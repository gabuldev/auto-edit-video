# Metadata Performance Feedback Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Injetar no prompt do stage `metadata` um resumo dos vídeos de melhor/pior retenção do mesmo tipo (short/long) do canal, pra o agente imitar o padrão de tema/gancho que retém.

**Architecture:** Guarda `duration_sec` por vídeo no store do insights (preenchido no sync via Data API). `service.performance_brief(conn, kind)` agrega top/piores por retenção filtrado por tipo. `runner.build_prompt` (stage metadata) injeta a seção, com degradação graciosa se não houver `insights.db`.

**Tech Stack:** Python 3.11+, SQLite (stdlib), google-api-python-client, pytest, ruff.

## Global Constraints

- Python >= 3.11. Sem rede real em testes (connectors/clients mockados).
- `duration_sec` é `INTEGER` nullable em `videos`; migração idempotente pro db existente (`_migrate` no `connect()`).
- Threshold de tipo: `SHORT_MAX_SEC = 180` (duration_sec <= 180 → "short", senão "long"). Constante ajustável.
- `performance_brief` retorna `""` se < 3 vídeos do tipo com dado (`avg_view_pct` e `duration_sec` não-None). Top 8 / piores 4, sem sobreposição.
- Degradação graciosa: sem `insights.db` / vazio / qualquer erro → runner injeta nada, edição intacta.
- Re-upsert com `duration_sec=None` NÃO apaga a duração existente (usar `COALESCE`).
- Testes: `.venv/bin/python -m pytest tests/ -v`. Lint: `.venv/bin/ruff check auto_edit/ tests/ --select E,F,W --ignore E501`. (system python3 é 3.9 e quebra a coleta — usar `.venv/bin/python`.)
- Trabalhar na branch `feat/metadata-performance-feedback`.

---

### Task 1: Store — coluna `duration_sec` + migração

**Files:**
- Modify: `auto_edit/insights/store.py`
- Test: `tests/test_insights_store.py`

**Interfaces:**
- Produces: `_migrate(conn) -> None`; `connect` chama `_migrate`; `upsert_video(..., duration_sec: int | None = None)` grava/atualiza a duração (COALESCE preserva a existente se a nova for None).

- [ ] **Step 1: Testes que falham**

Adicionar em `tests/test_insights_store.py`:

```python
import sqlite3 as _sqlite3


class TestDurationColumn:
    def test_migrate_adds_column_to_old_db(self, tmp_path):
        # db pré-existente SEM duration_sec
        path = tmp_path / "old.db"
        raw = _sqlite3.connect(str(path))
        raw.execute(
            "CREATE TABLE videos (platform TEXT, platform_video_id TEXT, "
            "title TEXT, url TEXT, thumbnail_url TEXT, published_at TEXT, "
            "workspace_path TEXT, template TEXT, topic TEXT, linked_at TEXT, "
            "created_at TEXT, PRIMARY KEY (platform, platform_video_id))"
        )
        raw.commit()
        raw.close()
        conn = st.connect(path)
        cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
        assert "duration_sec" in cols

    def test_upsert_stores_and_preserves_duration(self, tmp_path):
        conn = st.connect(tmp_path / "d.db")
        st.upsert_video(conn, "youtube", "v1", title="A", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=90)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 90
        # re-sync sem duração NÃO apaga
        st.upsert_video(conn, "youtube", "v1", title="A2", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=None)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 90
        # re-sync com nova duração atualiza
        st.upsert_video(conn, "youtube", "v1", title="A3", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=200)
        assert st.list_videos(conn, "youtube")[0]["duration_sec"] == 200
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py::TestDurationColumn -v`
Expected: FAIL — `upsert_video() got an unexpected keyword argument 'duration_sec'` / coluna ausente.

- [ ] **Step 3: Implementar**

Em `auto_edit/insights/store.py`, no `_SCHEMA`, adicionar a coluna na tabela `videos` (após `published_at`):

```
  published_at      TEXT,
  duration_sec      INTEGER,
```

Adicionar a função de migração (após `_METRIC_COLS`):

```python
def _migrate(conn: sqlite3.Connection) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    if "duration_sec" not in cols:
        conn.execute("ALTER TABLE videos ADD COLUMN duration_sec INTEGER")
        conn.commit()
```

No `connect`, chamar `_migrate` após o `executescript`:

```python
    conn.executescript(_SCHEMA)
    _migrate(conn)
    return conn
```

Trocar `upsert_video` por (adiciona `duration_sec`):

```python
def upsert_video(conn, platform, platform_video_id, *, title, url,
                 thumbnail_url, published_at, duration_sec=None) -> None:
    conn.execute(
        """
        INSERT INTO videos (platform, platform_video_id, title, url,
                            thumbnail_url, published_at, duration_sec, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
        ON CONFLICT(platform, platform_video_id) DO UPDATE SET
          title = excluded.title,
          url = excluded.url,
          thumbnail_url = excluded.thumbnail_url,
          published_at = excluded.published_at,
          duration_sec = COALESCE(excluded.duration_sec, videos.duration_sec)
        """,
        (platform, platform_video_id, title, url, thumbnail_url,
         published_at, duration_sec, _now()),
    )
    conn.commit()
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_insights_store.py -v`
Expected: PASS (todos, incl. os antigos).

- [ ] **Step 5: Commit**

```bash
git add auto_edit/insights/store.py tests/test_insights_store.py
git commit -m "feat: duration_sec no store do insights (+ migração)"
```

---

### Task 2: YouTube — parse de duração + enriquecer no sync

**Files:**
- Modify: `auto_edit/insights/connector.py` (campo em `VideoRef`)
- Modify: `auto_edit/insights/youtube.py`
- Test: `tests/test_insights_youtube.py`

**Interfaces:**
- Consumes: `VideoRef` (Task já existente).
- Produces: `VideoRef.duration_sec: int | None = None`; `youtube._parse_duration(iso: str) -> int | None`; `YouTubeConnector.list_videos` popula `duration_sec` via `videos.list(part=contentDetails)`.

- [ ] **Step 1: Testes que falham**

Adicionar em `tests/test_insights_youtube.py`:

```python
from auto_edit.insights.youtube import _parse_duration


class TestParseDuration:
    def test_minutes_seconds(self):
        assert _parse_duration("PT1M30S") == 90

    def test_seconds_only(self):
        assert _parse_duration("PT45S") == 45

    def test_hours(self):
        assert _parse_duration("PT1H2M3S") == 3723

    def test_garbage(self):
        assert _parse_duration("banana") is None
```

Adicionar um `videos()` ao `_FakeData` (na classe já existente do arquivo) e um teste que `list_videos` preenche a duração. Estender `_FakeData`:

```python
    def videos(self):
        class V:
            def list(inner, **kw):
                return _FakeReq({"items": [
                    {"id": "v1", "contentDetails": {"duration": "PT2M10S"}}]})
        return V()
```

E o teste (na `TestYouTubeApiCalls`):

```python
    def test_list_videos_enriches_duration(self):
        c = _connector_with_fakes()
        refs = c.list_videos()
        assert refs[0].duration_sec == 130  # PT2M10S
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py -v`
Expected: FAIL — `cannot import name '_parse_duration'`.

- [ ] **Step 3: Implementar — campo em VideoRef**

Em `auto_edit/insights/connector.py`, no dataclass `VideoRef`, adicionar o campo (após `published_at`):

```python
    published_at: str  # ISO 8601
    duration_sec: int | None = None
```

- [ ] **Step 4: Implementar — parse + enriquecimento**

Em `auto_edit/insights/youtube.py`, adicionar o regex/parse (perto do topo, após `_SHORTS_RE`):

```python
_DURATION_RE = re.compile(r"^PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?$")


def _parse_duration(iso: str) -> int | None:
    m = _DURATION_RE.match(iso or "")
    if not m or not any(m.groups()):
        return None
    h, mi, s = (int(x) if x else 0 for x in m.groups())
    return h * 3600 + mi * 60 + s
```

Adicionar o método de fetch e chamar no `list_videos`. Depois do loop que monta `refs` (antes do filtro `if since:`), inserir:

```python
        durations = self._fetch_durations([r.platform_video_id for r in refs])
        for r in refs:
            r.duration_sec = durations.get(r.platform_video_id)
```

E o helper na classe:

```python
    def _fetch_durations(self, ids: list[str]) -> dict[str, int]:
        out: dict[str, int] = {}
        for batch in _chunks(ids, 50):
            resp = self._data.videos().list(
                part="contentDetails", id=",".join(batch), maxResults=50,
            ).execute()
            for it in resp.get("items", []):
                dur = _parse_duration(
                    it.get("contentDetails", {}).get("duration", ""))
                if dur is not None:
                    out[it["id"]] = dur
        return out
```

- [ ] **Step 5: Rodar e ver passar + full suite + ruff**

Run: `.venv/bin/python -m pytest tests/test_insights_youtube.py -v`
Expected: PASS
Run: `.venv/bin/python -m pytest tests/ -q` (nada quebrou)
Run: `.venv/bin/ruff check auto_edit/insights/ tests/test_insights_youtube.py --select E,F,W --ignore E501`

- [ ] **Step 6: Commit**

```bash
git add auto_edit/insights/connector.py auto_edit/insights/youtube.py tests/test_insights_youtube.py
git commit -m "feat: enriquece duração dos vídeos no sync do youtube"
```

---

### Task 3: Service — `performance_brief` + sync passa duração

**Files:**
- Modify: `auto_edit/insights/service.py`
- Test: `tests/test_insights_service.py`

**Interfaces:**
- Consumes: `store.latest_snapshots`, `store.upsert_video(duration_sec=...)`, `VideoRef.duration_sec` (Tasks 1–2).
- Produces: `SHORT_MAX_SEC = 180`; `_derive_kind(duration_sec: int | None) -> str | None`; `performance_brief(conn, kind: str | None = None, top: int = 8, bottom: int = 4) -> str`. `sync` passa `duration_sec=v.duration_sec`.

- [ ] **Step 1: Testes que falham**

Adicionar em `tests/test_insights_service.py`:

```python
class TestDeriveKind:
    def test_short_and_long(self):
        assert svc._derive_kind(60) == "short"
        assert svc._derive_kind(180) == "short"
        assert svc._derive_kind(181) == "long"
        assert svc._derive_kind(None) is None


class TestPerformanceBrief:
    def _seed(self, conn, vid, dur, ret, views):
        st.upsert_video(conn, "youtube", vid, title=f"T{vid}", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=dur)
        st.add_snapshot(conn, "youtube", vid,
                        {"avg_view_pct": ret, "views": views})

    def test_filters_by_kind_and_orders(self, tmp_path):
        conn = st.connect(tmp_path / "b.db")
        # 3 shorts + 1 long
        self._seed(conn, "s1", 30, 80.0, 100)
        self._seed(conn, "s2", 40, 50.0, 200)
        self._seed(conn, "s3", 50, 65.0, 150)
        self._seed(conn, "l1", 600, 40.0, 999)
        brief = svc.performance_brief(conn, kind="short", top=2, bottom=1)
        assert "T s1" not in brief  # título é "Ts1"
        assert "Ts1" in brief and "Ts2" in brief  # melhor e pior entram
        assert "Tl1" not in brief  # long fica de fora
        # melhor retenção (s1, 80%) aparece antes do pior (s2, 50%)
        assert brief.index("Ts1") < brief.index("Ts2")

    def test_empty_when_small_sample(self, tmp_path):
        conn = st.connect(tmp_path / "s.db")
        self._seed(conn, "s1", 30, 80.0, 100)
        self._seed(conn, "s2", 40, 50.0, 200)  # só 2 shorts (< 3)
        assert svc.performance_brief(conn, kind="short") == ""

    def test_ignores_rows_without_metrics(self, tmp_path):
        conn = st.connect(tmp_path / "n.db")
        # vídeo sem snapshot / sem duração não entra
        st.upsert_video(conn, "youtube", "x", title="X", url="u",
                        thumbnail_url="t", published_at=None, duration_sec=None)
        assert svc.performance_brief(conn, kind="short") == ""
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_insights_service.py::TestDeriveKind tests/test_insights_service.py::TestPerformanceBrief -v`
Expected: FAIL — `module 'auto_edit.insights.service' has no attribute '_derive_kind'`.

- [ ] **Step 3: Implementar**

Em `auto_edit/insights/service.py`, adicionar após os imports:

```python
SHORT_MAX_SEC = 180


def _derive_kind(duration_sec: int | None) -> str | None:
    if duration_sec is None:
        return None
    return "short" if duration_sec <= SHORT_MAX_SEC else "long"


def performance_brief(conn, kind: str | None = None, top: int = 8,
                      bottom: int = 4) -> str:
    rows = [
        r for r in store.latest_snapshots(conn, "youtube")
        if r.get("avg_view_pct") is not None and r.get("duration_sec") is not None
    ]
    if kind:
        rows = [r for r in rows if _derive_kind(r["duration_sec"]) == kind]
    if len(rows) < 3:
        return ""
    rows.sort(key=lambda r: r["avg_view_pct"], reverse=True)
    best = rows[:top]
    worst = [r for r in rows[-bottom:] if r not in best]
    label = f"teus {kind}s" if kind else "teu canal"

    def _line(r: dict) -> str:
        return (f'- "{r.get("title", "")}" — {round(r["avg_view_pct"], 1)}% '
                f'retenção, {r.get("views") or 0} views')

    parts = [f"### Maior retenção ({label})"]
    parts += [_line(r) for r in best]
    if worst:
        parts.append(f"### Menor retenção ({label})")
        parts += [_line(r) for r in worst]
    return "\n".join(parts)
```

Na função `sync`, passar a duração no `upsert_video`:

```python
        store.upsert_video(
            conn, conn_obj.platform, v.platform_video_id,
            title=v.title, url=v.url, thumbnail_url=v.thumbnail_url,
            published_at=v.published_at, duration_sec=v.duration_sec,
        )
```

- [ ] **Step 4: Rodar e ver passar**

Run: `.venv/bin/python -m pytest tests/test_insights_service.py -v`
Expected: PASS (todos).

- [ ] **Step 5: Commit**

```bash
git add auto_edit/insights/service.py tests/test_insights_service.py
git commit -m "feat: performance_brief por tipo + sync grava duração"
```

---

### Task 4: Runner — injeção no stage metadata + nota no prompt

**Files:**
- Modify: `auto_edit/runner.py`
- Modify: `agents/metadata.md`
- Test: `tests/test_runner_prompt.py`

**Interfaces:**
- Consumes: `insights.store.connect`, `insights.service.performance_brief`, `config.insights_db_path` (Tasks 1–3).
- Produces: `runner._performance_section(video_type: str) -> str`; injeção no bloco `stage == "metadata"` de `build_prompt`.

- [ ] **Step 1: Testes que falham**

Adicionar em `tests/test_runner_prompt.py`:

```python
from auto_edit import config as cfg
from auto_edit.insights import store as ist


class TestPerformanceSection:
    def test_empty_when_no_db(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        assert runner._performance_section("short") == ""

    def test_injects_when_db_has_data(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        conn = ist.connect(cfg.insights_db_path())
        for i, ret in enumerate([80.0, 60.0, 40.0]):
            ist.upsert_video(conn, "youtube", f"s{i}", title=f"Vid{i}", url="u",
                             thumbnail_url="t", published_at=None, duration_sec=30)
            ist.add_snapshot(conn, "youtube", f"s{i}",
                             {"avg_view_pct": ret, "views": 100})
        conn.close()
        section = runner._performance_section("short")
        assert "retenção" in section
        assert "Vid0" in section
```

- [ ] **Step 2: Rodar e ver falhar**

Run: `.venv/bin/python -m pytest tests/test_runner_prompt.py::TestPerformanceSection -v`
Expected: FAIL — `module 'auto_edit.runner' has no attribute '_performance_section'`.

- [ ] **Step 3: Implementar — helper**

Em `auto_edit/runner.py`, adicionar a função (perto dos outros helpers de leitura, ex: após `_read_json_optional`):

```python
def _performance_section(video_type: str) -> str:
    """Resumo de retenção do canal (do insights.db) pro tipo do vídeo.

    Degrada pra "" se o insights não estiver disponível — nunca quebra a edição.
    """
    kind = "short" if video_type == "short" else "long"
    try:
        from auto_edit import config as cfg
        from auto_edit.insights import service as isvc
        from auto_edit.insights import store as ist

        db_path = cfg.insights_db_path()
        if not db_path.exists():
            return ""
        conn = ist.connect(db_path)
        return isvc.performance_brief(conn, kind=kind)
    except Exception:
        return ""
```

- [ ] **Step 4: Implementar — injeção no metadata**

Em `build_prompt`, no bloco `elif stage == "metadata":`, após a lista `sections += [...]` (depois de `text`), adicionar:

```python
        brief = _performance_section(video_type)
        if brief:
            sections += [
                "\n## O que retém no teu canal (sinal, não regra)",
                brief,
                "Imita o padrão de TEMA e GANCHO dos de maior retenção e evita o "
                "dos de menor — sem copiar títulos, priorizando o que é fiel a "
                "ESTE vídeo.",
            ]
```

- [ ] **Step 5: Nota no prompt do agente**

Em `agents/metadata.md`, adicionar antes da seção `## Output Format`:

```markdown
## Performance do canal (quando presente)

Se o prompt trouxer uma seção "O que retém no teu canal", use-a como sinal —
não como regra. Os de maior retenção mostram que tema/ângulo/gancho seguram a
audiência; os de menor, o que evitar. Ajuste `main_text`, `sub_text`, `hook` e
a escolha de `template` nessa direção, sempre fiel a ESTE vídeo. Amostra
pequena = trate como dica, não lei.
```

- [ ] **Step 6: Rodar e ver passar + full suite + ruff**

Run: `.venv/bin/python -m pytest tests/test_runner_prompt.py -v`
Expected: PASS
Run: `.venv/bin/python -m pytest tests/ -q`
Expected: tudo verde
Run: `.venv/bin/ruff check auto_edit/ tests/ --select E,F,W --ignore E501`
Expected: sem erros

- [ ] **Step 7: Commit**

```bash
git add auto_edit/runner.py agents/metadata.md tests/test_runner_prompt.py
git commit -m "feat: injeta resumo de retenção do canal no stage metadata"
```

---

## Self-Review

**Spec coverage:**
- §3 store `duration_sec` + migração → Task 1. ✓
- §4 `VideoRef.duration_sec` → Task 2. ✓
- §5 youtube parse + enriquecimento → Task 2. ✓
- §6 service `performance_brief`/`_derive_kind` + sync duração → Task 3. ✓
- §7 runner injeção → Task 4. ✓
- §8 nota no metadata.md → Task 4 Step 5. ✓
- §9 testes (store/youtube/service/runner) → cada task; sem rede. ✓
- §10 backfill/graciosa → Task 4 (`_performance_section` try/except + db inexistente). ✓

**Placeholder scan:** Sem TBD/TODO. Todo step tem código/comando concreto. ✓

**Type consistency:** `duration_sec: int | None` consistente entre store/VideoRef/service. `_derive_kind(int|None)->str|None`, `performance_brief(conn, kind, top, bottom)->str` iguais entre definição (Task 3) e uso (Task 4). `upsert_video(..., duration_sec=None)` idêntico entre Task 1 (def) e Tasks 2/3 (chamada via sync). `_performance_section(video_type)->str` def e teste batem. ✓

**Nota de execução:** rodar pytest via `.venv/bin/python` (3.13); `python3` do sistema é 3.9 e quebra a coleta.
