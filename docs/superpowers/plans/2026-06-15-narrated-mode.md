# Narrated Mode Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a `narrated` pipeline type that turns a script + recorded voiceover + B-roll folder into an assembled, captioned video, with AI matching clips to script blocks and a human preview gate before render.

**Architecture:** New stage sequence (`parse-script → extract-vo → align-blocks → analyze-clips → match → review → assemble`) feeding the existing `caption → metadata → thumbnail` stages. The recorded voice is the timing spine: its transcription drives block timing and captions. AI (Gemini for vision, Claude for matching) proposes a clip map the user approves before `assemble` renders with ffmpeg.

**Tech Stack:** Python 3.11+, Typer CLI, Whisper, ffmpeg/ffprobe, pysubs2, Gemini API (vision), Claude CLI (agents), pytest.

**Spec:** `docs/superpowers/specs/2026-06-15-narrated-mode-design.md`

**Conventions (from CLAUDE.md):**
- Tests: `.venv/bin/python -m pytest tests/ -v`
- Lint: `.venv/bin/ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`
- ralph syntax: `bash -n ralph.sh`
- Never commit to `main` — work on branch `feat/narrated-mode` (already branched from `feat/narrated-mode-spec`; rebase onto main first if needed).
- Caption burn requires the Nix ffmpeg-full (has libass). Pure-logic tests do not burn, so they run on `.venv`.

---

## File Structure

**Create:**
- `tools/script_parser.py` — `parse-script` stage: freeform roteiro → `script.json`
- `tools/block_aligner.py` — `align-blocks` stage: voice transcription + blocks → `vo_alignment.json`
- `tools/clip_analyzer.py` — `analyze-clips` stage: B-roll frames → `clip_index.json` (Gemini vision)
- `tools/assembler.py` — `assemble` stage: `clip_map.json` → `edited_video.mp4` (ffmpeg)
- `agents/script_parser.md` — prompt for `parse-script`
- `agents/matcher.md` — prompt for `match`
- `tests/test_block_aligner.py`
- `tests/test_assembler.py`
- `tests/test_clip_analyzer.py`
- `tests/test_pipeline_sequences.py`

**Modify:**
- `auto_edit/pipeline.py` — replace global `STAGES`/skip with `STAGE_SEQUENCES` per type; extend `init()` with `voice_path`/`clips_dir`; per-type advance in `set_stage_status`/`loop_back`/`set_stage`
- `auto_edit/runner.py` — add `build_prompt` branches for `parse-script` and `match`
- `auto_edit/cli.py` — add `narrate` command + `review-broll` command; extend `_run_pipeline`
- `ralph.sh` — dispatch cases for `parse-script`, `extract-vo`, `align-blocks`, `analyze-clips`, `match`, `review` (pause), `assemble`
- `tools/extract.py` — let `extract` read an explicit audio path (`voice_path`) when present

**Reuse unchanged:** `tools/captioner.py`, `tools/thumbnailer.py`, `agents/metadata.md`, executor's reframe/audio-normalize logic (imported by `assembler.py`).

---

## Phase 0: Pipeline sequence refactor (foundation)

### Task 1: Per-type stage sequences in pipeline.py

**Files:**
- Modify: `auto_edit/pipeline.py:11-14` (STAGES + SKIP sets), `init()`, `set_stage_status()`, `loop_back()`, `set_stage()`
- Test: `tests/test_pipeline_sequences.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_pipeline_sequences.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from auto_edit import pipeline


def test_short_sequence_matches_legacy_order():
    seq = pipeline.stage_sequence("short")
    assert seq == ["extract", "plan", "review", "execute", "caption",
                   "evaluate", "metadata", "thumbnail", "done"]


def test_long_sequence_has_overlay_not_caption():
    seq = pipeline.stage_sequence("long")
    assert "overlay" in seq and "caption" not in seq


def test_narrated_sequence():
    seq = pipeline.stage_sequence("narrated")
    assert seq == ["parse-script", "extract-vo", "align-blocks",
                   "analyze-clips", "match", "review", "assemble",
                   "caption", "metadata", "thumbnail", "done"]


def test_init_materializes_only_sequence_stages(tmp_path):
    p = pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx")
    assert set(p["stages"]) == set(pipeline.stage_sequence("narrated")) - {"done"}
    assert "plan" not in p["stages"]


def test_set_stage_status_advances_within_type(tmp_path):
    pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx")
    p = pipeline.set_stage_status(tmp_path, "parse-script", "complete")
    assert p["current_stage"] == "extract-vo"
```

- [ ] **Step 2: Run test, verify it fails**

Run: `.venv/bin/python -m pytest tests/test_pipeline_sequences.py -v`
Expected: FAIL — `pipeline.stage_sequence` does not exist.

- [ ] **Step 3: Implement STAGE_SEQUENCES + stage_sequence()**

Replace lines 11-14 of `auto_edit/pipeline.py`:

```python
STAGE_SEQUENCES = {
    "short":    ["extract", "plan", "review", "execute", "caption",
                 "evaluate", "metadata", "thumbnail", "done"],
    "long":     ["extract", "plan", "review", "execute", "overlay",
                 "evaluate", "metadata", "thumbnail", "done"],
    "narrated": ["parse-script", "extract-vo", "align-blocks", "analyze-clips",
                 "match", "review", "assemble", "caption", "metadata",
                 "thumbnail", "done"],
}

# Stages that loop back when the evaluator rejects (only types with evaluate)
LOOPBACK_STAGES = {"plan", "review", "execute", "overlay", "caption", "evaluate"}


def stage_sequence(video_type: str) -> list[str]:
    if video_type not in STAGE_SEQUENCES:
        raise ValueError(f"Unknown video_type: {video_type}")
    return STAGE_SEQUENCES[video_type]
```

- [ ] **Step 4: Update init() to use the sequence**

In `init()`, replace the `stages = {}` loop with:

```python
    seq = stage_sequence(video_type)
    stages = {s: {"status": "pending"} for s in seq if s != "done"}
```

The `pipeline` dict's `"current_stage"` becomes `seq[0]`:

```python
        "current_stage": seq[0],
```

- [ ] **Step 5: Update set_stage_status() to advance within the type's sequence**

In `set_stage_status()`, replace the advance block:

```python
    if status == "complete":
        pipeline["stages"][stage]["completed_at"] = _now()
        seq = stage_sequence(pipeline["type"])
        current_idx = seq.index(stage)
        for next_stage in seq[current_idx + 1:]:
            if next_stage == "done":
                pipeline["current_stage"] = "done"
                break
            if pipeline["stages"].get(next_stage, {}).get("status") != "skip":
                pipeline["current_stage"] = next_stage
                break
```

- [ ] **Step 6: Update loop_back() and set_stage()**

In `loop_back()` change the reset loop to use `LOOPBACK_STAGES` intersected with the type's stages (narrated has no evaluate, so loop_back is never reached for it, but keep it safe):

```python
    for stage in LOOPBACK_STAGES:
        if stage in pipeline["stages"] and pipeline["stages"][stage].get("status") != "skip":
            pipeline["stages"][stage] = {"status": "pending"}
```

In `set_stage()` replace `if stage not in STAGES` with:

```python
    if stage not in stage_sequence(pipeline["type"]):
        raise ValueError(f"Unknown stage '{stage}' for type '{pipeline['type']}'")
```

- [ ] **Step 7: Run tests, verify pass + no regression**

Run: `.venv/bin/python -m pytest tests/test_pipeline_sequences.py tests/test_pipeline.py -v`
Expected: PASS (existing `test_pipeline.py` still green).

- [ ] **Step 8: Commit**

```bash
git add auto_edit/pipeline.py tests/test_pipeline_sequences.py
git commit -m "refactor: per-type stage sequences in pipeline state machine"
```

### Task 2: Extend init() with voice_path / clips_dir for narrated

**Files:**
- Modify: `auto_edit/pipeline.py` `init()`
- Test: `tests/test_pipeline_sequences.py`

- [ ] **Step 1: Add failing test**

```python
def test_init_stores_narrated_inputs(tmp_path):
    p = pipeline.init(tmp_path, Path("/tmp/v.mp4"), "narrated", "ctx",
                      voice_path=Path("/tmp/vo.mp3"),
                      clips_dir=Path("/tmp/brolls"))
    assert p["voice_path"].endswith("vo.mp3")
    assert p["clips_dir"].endswith("brolls")
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_pipeline_sequences.py::test_init_stores_narrated_inputs -v`
Expected: FAIL — unexpected keyword arg.

- [ ] **Step 3: Add params to init()**

Add to `init()` signature: `voice_path: Path | None = None, clips_dir: Path | None = None`. After building the `pipeline` dict add:

```python
    if voice_path is not None:
        pipeline["voice_path"] = str(voice_path.resolve())
    if clips_dir is not None:
        pipeline["clips_dir"] = str(clips_dir.resolve())
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_pipeline_sequences.py -v`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add auto_edit/pipeline.py tests/test_pipeline_sequences.py
git commit -m "feat: store voice_path/clips_dir in pipeline for narrated mode"
```

---

## Phase 1: extract-vo (transcribe the voice)

### Task 3: Let extract.py transcribe an explicit voice file

**Files:**
- Modify: `tools/extract.py` `extract()` (around line 45)
- Test: manual (Whisper not unit-tested in repo)

- [ ] **Step 1: Read `extract()` to find where it picks the media path**

Run: `sed -n '45,96p' tools/extract.py`
Confirm it builds the audio from `pipeline["video_path"]`.

- [ ] **Step 2: Implement voice_path preference**

In `extract()`, where it resolves the source media, prefer `voice_path` when present:

```python
    pipeline = _load_pipeline(workspace)
    source = Path(pipeline.get("voice_path") or pipeline["video_path"])
```

Use `source` everywhere `video_path` was used for audio extraction/transcription. (Energy map is harmless on the voice file.)

- [ ] **Step 3: Manual smoke (deferred to Phase 8 e2e)**

No unit test; verified in the end-to-end smoke (Task 16). Mark done after Step 2.

- [ ] **Step 4: Commit**

```bash
git add tools/extract.py
git commit -m "feat: extract stage transcribes voice_path when set (narrated)"
```

---

## Phase 2: parse-script (roteiro → blocks)

### Task 4: Agent prompt for parse-script

**Files:**
- Create: `agents/script_parser.md`

- [ ] **Step 1: Write the prompt file**

```markdown
# Script Parser

You convert a freeform narration script (roteiro, usually Portuguese) into
structured blocks. The script alternates between visual directions and the
spoken narration, often with rough timestamps like `[0:00 - 0:08]`.

For EACH block, extract:
- `id`: 1-based integer, in script order
- `narration`: the EXACT spoken text (the "Áudio:" line). Strip surrounding
  quotes. Keep wording verbatim — it will be matched against a transcription.
- `visual`: the visual direction (the "Visual:" line), describing what should
  be on screen.
- `script_hint`: `[start_seconds, end_seconds]` parsed from the `[m:ss - m:ss]`
  marker if present, else `null`.

Output ONLY valid JSON, no prose, no code fences:

{
  "blocks": [
    {"id": 1, "narration": "...", "visual": "...", "script_hint": [0.0, 8.0]}
  ]
}

If a block has no narration text, skip it.
```

- [ ] **Step 2: Commit**

```bash
git add agents/script_parser.md
git commit -m "feat: add script_parser agent prompt"
```

### Task 5: build_prompt branch + script_parser tool wrapper

**Files:**
- Modify: `auto_edit/runner.py` `build_prompt()` (after the `metadata` branch ~line 170)
- Create: `tools/script_parser.py`

- [ ] **Step 1: Add build_prompt branch**

In `build_prompt()`, before the final return, add:

```python
    elif stage == "parse-script":
        base = prompt_file.read_text()
        roteiro = (workspace / "script_source.txt").read_text()
        return f"{base}\n\n## Roteiro\n\n{roteiro}\n"
```

- [ ] **Step 2: Create the tool wrapper (validates agent JSON output)**

`tools/script_parser.py` is invoked by the `run_agent` flow indirectly — but parse-script is an AGENT stage (see ralph Task 13), so no Python tool is strictly required. Skip creating `tools/script_parser.py`. (This step intentionally creates nothing; parse-script is pure agent + `validate_and_save_llm_output`.)

- [ ] **Step 3: Commit**

```bash
git add auto_edit/runner.py
git commit -m "feat: build_prompt support for parse-script stage"
```

---

## Phase 3: align-blocks (voice timing per block)

### Task 6: Block aligner pure logic + tests

**Files:**
- Create: `tools/block_aligner.py`
- Test: `tests/test_block_aligner.py`

- [ ] **Step 1: Write failing tests**

```python
# tests/test_block_aligner.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.block_aligner import _normalize, _align_blocks


def test_normalize_strips_punct_and_case():
    assert _normalize("A Tower, Bridge!") == "a tower bridge"


def test_align_exact_phrases():
    words = [
        {"word": "a", "start": 0.0, "end": 0.2},
        {"word": "ponte", "start": 0.2, "end": 0.6},
        {"word": "abriu", "start": 0.6, "end": 1.0},
        {"word": "ele", "start": 2.0, "end": 2.2},
        {"word": "pulou", "start": 2.2, "end": 2.6},
    ]
    blocks = [
        {"id": 1, "narration": "A ponte abriu"},
        {"id": 2, "narration": "Ele pulou"},
    ]
    out = _align_blocks(words, blocks, vo_duration=2.6)
    assert out[0]["vo_start"] == 0.0
    assert abs(out[0]["vo_end"] - 1.0) < 0.01
    assert abs(out[1]["vo_start"] - 2.0) < 0.01
    assert abs(out[1]["vo_end"] - 2.6) < 0.01


def test_align_tolerates_small_variation():
    # narration says "muito maneiro" but transcription has "muito maneira"
    words = [
        {"word": "ficou", "start": 0.0, "end": 0.4},
        {"word": "muito", "start": 0.4, "end": 0.8},
        {"word": "maneira", "start": 0.8, "end": 1.2},
    ]
    blocks = [{"id": 1, "narration": "ficou muito maneiro"}]
    out = _align_blocks(words, blocks, vo_duration=1.2)
    assert out[0]["vo_start"] == 0.0
    assert abs(out[0]["vo_end"] - 1.2) < 0.01


def test_blocks_are_contiguous_no_gap():
    words = [{"word": f"w{i}", "start": i * 1.0, "end": i * 1.0 + 0.5} for i in range(6)]
    blocks = [
        {"id": 1, "narration": "w0 w1 w2"},
        {"id": 2, "narration": "w3 w4 w5"},
    ]
    out = _align_blocks(words, blocks, vo_duration=5.5)
    # block 2 starts exactly where block 1 ended (no black gap downstream)
    assert out[1]["vo_start"] == out[0]["vo_end"]
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_block_aligner.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement block_aligner.py**

```python
"""
ALIGN-BLOCKS stage — narrated mode.
Maps each script block's narration text onto the recorded-voice transcription
to recover the real start/end of every block in the voice timeline.

Usage: python tools/block_aligner.py <workspace_dir>
"""
from __future__ import annotations

import json
import re
import sys
from difflib import SequenceMatcher
from pathlib import Path


def _normalize(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s]", " ", text, flags=re.UNICODE)
    return re.sub(r"\s+", " ", text).strip()


def _align_blocks(words: list[dict], blocks: list[dict], vo_duration: float) -> list[dict]:
    """Greedy forward alignment: walk the word stream once, assigning a
    contiguous run of words to each block by best fuzzy match of its narration.
    Blocks are contiguous (each starts where the previous ended) so the
    assembled B-roll never leaves a gap."""
    norm_words = [_normalize(w["word"]) for w in words]
    out: list[dict] = []
    cursor = 0  # index into words
    n = len(words)

    for bi, block in enumerate(blocks):
        target = _normalize(block["narration"]).split()
        if not target or cursor >= n:
            start = words[cursor]["start"] if cursor < n else vo_duration
            out.append({"id": block["id"], "vo_start": start, "vo_end": start})
            continue

        # find the best-matching window starting at/after cursor
        target_len = len(target)
        best_end = cursor + target_len  # default span = word count of narration
        best_end = min(best_end, n)

        # refine end by maximizing similarity over a small range around target_len
        best_score = -1.0
        lo = cursor + max(1, target_len - 2)
        hi = min(n, cursor + target_len + 3)
        for end in range(lo, hi + 1):
            window = " ".join(norm_words[cursor:end])
            score = SequenceMatcher(None, window, " ".join(target)).ratio()
            if score > best_score:
                best_score = score
                best_end = end

        vo_start = words[cursor]["start"]
        vo_end = words[best_end - 1]["end"] if best_end > cursor else vo_start
        out.append({"id": block["id"], "vo_start": round(vo_start, 3),
                    "vo_end": round(vo_end, 3)})
        cursor = best_end

    # make contiguous: each block ends where the next begins; last ends at vo_duration
    for i in range(len(out) - 1):
        out[i]["vo_end"] = out[i + 1]["vo_start"]
    if out:
        out[-1]["vo_end"] = round(vo_duration, 3)
    return out


def align(workspace: Path) -> None:
    transcription = json.loads((workspace / "transcription.json").read_text())
    script = json.loads((workspace / "script.json").read_text())
    words = transcription.get("words", [])
    vo_duration = float(transcription.get("duration", words[-1]["end"] if words else 0.0))
    blocks = _align_blocks(words, script.get("blocks", []), vo_duration)
    (workspace / "vo_alignment.json").write_text(
        json.dumps({"vo_duration": vo_duration, "blocks": blocks},
                   indent=2, ensure_ascii=False), encoding="utf-8")
    print(f"[align-blocks] Aligned {len(blocks)} blocks over {vo_duration:.1f}s of voice")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/block_aligner.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    align(Path(sys.argv[1]))
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_block_aligner.py -v`
Expected: PASS (4 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/block_aligner.py tests/test_block_aligner.py
git commit -m "feat: align-blocks maps script blocks onto voice timeline"
```

---

## Phase 4: analyze-clips (vision)

### Task 7: Frame extraction + clip duration (testable helpers)

**Files:**
- Create: `tools/clip_analyzer.py`
- Test: `tests/test_clip_analyzer.py`

- [ ] **Step 1: Write failing tests for the pure helpers**

```python
# tests/test_clip_analyzer.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.clip_analyzer import _frame_timestamps, _is_video


def test_frame_timestamps_spreads_across_duration():
    ts = _frame_timestamps(10.0, n=5)
    assert len(ts) == 5
    assert ts[0] > 0 and ts[-1] < 10.0
    assert ts == sorted(ts)


def test_frame_timestamps_short_clip():
    ts = _frame_timestamps(1.0, n=5)
    assert all(0 < t < 1.0 for t in ts)


def test_is_video_by_extension():
    assert _is_video(Path("a.mp4"))
    assert _is_video(Path("a.MOV"))
    assert not _is_video(Path("a.txt"))
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_clip_analyzer.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement clip_analyzer.py**

```python
"""
ANALYZE-CLIPS stage — narrated mode.
Samples frames from each B-roll clip and asks a vision model to describe its
content. Result cached in clip_index.json (skips already-indexed clips).

Usage: python tools/clip_analyzer.py <workspace_dir>
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

VIDEO_EXTS = {".mp4", ".mov", ".mkv", ".avi", ".webm", ".m4v"}
FRAMES_PER_CLIP = 4


def _is_video(path: Path) -> bool:
    return path.suffix.lower() in VIDEO_EXTS


def _frame_timestamps(duration: float, n: int = FRAMES_PER_CLIP) -> list[float]:
    """Evenly spaced sample points strictly inside (0, duration)."""
    if duration <= 0:
        return [0.0]
    step = duration / (n + 1)
    return [round(step * (i + 1), 3) for i in range(n)]


def _get_duration(path: Path) -> float:
    out = subprocess.run(
        ["ffprobe", "-v", "error", "-show_entries", "format=duration",
         "-of", "default=noprint_wrappers=1:nokey=1", str(path)],
        capture_output=True, text=True, check=True)
    return float(out.stdout.strip())


def _extract_frame(video: Path, ts: float, out_png: Path) -> None:
    subprocess.run(
        ["ffmpeg", "-y", "-ss", f"{ts:.3f}", "-i", str(video),
         "-frames:v", "1", "-q:v", "3", str(out_png)],
        capture_output=True, check=True)


def _describe_with_gemini(frames: list[Path], context: str) -> dict:
    """Returns {'desc': str, 'tags': [str]} using Gemini Vision."""
    import google.generativeai as genai  # imported lazily
    genai.configure(api_key=os.environ["GEMINI_API_KEY"])
    model = genai.GenerativeModel("gemini-1.5-flash")
    imgs = [{"mime_type": "image/png", "data": p.read_bytes()} for p in frames]
    prompt = (
        f"Estes são frames de UM clip de B-roll. Contexto do vídeo: {context}. "
        "Descreva em uma frase curta o que aparece, e liste 3-6 tags. "
        'Responda só JSON: {"desc": "...", "tags": ["..."]}'
    )
    resp = model.generate_content([prompt, *imgs])
    text = resp.text.strip().removeprefix("```json").removeprefix("```").removesuffix("```").strip()
    return json.loads(text)


def analyze(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    clips_dir = Path(pipeline["clips_dir"])
    context = pipeline.get("context", "")
    index_path = workspace / "clip_index.json"
    index = json.loads(index_path.read_text()) if index_path.exists() else {}

    clips = sorted(p for p in clips_dir.iterdir() if _is_video(p))
    for clip in clips:
        if clip.name in index:
            continue
        duration = _get_duration(clip)
        with tempfile.TemporaryDirectory() as td:
            frames = []
            for i, ts in enumerate(_frame_timestamps(duration)):
                fp = Path(td) / f"f{i}.png"
                _extract_frame(clip, ts, fp)
                frames.append(fp)
            described = _describe_with_gemini(frames, context)
        index[clip.name] = {"duration": round(duration, 3), **described}
        print(f"[analyze-clips] {clip.name}: {described['desc']}")
        index_path.write_text(json.dumps(index, indent=2, ensure_ascii=False),
                              encoding="utf-8")
    print(f"[analyze-clips] Indexed {len(index)} clips")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/clip_analyzer.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    analyze(Path(sys.argv[1]))
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_clip_analyzer.py -v`
Expected: PASS (3 tests).

- [ ] **Step 5: Add `google-generativeai` to deps**

Add `google-generativeai` to `pyproject.toml` dependencies (mirror how existing deps are listed) and install: `.venv/bin/pip install google-generativeai`.

- [ ] **Step 6: Commit**

```bash
git add tools/clip_analyzer.py tests/test_clip_analyzer.py pyproject.toml
git commit -m "feat: analyze-clips samples frames + Gemini vision description"
```

---

## Phase 5: match (clips ↔ blocks)

### Task 8: Matcher agent prompt

**Files:**
- Create: `agents/matcher.md`

- [ ] **Step 1: Write the prompt**

```markdown
# B-roll Matcher

You assign B-roll clips to narration blocks for a narrated video.

INPUT (provided below): a list of blocks (id, narration, visual description,
and `target_duration` in seconds = the time the block's voice occupies) and a
clip index (filename → {duration, desc, tags}).

For EACH block, pick a SEQUENCE of clips whose trimmed lengths sum to roughly
`target_duration` (within ~0.5s). Prefer 2+ short cuts per block for dynamism.
Match clips to the block's `visual` description using clip `desc`/`tags`.
Rules:
- Each clip entry has `in`/`out` (seconds within the source clip); `out - in`
  is that cut's screen time. `out` must not exceed the clip's `duration`.
- You MAY reuse a clip across blocks, but avoid the same clip back-to-back.
- If clips can't fill `target_duration`, get as close as possible; the
  assembler will stretch the last clip. Never leave a block with zero clips.

Output ONLY valid JSON, no prose, no code fences:

{
  "blocks": [
    {"id": 4, "vo_start": 30.1, "vo_end": 38.0, "clips": [
      {"file": "onibus.mp4", "in": 2.0, "out": 5.5},
      {"file": "ponte_abrindo.mp4", "in": 0.0, "out": 4.4}
    ]}
  ]
}
```

- [ ] **Step 2: Commit**

```bash
git add agents/matcher.md
git commit -m "feat: add matcher agent prompt"
```

### Task 9: build_prompt branch for match

**Files:**
- Modify: `auto_edit/runner.py` `build_prompt()`

- [ ] **Step 1: Add the branch**

After the `parse-script` branch add:

```python
    elif stage == "match":
        base = prompt_file.read_text()
        script = _read_json(workspace / "script.json")
        align = _read_json(workspace / "vo_alignment.json")
        clip_index = _read_json(workspace / "clip_index.json")
        align_by_id = {b["id"]: b for b in align["blocks"]}
        blocks = []
        for b in script["blocks"]:
            a = align_by_id.get(b["id"], {})
            dur = round(a.get("vo_end", 0) - a.get("vo_start", 0), 2)
            blocks.append({"id": b["id"], "visual": b["visual"],
                           "narration": b["narration"],
                           "vo_start": a.get("vo_start"), "vo_end": a.get("vo_end"),
                           "target_duration": dur})
        payload = {"blocks": blocks, "clip_index": clip_index}
        return f"{base}\n\n## Dados\n\n{_compact_json(payload)}\n"
```

- [ ] **Step 2: Run runner import sanity**

Run: `.venv/bin/python -c "import auto_edit.runner"`
Expected: no error.

- [ ] **Step 3: Commit**

```bash
git add auto_edit/runner.py
git commit -m "feat: build_prompt support for match stage"
```

---

## Phase 6: assemble (ffmpeg render)

### Task 10: Assembler filter builder + tests

**Files:**
- Create: `tools/assembler.py`
- Test: `tests/test_assembler.py`

- [ ] **Step 1: Write failing tests for the pure filter builder**

```python
# tests/test_assembler.py
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent))
from tools.assembler import _flatten_clips, _build_video_filter


def test_flatten_clips_preserves_order():
    clip_map = {"blocks": [
        {"id": 1, "vo_start": 0.0, "vo_end": 2.0, "clips": [
            {"file": "a.mp4", "in": 0.0, "out": 1.0},
            {"file": "b.mp4", "in": 1.0, "out": 2.0}]},
        {"id": 2, "vo_start": 2.0, "vo_end": 3.0, "clips": [
            {"file": "c.mp4", "in": 0.0, "out": 1.0}]},
    ]}
    flat = _flatten_clips(clip_map)
    assert [c["file"] for c in flat] == ["a.mp4", "b.mp4", "c.mp4"]


def test_build_video_filter_has_trim_and_concat():
    clips = [{"file": "a.mp4", "in": 0.0, "out": 1.0, "_idx": 0},
             {"file": "b.mp4", "in": 1.0, "out": 2.5, "_idx": 1}]
    filt = _build_video_filter(clips, reframe=(1080, 1920))
    assert filt.count("trim=") == 2
    assert "concat=n=2" in filt
    assert "scale=1080:1920" in filt
    assert "[outv]" in filt
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_assembler.py -v`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement assembler.py**

```python
"""
ASSEMBLE stage — narrated mode.
Reads clip_map.json + the voice file, concatenates the chosen B-roll cuts
(muted), lays the voice as the single audio track, reframes to target aspect,
and writes edited_video.mp4 with duration == voice duration.

Usage: python tools/assembler.py <workspace_dir>
"""
from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from executor import _get_video_codec, SHORT_TARGET  # reuse codec choice

LONG_TARGET = (1920, 1080)


def _flatten_clips(clip_map: dict) -> list[dict]:
    flat: list[dict] = []
    for block in clip_map.get("blocks", []):
        for c in block.get("clips", []):
            flat.append(dict(c))
    for i, c in enumerate(flat):
        c["_idx"] = i
    return flat


def _build_video_filter(clips: list[dict], reframe: tuple[int, int] | None) -> str:
    parts, concat_inputs = [], ""
    for c in clips:
        i = c["_idx"]
        parts.append(
            f"[{i}:v]trim=start={c['in']:.3f}:end={c['out']:.3f},"
            f"setpts=PTS-STARTPTS[v{i}]")
        concat_inputs += f"[v{i}]"
    n = len(clips)
    parts.append(f"{concat_inputs}concat=n={n}:v=1:a=0[catv]")
    if reframe:
        tw, th = reframe
        parts.append(
            f"[catv]crop=ih*{tw}/{th}:ih:(iw-ih*{tw}/{th})/2:0,"
            f"scale={tw}:{th}:flags=lanczos[outv]")
    else:
        parts.append("[catv]null[outv]")
    return ";".join(parts)


def assemble(workspace: Path) -> None:
    pipeline = json.loads((workspace / "pipeline.json").read_text())
    clip_map = json.loads((workspace / "clip_map.json").read_text())
    clips_dir = Path(pipeline["clips_dir"])
    voice = Path(pipeline["voice_path"])
    video_type = pipeline.get("type", "narrated")

    flat = _flatten_clips(clip_map)
    if not flat:
        raise RuntimeError("clip_map has no clips")

    reframe = SHORT_TARGET if pipeline.get("orientation", "short") != "long" else LONG_TARGET
    # narrated reuses --type to choose orientation: short→9:16, long→16:9
    reframe = SHORT_TARGET if video_type != "long" else LONG_TARGET

    inputs: list[str] = []
    for c in flat:
        inputs += ["-i", str(clips_dir / c["file"])]
    voice_idx = len(flat)
    inputs += ["-i", str(voice)]

    vfilter = _build_video_filter(flat, reframe)
    # voice: loudnorm + stereo (Apple-compatible), matches executor's audio path
    afilter = (f"[{voice_idx}:a]loudnorm=I=-16:TP=-1.5:LRA=11,"
               "aformat=sample_fmts=fltp:channel_layouts=stereo[outa]")
    filter_complex = f"{vfilter};{afilter}"

    codec, codec_flags = _get_video_codec()
    output = workspace / "edited_video.mp4"
    cmd = ["ffmpeg", "-y", *inputs,
           "-filter_complex", filter_complex,
           "-map", "[outv]", "-map", "[outa]",
           "-c:v", codec, *codec_flags,
           "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
           # end at the shorter of (video, voice): voice is the spine
           "-shortest",
           "-movflags", "+faststart", "-brand", "mp42", str(output)]
    print(f"[assemble] {len(flat)} cuts → {output.name} (reframe {reframe})")
    if subprocess.run(cmd).returncode != 0:
        raise RuntimeError("FFmpeg failed during assemble")
    print(f"[assemble] Done → {output}")


if __name__ == "__main__":
    if len(sys.argv) < 2:
        print("Usage: python tools/assembler.py <workspace_dir>", file=sys.stderr)
        sys.exit(1)
    assemble(Path(sys.argv[1]))
```

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_assembler.py -v`
Expected: PASS (3 tests).

> **Note on `-shortest` + coverage:** if total B-roll < voice, `-shortest` would cut the voice short. To honor "stretch last clip, never black gap", Task 11 adds last-clip padding so total video ≥ voice before this runs.

- [ ] **Step 5: Commit**

```bash
git add tools/assembler.py tests/test_assembler.py
git commit -m "feat: assembler builds B-roll track + voice + reframe"
```

### Task 11: Last-clip stretch so video covers the voice

**Files:**
- Modify: `tools/assembler.py`
- Test: `tests/test_assembler.py`

- [ ] **Step 1: Add failing test**

```python
from tools.assembler import _pad_to_cover


def test_pad_stretches_last_clip_when_short():
    flat = [{"file": "a.mp4", "in": 0.0, "out": 1.0, "_idx": 0},
            {"file": "b.mp4", "in": 0.0, "out": 1.0, "_idx": 1}]
    # voice is 3.0s, clips sum 2.0s → last clip must grow by 1.0s
    padded = _pad_to_cover(flat, vo_duration=3.0)
    assert padded[-1]["out"] - padded[-1]["in"] == 2.0  # 1.0 + 1.0 stretch


def test_pad_noop_when_already_covers():
    flat = [{"file": "a.mp4", "in": 0.0, "out": 2.0, "_idx": 0}]
    padded = _pad_to_cover(flat, vo_duration=1.5)
    assert padded[-1]["out"] == 2.0
```

- [ ] **Step 2: Run, verify fail**

Run: `.venv/bin/python -m pytest tests/test_assembler.py::test_pad_stretches_last_clip_when_short -v`
Expected: FAIL — `_pad_to_cover` missing.

- [ ] **Step 3: Implement _pad_to_cover and wire into assemble()**

Add to `assembler.py`:

```python
def _pad_to_cover(flat: list[dict], vo_duration: float) -> list[dict]:
    """Ensure the summed cut duration >= voice duration by extending the last
    cut's out point. Prevents -shortest from truncating the voice / leaving a
    black tail."""
    total = sum(c["out"] - c["in"] for c in flat)
    deficit = vo_duration - total
    if deficit > 0.01 and flat:
        flat[-1]["out"] = round(flat[-1]["out"] + deficit, 3)
    return flat
```

In `assemble()`, after `flat = _flatten_clips(clip_map)` and the empty check, add:

```python
    vo_duration = float(json.loads((workspace / "vo_alignment.json").read_text())["vo_duration"])
    flat = _pad_to_cover(flat, vo_duration)
```

(If a stretched `out` exceeds the source clip duration, ffmpeg's `trim` clamps to the last frame — an acceptable freeze, matching the spec's "hold last frame".)

- [ ] **Step 4: Run, verify pass**

Run: `.venv/bin/python -m pytest tests/test_assembler.py -v`
Expected: PASS (5 tests).

- [ ] **Step 5: Commit**

```bash
git add tools/assembler.py tests/test_assembler.py
git commit -m "feat: stretch last clip so assembled video covers the voice"
```

---

## Phase 7: Review gate command

### Task 12: `review-broll` CLI command

**Files:**
- Modify: `auto_edit/cli.py` (add command near other `@app.command()`s)

- [ ] **Step 1: Implement the command**

```python
@app.command(name="review-broll")
def review_broll(
    target: Path = typer.Argument(..., help="Workspace dir or the script/video name"),
) -> None:
    """Show the proposed B-roll clip map for a narrated video before assemble."""
    ws = _resolve_workspace(target)  # reuse existing workspace resolver
    clip_map = json.loads((ws / "clip_map.json").read_text())
    script = {b["id"]: b for b in json.loads((ws / "script.json").read_text())["blocks"]}
    for block in clip_map["blocks"]:
        b = script.get(block["id"], {})
        dur = block["vo_end"] - block["vo_start"]
        console.print(f"\n[bold]Bloco {block['id']}[/bold] "
                      f"[{block['vo_start']:.1f}→{block['vo_end']:.1f}s, {dur:.1f}s]")
        console.print(f"  [dim]{b.get('narration','')[:80]}[/dim]")
        for c in block["clips"]:
            cut = c["out"] - c["in"]
            console.print(f"  • {c['file']}  [{c['in']:.1f}→{c['out']:.1f}] ({cut:.1f}s)")
    console.print(
        f"\nEdite [cyan]{ws/'clip_map.json'}[/cyan] se quiser, depois:\n"
        f"  [green]auto-edit resume {target} --from assemble[/green]\n")
```

If `_resolve_workspace` does not exist, mirror the workspace-lookup used by `auto-edit status` (find the existing helper in `cli.py` and reuse it; if it is inline, extract it into `_resolve_workspace(target: Path) -> Path`).

- [ ] **Step 2: Sanity import + help**

Run: `.venv/bin/python -m auto_edit.cli review-broll --help`
Expected: shows the command help (no import error).

- [ ] **Step 3: Commit**

```bash
git add auto_edit/cli.py
git commit -m "feat: review-broll command shows clip map before assemble"
```

---

## Phase 8: ralph dispatch + narrate command + e2e

### Task 13: ralph.sh dispatch for narrated stages

**Files:**
- Modify: `ralph.sh` (add cases inside the `case "$STAGE" in` block, ~line 277)

- [ ] **Step 1: Add the new cases**

Insert these cases alongside the existing ones:

```bash
        parse-script)
            run_agent "parse-script" "$WORKSPACE/script.json" "$AGENTS_DIR/script_parser.md"
            ;;

        extract-vo)
            run_python_tool "extract-vo" "$TOOLS_DIR/extract.py"
            ;;

        align-blocks)
            run_python_tool "align-blocks" "$TOOLS_DIR/block_aligner.py"
            ;;

        analyze-clips)
            run_python_tool "analyze-clips" "$TOOLS_DIR/clip_analyzer.py"
            ;;

        match)
            run_agent "match" "$WORKSPACE/clip_map.json" "$AGENTS_DIR/matcher.md"
            ;;

        review)
            if [ "${AUTO_EDIT_AUTO_APPROVE:-}" = "1" ]; then
                log "Auto-approve set — skipping review gate."
                "$PYTHON" -m auto_edit.pipeline complete "$WORKSPACE" "review"
            else
                log "Review gate. Run: auto-edit review-broll $WORKSPACE"
                log "Then: auto-edit resume <name> --from assemble"
                "$PYTHON" -m auto_edit.pipeline running "$WORKSPACE" "review" 2>/dev/null || true
                break
            fi
            ;;

        assemble)
            run_python_tool "assemble" "$TOOLS_DIR/assembler.py"
            ;;
```

> Note: `extract-vo` reuses `extract.py` (which now prefers `voice_path`). The existing `extract)` case stays for short/long. The `review)` case is shared — but short/long never reach a `review` that pauses because their `review` runs the reviewer agent. Guard: the existing `review)` case currently runs `run_agent ... reviewer.md`. Make the dispatch type-aware:

Wrap the `review)` case to branch on type:

```bash
        review)
            VIDEO_TYPE=$("$PYTHON" -c "import json;print(json.load(open('$PIPELINE'))['type'])")
            if [ "$VIDEO_TYPE" = "narrated" ]; then
                if [ "${AUTO_EDIT_AUTO_APPROVE:-}" = "1" ]; then
                    "$PYTHON" -m auto_edit.pipeline complete "$WORKSPACE" "review"
                else
                    log "Review gate. Run: auto-edit review-broll $WORKSPACE ; then resume --from assemble"
                    "$PYTHON" -m auto_edit.pipeline running "$WORKSPACE" "review" 2>/dev/null || true
                    break
                fi
            else
                run_agent "review" "$WORKSPACE/reviewed_plan.json" "$AGENTS_DIR/reviewer.md"
            fi
            ;;
```

Remove the standalone `review)` block added above to avoid a duplicate case.

- [ ] **Step 2: Validate ralph syntax**

Run: `bash -n ralph.sh`
Expected: no output (valid).

- [ ] **Step 3: Confirm `auto_edit.pipeline` has a `complete` CLI verb**

Run: `grep -n "complete\|running\|def main\|sys.argv" auto_edit/pipeline.py | head`
If a `complete <ws> <stage>` verb does not exist, add a thin CLI handler that calls `set_stage_status(ws, stage, "complete")` (mirror the existing `running`/`failed` verbs already used by ralph).

- [ ] **Step 4: Commit**

```bash
git add ralph.sh auto_edit/pipeline.py
git commit -m "feat: ralph dispatch for narrated stages + review gate pause"
```

### Task 14: `narrate` CLI command

**Files:**
- Modify: `auto_edit/cli.py` (new command), `_run_pipeline` (accept voice/clips), workspace init

- [ ] **Step 1: Read `_run_pipeline` to learn its signature + how it calls pipeline.init**

Run: `grep -n "_run_pipeline\|pipeline.init\|def _run_pipeline\|script_source" auto_edit/cli.py`
Confirm where `pipeline.init(...)` is called and where the source video is copied into the workspace.

- [ ] **Step 2: Add voice_path/clips_dir passthrough to `_run_pipeline`**

Add params `voice_path: Optional[Path] = None, clips_dir: Optional[Path] = None, script_text: Optional[str] = None` to `_run_pipeline`. At the `pipeline.init(...)` call, pass `voice_path=voice_path, clips_dir=clips_dir`. After init, when `script_text` is set, write it for parse-script:

```python
    if script_text is not None:
        (workspace / "script_source.txt").write_text(script_text, encoding="utf-8")
```

For narrated, there is no source "video" — pass the voice file as `video_path` placeholder so finalize/output naming still works, and rely on `voice_path` for transcription.

- [ ] **Step 3: Implement the `narrate` command**

```python
@app.command()
def narrate(
    script: Path = typer.Argument(..., help="Path to the narration script (text/markdown)"),
    voice: Path = typer.Option(..., "--voice", help="Recorded voiceover audio file"),
    clips: Path = typer.Option(..., "--clips", help="Folder of B-roll clips"),
    video_type: str = typer.Option("short", "--type", "-t", help="short (9:16) or long (16:9)"),
    context: str = typer.Option("", "--context", "-c", help="What the video is about"),
    whisper_model: str = typer.Option("small", "--whisper-model", "-m"),
    language: str = typer.Option("pt", "--language", "-l"),
    resume_from: Optional[str] = typer.Option(None, "--from"),
    cli: Optional[str] = typer.Option(None, "--cli"),
    cli_fallback: Optional[str] = typer.Option(None, "--cli-fallback"),
) -> None:
    """Assemble a narrated video from a script + voiceover + B-roll folder."""
    if video_type not in ("short", "long"):
        console.print("[red]--type must be 'short' or 'long'[/red]")
        raise typer.Exit(1)
    for p, name in [(script, "script"), (voice, "voice"), (clips, "clips")]:
        if not p.exists():
            console.print(f"[red]{name} not found:[/red] {p}")
            raise typer.Exit(1)
    if whisper_model not in VALID_MODELS:
        console.print(f"[red]Invalid model.[/red] Choose from: {', '.join(VALID_MODELS)}")
        raise typer.Exit(1)
    _run_pipeline(
        voice,                      # video_path placeholder = voice file
        "narrated",
        context,
        whisper_model,
        max_iterations=1,
        resume_from=resume_from,
        cli=cli,
        cli_fallback=cli_fallback,
        language=language,
        voice_path=voice,
        clips_dir=clips,
        script_text=script.read_text(encoding="utf-8"),
    )
```

(Match `_run_pipeline`'s real positional/keyword shape from Step 1; adjust arg passing accordingly.)

- [ ] **Step 4: Sanity check the command loads**

Run: `.venv/bin/python -m auto_edit.cli narrate --help`
Expected: help text with `--voice`, `--clips`, `--type`.

- [ ] **Step 5: Commit**

```bash
git add auto_edit/cli.py
git commit -m "feat: auto-edit narrate command for narrated mode"
```

### Task 15: Full test + lint pass

- [ ] **Step 1: Run the focused suite**

Run: `.venv/bin/python -m pytest tests/test_pipeline_sequences.py tests/test_block_aligner.py tests/test_clip_analyzer.py tests/test_assembler.py tests/test_captioner.py tests/test_executor.py tests/test_pipeline.py -v`
Expected: all PASS.

- [ ] **Step 2: Lint**

Run: `.venv/bin/ruff check auto_edit/ tools/ tests/ --select E,F,W --ignore E501`
Expected: All checks passed.

- [ ] **Step 3: ralph syntax**

Run: `bash -n ralph.sh`
Expected: valid.

- [ ] **Step 4: Commit any lint fixes**

```bash
git add -A && git commit -m "chore: lint + test pass for narrated mode" || echo "nothing to commit"
```

### Task 16: End-to-end smoke (manual, using Nix ffmpeg)

**Files:** none (manual verification)

- [ ] **Step 1: Prepare a tiny fixture**

Use the Tower Bridge script (paste into `roteiro.txt`), a short recorded `vo.m4a`, and a folder with 3-4 short clips.

- [ ] **Step 2: Run through the gate (Nix ffmpeg on PATH for libass burn)**

```bash
export PATH="/nix/store/f9m6rhxvb821jcyhjlqg2x953nxc91aa-ffmpeg-full-8.0.1-bin/bin:$PATH"
auto-edit narrate roteiro.txt --voice vo.m4a --clips ./brolls/ --type short -c "Tower Bridge"
# pipeline pauses at review:
auto-edit review-broll roteiro
# (optionally edit clip_map.json)
auto-edit resume roteiro --from assemble
```

- [ ] **Step 3: Verify outputs**

Run (Nix ffprobe):
```bash
WS=$(ls -d workspace/roteiro* | head -1)
ffprobe -v error -show_entries format=duration -of default=nk=1:nw=1 "$WS/captioned_video.mp4"
tail -1 "$WS/captions.ass"
```
Expected: captioned duration ≈ voice duration; last caption near the end (coverage guard from `captioner.py` quiet = good).

- [ ] **Step 4: Open PR**

```bash
git push -u origin feat/narrated-mode
gh pr create --title "feat: narrated mode (script + B-roll + voice)" \
  --body "Implements docs/superpowers/specs/2026-06-15-narrated-mode-design.md"
```

---

## Self-Review Notes

- **Spec coverage:** parse-script (T4-5), extract-vo (T3), align-blocks (T6), analyze-clips (T7), match (T8-9), review gate (T12, T13), assemble + cover-stretch (T10-11), reuse caption/metadata/thumbnail (sequence in T1, e2e T16), per-type sequences (T1), voice/clips storage (T2), CLI (T14). All spec sections mapped.
- **Out of scope honored:** no music, no TTS, no evaluate loop for narrated (max_iterations=1, LOOPBACK guarded).
- **Type consistency:** `_flatten_clips`/`_build_video_filter`/`_pad_to_cover` (assembler), `_align_blocks`/`_normalize` (aligner), `_frame_timestamps`/`_is_video` (analyzer), `stage_sequence`/`STAGE_SEQUENCES` (pipeline) — names used identically across tasks.
- **Known integration unknowns flagged inline:** `_resolve_workspace` (T12), `_run_pipeline` real signature (T14), `pipeline complete` verb (T13) — each step says to confirm against the real code and mirror existing patterns rather than assume.
