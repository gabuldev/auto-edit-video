# Metadata Performance Feedback — Design

**Data:** 2026-07-30
**Branch:** `feat/metadata-performance-feedback`
**Sub-projeto:** fecha o loop measure → learn no stage `metadata` da edição. Depende do módulo `insights` (já mergeado, PR #39).

---

## 1. Contexto e objetivo

Hoje o pipeline de edição não usa as métricas do `insights.db`. Ao editar um vídeo, o stage `metadata` (que gera `short_title`/`youtube_title`, `hook`, `hashtags` e o objeto `thumbnail` — `main_text`/`sub_text`/`template`) só recebe a transcrição + contexto.

**Objetivo:** injetar no prompt do stage `metadata` um resumo da performance do canal — os vídeos de **melhor e pior retenção do mesmo tipo** (short vs long) do vídeo sendo editado — para o agente imitar o padrão de tema/gancho que retém e evitar o que não retém.

### Decisões travadas (brainstorming)
- **Ponto de injeção:** stage `metadata` (por vídeo). Planner (`plan new`) fica pra depois.
- **Sinal:** top/piores por **retenção** (`avg_view_pct`) — título + retenção% + views. O agente infere o padrão. CTR não existe na API (ver [[project_youtube_ctr_limitation]]).
- **Segmentado por tipo (short/long):** baselines de retenção diferem muito entre short e long. Guarda `duration_sec` por vídeo e deriva o tipo por threshold.
- **Graciosa:** sem `insights.db` / vazio / sem vídeos do tipo → sem seção, edição intacta.

### Não-objetivos (v2+)
- Feedback por template (precisa de link workspace↔vídeo; 0 linkados hoje).
- Feed no `plan new`.
- CTR (não disponível na Analytics API de canal).
- Resumo pré-processado por um LLM separado.

---

## 2. Arquitetura

Fluxo: `runner.build_prompt("metadata", ...)` → chama `insights.service.performance_brief(conn, kind)` → injeta a seção no prompt. O `kind` (`short`/`long`) vem do `video_type` do pipeline. A agregação mora no `insights`; o `runner` só injeta.

Pré-requisito de dado: `duration_sec` por vídeo. Preenchido no `sync` via Data API (`videos.list(part=contentDetails)`). **Precisa re-sync** pra backfill dos 432 vídeos já no store (o `sync` é idempotente — só anexa snapshot + atualiza duração).

---

## 3. Store — coluna `duration_sec`

`videos` ganha `duration_sec INTEGER` (nullable). Migração pro db existente (padrão `_migrate` como o content-creator faz):

```python
def _migrate(conn) -> None:
    cols = {r[1] for r in conn.execute("PRAGMA table_info(videos)")}
    if "duration_sec" not in cols:
        conn.execute("ALTER TABLE videos ADD COLUMN duration_sec INTEGER")
        conn.commit()
```
Chamado dentro de `connect()` após `executescript(_SCHEMA)`.

`upsert_video(...)` ganha kwarg `duration_sec: int | None = None` e o inclui no INSERT + no `ON CONFLICT DO UPDATE` (atualiza a duração ao re-sync).

`latest_snapshots` já faz `SELECT v.*` — passa a trazer `duration_sec` automaticamente. Nada muda lá.

---

## 4. Connector — `VideoRef.duration_sec`

`VideoRef` ganha `duration_sec: int | None = None`. `service.sync` passa `duration_sec=v.duration_sec` pro `upsert_video`.

---

## 5. YouTube — enriquecer durações

`youtube._parse_duration(iso: str) -> int | None` — parse de ISO 8601 (`PT#H#M#S`) pra segundos. Regex `PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?`. `None` se não casar.

`YouTubeConnector.list_videos` — depois de montar os `VideoRef` das uploads, busca durações em lote via `videos.list(part="contentDetails", id=",".join(batch de 50))` e preenche `ref.duration_sec` via um map `{video_id: duration_sec}`. Um helper `_fetch_durations(self, ids) -> dict[str, int]`.

Teste com serviço fake: um `_FakeData.videos()` que devolve `contentDetails.duration`.

---

## 6. Service — `performance_brief`

```python
SHORT_MAX_SEC = 180  # <= isso conta como short (ajustável)

def performance_brief(conn, kind: str | None = None, top: int = 8, bottom: int = 4) -> str
```
- Lê `latest_snapshots(conn, "youtube")` (ou todas plataformas; v1 só YT).
- Filtra linhas com `avg_view_pct` não-None **e** `duration_sec` não-None.
- Deriva o tipo de cada linha: `"short" if duration_sec <= SHORT_MAX_SEC else "long"`.
- Se `kind` dado, filtra por ele.
- Ordena por `avg_view_pct` desc. Pega `top` do início e `bottom` do fim (sem sobreposição — se houver menos que `top+bottom` vídeos, divide sem repetir).
- Retorna markdown:
  ```
  ### Maior retenção (teus {kind}s)
  - "<title>" — <ret>% retenção, <views> views
  ...
  ### Menor retenção (teus {kind}s)
  - "<title>" — <ret>% retenção, <views> views
  ```
- String vazia se < 3 vídeos do tipo com dado (amostra pequena demais pra sinal).

`_derive_kind(duration_sec) -> str` helper puro, testável.

---

## 7. Runner — injeção no stage metadata

Em `runner.build_prompt`, no bloco `elif stage == "metadata"`, após a seção de transcrição:

```python
brief = _performance_section(video_type)
if brief:
    sections += ["\n## O que retém no teu canal (sinal, não regra)", brief,
                 "Imita o padrão de TEMA e GANCHO dos de maior retenção e evita o dos de menor — "
                 "sem copiar títulos, priorizando o que combina com ESTE vídeo."]
```

`_performance_section(video_type: str) -> str` (em runner.py):
- Mapeia `video_type` → `kind` (`"short"`→`"short"`, senão `"long"`).
- `try`: abre `store.connect(cfg.insights_db_path())` se o arquivo existe; chama `service.performance_brief(conn, kind)`; retorna.
- `except Exception`: retorna `""` (nunca quebra a edição). Também `""` se o db não existe.

Import lazy dentro da função (evita acoplar o runner ao insights no import time; e mantém a edição funcionando se o módulo insights sumir).

---

## 8. Prompt — `agents/metadata.md`

Nota curta (condicional) no fim da seção de instruções:

```markdown
## Performance do canal (quando presente)

Se o prompt trouxer uma seção "O que retém no teu canal", use-a como sinal —
não como regra. Os vídeos de maior retenção mostram que tema/ângulo/gancho
seguram a audiência; os de menor mostram o que evitar. Ajuste `main_text`,
`sub_text`, `hook` e a escolha de `template` nessa direção, sempre priorizando
o que é fiel a ESTE vídeo. Amostra pequena = trate como dica, não lei.
```

---

## 9. Testes

Sem rede. `tests/test_insights_service.py`, `tests/test_insights_youtube.py`, `tests/test_insights_store.py`, `tests/test_runner_*` (ou onde o runner já é testado).

- **store**: `_migrate` adiciona `duration_sec` num db pré-existente sem a coluna; `upsert_video` grava/atualiza `duration_sec`.
- **youtube**: `_parse_duration` cobre `PT1M30S`→90, `PT45S`→45, `PT1H2M3S`→3723, lixo→None. `list_videos` com fakes preenche `duration_sec`.
- **service**: `_derive_kind` (limite 180); `performance_brief` filtra por kind, ordena por retenção, corta top/bottom sem sobreposição, retorna "" com amostra < 3; ignora linhas sem `avg_view_pct`/`duration_sec`.
- **runner**: `_performance_section` retorna "" quando o db não existe; injeta a seção quando o db tem dados do tipo; mapeia `video_type` long→long.

Rodar: `.venv/bin/python -m pytest tests/ -v` e `ruff check auto_edit/ tests/ --select E,F,W --ignore E501`.

---

## 10. Riscos / decisões abertas

- **Backfill:** vídeos já no store têm `duration_sec` NULL até o próximo `sync`. `performance_brief` ignora NULL → seção vazia até re-sync. Documentar (rodar `auto-edit insights sync youtube`).
- **Heurística de tipo:** `duration <= 180s = short`. Não é a definição oficial de Short do YouTube, mas casa com o short/long do auto-edit. Threshold é constante ajustável.
- **N pequeno:** retenção com poucos vídeos de um tipo é ruidosa — daí o corte em < 3 vídeos e o enquadramento "sinal, não regra" no prompt.
- **Quota:** `videos.list` adiciona ~1 unidade por 50 vídeos no sync. Desprezível.
