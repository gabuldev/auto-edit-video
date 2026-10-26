"""What ralph does around an agent call: says it is still waiting, and refuses
an answer that only copied the prompt's example."""
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest

from auto_edit import runner

REPO = Path(__file__).parent.parent
PLANNER_LONG = REPO / "agents" / "planner_long.md"

# What qwen2.5:7b answered for a 10-min long: the schema's example, verbatim.
COPIED_PLAN = {
    "target_rationale": "45min bruto, ~18min de conteúdo único: 3 blocos repetem o mesmo argumento e 8min são troubleshooting de setup",
    "dropped_blocks": [],
    "cuts": [{"start": 0.0, "end": 2.5, "reason": "silence — no speech detected", "type": "silence"}],
    "kept_segments": [{"start": 2.5, "end": 45.2, "summary": "intro apresentando o objetivo do vídeo"}],
}
OWN_PLAN = {
    "target_rationale": "10min bruto, ~7min: sai o bloco que repete as 100k views do Threads",
    "dropped_blocks": [],
    # Reusing the prompt's ready-made reason labels is fine.
    "cuts": [{"start": 0.0, "end": 2.5, "reason": "silence — no speech detected", "type": "silence"},
             {"start": 45.2, "end": 47.8, "reason": "false start — speaker repeated the sentence", "type": "content"}],
    "kept_segments": [{"start": 2.5, "end": 45.2, "summary": "abre mostrando a interface nova do app"}],
}


def _validate(tmp_path, obj, template=PLANNER_LONG):
    raw = tmp_path / "raw.txt"
    raw.write_text(json.dumps(obj, ensure_ascii=False), encoding="utf-8")
    out = tmp_path / "out.json"
    return runner.validate_and_save_llm_output(raw, out, template), out


def test_an_answer_that_copied_the_example_is_refused(tmp_path, capsys):
    ok, out = _validate(tmp_path, COPIED_PLAN)
    assert not ok and not out.exists()
    assert "copiou o exemplo" in capsys.readouterr().err


def test_an_own_answer_passes_even_reusing_reason_labels(tmp_path):
    ok, out = _validate(tmp_path, OWN_PLAN)
    assert ok and json.loads(out.read_text(encoding="utf-8")) == OWN_PLAN


def test_one_match_is_not_a_copy():
    # metadata.md quotes a real title of the channel; the same video may get it
    one = {**OWN_PLAN, "target_rationale": COPIED_PLAN["target_rationale"]}
    assert len(runner.copied_example(one, PLANNER_LONG.read_text(encoding="utf-8"))) == 1


def test_without_a_template_nothing_is_checked(tmp_path):
    ok, _ = _validate(tmp_path, COPIED_PLAN, template=None)
    assert ok


@pytest.mark.skipif(sys.platform == "win32" or not shutil.which("bash"), reason="ralph.sh under bash")
def test_ralph_says_it_is_waiting_on_a_slow_agent(tmp_path):
    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    fake = bin_dir / "claude"
    fake.write_text('#!/bin/sh\nsleep 3\necho \'{"ok": true}\'\n', encoding="utf-8")
    fake.chmod(0o755)
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text("{}", encoding="utf-8")
    prompt = tmp_path / "p.md"
    prompt.write_text("responda ok", encoding="utf-8")
    env = {**os.environ, "PATH": f"{bin_dir}{os.pathsep}{os.environ['PATH']}", "AUTO_EDIT_LLM": "claude",
           "AUTO_EDIT_HEARTBEAT_SEC": "1", "PYTHON": sys.executable}
    env.pop("AUTO_EDIT_LLM_FALLBACK", None)
    out = subprocess.run(["bash", str(REPO / "ralph.sh"), "--agent", str(ws), "teste", str(ws / "out.json"), str(prompt)],
                         env=env, capture_output=True, text=True, timeout=30).stdout
    assert "teste: aguardando claude responder… 1s" in out
    assert json.loads((ws / "out.json").read_text(encoding="utf-8")) == {"ok": True}
