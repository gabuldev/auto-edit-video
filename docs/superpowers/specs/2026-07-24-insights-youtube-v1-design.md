# Insights v1 (YouTube, read-only) — Design

**Data:** 2026-07-24
**Branch:** `feat/insights-youtube-v1`
**Sub-projeto:** SP-A do flywheel de crescimento (measure → learn → plan). Escopo: só ingestão YouTube read-only. Publish, feed no planner e Instagram são v2+.

---

## 1. Contexto e objetivo

O auto-edit hoje faz `plan → edit → publish` (manual). Falta a volta: puxar a performance dos vídeos publicados e guardar pra informar o conteúdo futuro. Este é o primeiro passo — **ingerir e armazenar os números do YouTube**, com um relatório pra leitura humana.

O consumidor final dos dados é o `auto-edit plan` (já mora em `AUTO_EDIT_HOME`), então o módulo mora no auto-edit.

### Decisões travadas (brainstorming)
- **v1 = só ingestão YT, read-only.** Sem publicar. Dado já existe (o usuário posta tudo no YT).
- **Home:** novo pacote `auto_edit/insights/`, store em `AUTO_EDIT_HOME/insights.db`.
- **Atribuição:** ingere o **canal inteiro**; linkar um vídeo a um workspace/template é enriquecimento opcional, não pré-requisito.
- **Feedback v1:** ingest + store + **relatório**. Sugestão automática pro planner é v2.
- **Multi-plataforma na costura:** comandos e schema carregam `platform` desde já; só YouTube é implementado. IG pluga depois via um novo connector.
- **Libs:** `google-auth-oauthlib` + `google-api-python-client` (oficiais).
- **Métricas:** conjunto normalizado + `raw_json` pro específico da plataforma.

### Não-objetivos (v2+)
- Publicar automático (YT/IG).
- Alimentar o `plan new` com performance.
- Connector de Instagram.
- Scheduler/worker (sync é comando manual; cron fica a cargo do usuário).

---

## 2. Arquitetura

Novo pacote `auto_edit/insights/` seguindo o padrão de `plan.py` (Typer sub-app montado no CLI principal via `app.add_typer`).

| Arquivo | Responsabilidade |
|---------|------------------|
| `auto_edit/insights/__init__.py` | expõe `insights_app` |
| `auto_edit/insights/store.py` | SQLite: schema + CRUD (espelha `content-creator/core/db.py`) |
| `auto_edit/insights/connector.py` | `Connector` protocol + dataclasses `VideoRef`/`MetricPoint` + registry por plataforma |
| `auto_edit/insights/youtube.py` | connector YouTube: OAuth + Data API v3 + Analytics API v2 |
| `auto_edit/insights/service.py` | orquestra sync/link/report — lógica pura sobre store+connector |
| `auto_edit/insights/cli.py` | comandos Typer (`auth`/`sync`/`link`/`report`) |

`auto_edit/config.py` ganha `insights_db_path()` e `tokens_dir()`.

**Fluxo de dados:**
```
insights sync <platform>
  → Connector.list_videos()  (Data API: uploads do canal)
  → Connector.fetch_metrics(video_ids)  (Analytics API: métricas)
  → store.upsert_video(...) + store.add_snapshot(...)
insights link <ws|video> <url>
  → resolve (platform, video_id) da URL → store.link_video(template/topic do metadata.json)
insights report
  → store.query → service.aggregate → tabela (rich)
```

---

## 3. Store (SQLite)

`AUTO_EDIT_HOME/insights.db`. Padrão de `core/db.py`: `connect()` cria schema idempotente + `_migrate()`.

```sql
CREATE TABLE IF NOT EXISTS videos (
  platform          TEXT NOT NULL,           -- 'youtube' | 'instagram' (futuro)
  platform_video_id TEXT NOT NULL,
  title             TEXT NOT NULL DEFAULT '',
  url               TEXT NOT NULL DEFAULT '',
  thumbnail_url     TEXT NOT NULL DEFAULT '',
  published_at      TEXT,                     -- ISO 8601
  workspace_path    TEXT,                     -- link opcional
  template          TEXT,                     -- do metadata.json (thumbnail.template)
  topic             TEXT,                     -- do contexto/metadata
  linked_at         TEXT,
  created_at        TEXT NOT NULL,
  PRIMARY KEY (platform, platform_video_id)
);

CREATE TABLE IF NOT EXISTS metric_snapshots (
  id                INTEGER PRIMARY KEY AUTOINCREMENT,
  platform          TEXT NOT NULL,
  platform_video_id TEXT NOT NULL,
  fetched_at        TEXT NOT NULL,            -- ISO 8601, quando o sync rodou
  views             INTEGER,
  reach             INTEGER,                  -- impressions (YT) / reach (IG)
  watch_time_min    REAL,                     -- estimatedMinutesWatched
  avg_view_pct      REAL,                     -- averageViewPercentage (retenção) — nullable
  ctr               REAL,                     -- impressionClickThroughRate — nullable
  likes             INTEGER,
  comments          INTEGER,
  shares            INTEGER,
  saves             INTEGER,                  -- IG (nullable no YT)
  followers_gained  INTEGER,                  -- subscribersGained (YT) / followers (IG)
  raw_json          TEXT NOT NULL DEFAULT '{}',
  FOREIGN KEY (platform, platform_video_id) REFERENCES videos(platform, platform_video_id)
);
```

**Funções (store.py):**
- `connect(db_path: Path) -> sqlite3.Connection`
- `upsert_video(conn, platform, platform_video_id, *, title, url, thumbnail_url, published_at) -> None` — INSERT ... ON CONFLICT(platform, platform_video_id) DO UPDATE (não sobrescreve campos de link).
- `link_video(conn, platform, platform_video_id, *, workspace_path, template, topic) -> bool` — seta campos de link + `linked_at`; retorna False se o vídeo não existe.
- `add_snapshot(conn, platform, platform_video_id, point: dict) -> None` — anexa snapshot (nunca sobrescreve).
- `latest_snapshots(conn, platform=None) -> list[dict]` — último snapshot por vídeo (via `MAX(fetched_at)`), joinado com `videos`.
- `list_videos(conn, platform=None) -> list[dict]`.

Métricas ausentes numa plataforma entram como `None` (coluna nullable) e o valor cru fica em `raw_json`.

---

## 4. Connector (costura de plataforma)

`connector.py` define o contrato que YT (v1) e IG (v2) implementam.

```python
from dataclasses import dataclass, field
from typing import Protocol

@dataclass
class VideoRef:
    platform_video_id: str
    title: str
    url: str
    thumbnail_url: str
    published_at: str  # ISO 8601

@dataclass
class MetricPoint:
    platform_video_id: str
    views: int | None = None
    reach: int | None = None
    watch_time_min: float | None = None
    avg_view_pct: float | None = None
    ctr: float | None = None
    likes: int | None = None
    comments: int | None = None
    shares: int | None = None
    saves: int | None = None
    followers_gained: int | None = None
    raw: dict = field(default_factory=dict)

class Connector(Protocol):
    platform: str
    def authenticate(self) -> None: ...
    def list_videos(self, since: str | None = None) -> list[VideoRef]: ...
    def fetch_metrics(self, video_ids: list[str]) -> list[MetricPoint]: ...
    @staticmethod
    def video_id_from_url(url: str) -> str | None: ...
```

Registry: `get_connector(platform: str) -> Connector` — dict `{"youtube": YouTubeConnector}`. Plataforma desconhecida → erro claro listando as disponíveis.

`MetricPoint.as_store_dict()` mapeia pros campos do `add_snapshot`.

---

## 5. Connector YouTube (`youtube.py`)

**APIs:**
- **Data API v3** — `channels.list(mine=True, part=contentDetails)` → uploads playlist; `playlistItems.list` → video IDs, títulos, thumbnails, publishedAt. (paginado)
- **Analytics API v2** — `reports.query` com `ids=channel==MINE`, `dimensions=video`, `filters=video==<ids>` (lotes de até ~200), `metrics=views,estimatedMinutesWatched,averageViewPercentage,likes,comments,shares,subscribersGained`. CTR e impressions vêm de `metrics=impressions,impressionClickThroughRate` (endpoint aceita esses no relatório por vídeo). Se a query de CTR falhar/estiver vazia, deixa `None` (não quebra o sync).

**OAuth 2.0 (installed app):**
- Client secret: caminho via env `AUTO_EDIT_YT_CLIENT_SECRET` (JSON baixado do Google Cloud). Se ausente → erro acionável com o passo-a-passo.
- `authenticate()`: `InstalledAppFlow.from_client_secrets_file(...).run_local_server()` na 1ª vez; guarda o refresh token em `AUTO_EDIT_HOME/tokens/youtube.json` (chmod 600). Depois, `Credentials.from_authorized_user_file` + refresh silencioso.
- Escopos: `youtube.readonly` + `yt-analytics.readonly`.

**Setup do Google Cloud (documentado no README/spec, o usuário faz — igual ao app IG):**
1. Criar projeto no Google Cloud Console.
2. Habilitar "YouTube Data API v3" e "YouTube Analytics API".
3. OAuth consent screen (External, modo Testing) — adicionar a própria conta como test user.
4. Criar credencial OAuth client ID tipo **Desktop app** → baixar o JSON → apontar `AUTO_EDIT_YT_CLIENT_SECRET` pra ele.

`video_id_from_url` reconhece `youtube.com/watch?v=`, `youtu.be/`, `youtube.com/shorts/`.

---

## 6. Service (`service.py`) — lógica pura, testável

- `sync(conn, connector, since=None) -> SyncResult` — chama `list_videos` + `fetch_metrics`, faz upsert + add_snapshot; retorna contagem (vídeos vistos, snapshots gravados).
- `link(conn, url, workspace_path) -> LinkResult` — deriva `(platform, video_id)` da URL (via connectors), lê `template`/`topic` do `metadata.json` do workspace, chama `store.link_video`. Erro claro se URL não bate com nenhuma plataforma ou vídeo não está no store (dica: rodar `sync` antes).
- `build_report(conn, platform=None, by=None, top=None) -> list[ReportRow]` — pega `latest_snapshots`, ordena por views desc; se `by in ("template","topic")` agrega (média de ctr/avg_view_pct, soma de views) só sobre vídeos linkados que têm o campo.

`ReportRow`/`SyncResult`/`LinkResult` = dataclasses. `metadata.json` do workspace: `template` de `thumbnail.template`; `topic` de `pipeline.json.context` (ou `metadata.topic` se existir).

---

## 7. CLI (`cli.py`) — `insights_app`

Montado em `cli.py`: `app.add_typer(insights_app, name="insights")`.

```
auto-edit insights auth [PLATFORM=youtube]
    Roda o fluxo OAuth e guarda o token. Erro acionável se faltar client secret.

auto-edit insights sync [PLATFORM=youtube] [--since YYYY-MM-DD]
    Puxa uploads + métricas do canal → upsert vídeos + anexa snapshots.
    Imprime resumo: N vídeos, M snapshots.

auto-edit insights link WORKSPACE_OR_VIDEO URL [-p/--platform auto]
    Marca template/topic (lidos do metadata.json do workspace). Plataforma
    inferida da URL por padrão.

auto-edit insights report [-p/--platform] [--by template|topic] [--top N]
    Tabela rich: título, views, watch-time, retenção, ctr, likes… Sem -p = todas.
    --by agrega por template/topic (fecha o loop de CTR por template).
```

---

## 8. Config, deps, secrets

- `config.py`: `insights_db_path() -> home_dir()/"insights.db"`; `tokens_dir() -> home_dir()/"tokens"` (criado com mode 700).
- `pyproject.toml`: adicionar `google-auth-oauthlib` e `google-api-python-client`.
- `.gitignore`: garantir que `AUTO_EDIT_HOME` já fica fora do repo (fica — é `~/.auto-edit`). O client secret e o token **nunca** entram no repo.
- CLAUDE.md: nova env var `AUTO_EDIT_YT_CLIENT_SECRET` na tabela.

---

## 9. Testes

Sem rede real. `tests/test_insights_store.py`, `tests/test_insights_service.py`, `tests/test_insights_youtube.py`.

- **store**: schema cria; `upsert_video` idempotente e não apaga link; `link_video` retorna False p/ vídeo inexistente; `add_snapshot` anexa (2 snapshots → 2 linhas); `latest_snapshots` pega o mais recente por vídeo; filtro por `platform`.
- **connector/youtube (parse)**: `video_id_from_url` cobre watch?v=, youtu.be, shorts; parse de uma resposta fake do Data API → `VideoRef`; parse de uma resposta fake do Analytics → `MetricPoint` (com CTR ausente → `None`). API client mockado (monkeypatch do objeto `service`/`googleapiclient`), nada de rede.
- **service**: `sync` sobre um connector fake (in-memory) grava o esperado; `link` lê template/topic de um metadata.json de fixture e seta no store; `link` erra claro p/ URL inválida; `build_report --by template` agrega só linkados.

Rodar: `python -m pytest tests/ -v` e `ruff check auto_edit/ tests/ --select E,F,W --ignore E501`.

---

## 10. Riscos / decisões abertas

- **N pequeno** — poucos vídeos = sinal ruidoso. v1 só mostra dado cru; interpretação fica com o humano. Sugestão automática (v2) só depois de volume.
- **Quotas da API** — Data + Analytics têm cota diária. Sync do canal inteiro é barato pra poucos vídeos; se crescer, paginar/limitar com `--since`.
- **CTR/impressions no Analytics por vídeo** — alguns cortes de relatório restringem essas métricas; se vier vazio, degrada pra `None` sem quebrar.
- **Setup do Google Cloud é manual** — documentado; sem isso o `auth` falha com instrução clara.
