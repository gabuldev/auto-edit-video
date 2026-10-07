"""The opening report: which lines of the first seconds are preamble, and
whether the promise of the video lands in time."""
import json
from pathlib import Path

import pytest

from auto_edit import opening, runner

# The opening of "AutoEdit agora tem interface gráfica" (published, 1:10 avg view).
REAL = {"segments": [
    {"start": 0.0, "end": 4.1, "text": "Fala galera, tem uma novidade para vocês"},
    {"start": 4.1, "end": 8.0, "text": "plataforma de edição de vídeo utilizando AI."},
    {"start": 8.0, "end": 14.0, "text": "Então bora lá falar dessa ferramenta"},
    {"start": 25.8, "end": 29.2, "text": "Obviamente tem algumas coisas importantes que a gente precisa falar aqui."},
    {"start": 36.9, "end": 43.3, "text": "Então para quem não me conhece sou engenheiro de software"},
    {"start": 53.2, "end": 55.3, "text": "Deixa só virar a câmera aqui."},
    {"start": 55.3, "end": 57.5, "text": "Olha isso daqui galera."},
]}


@pytest.mark.parametrize("text, kind", [
    ("Fala galera, tudo bem?", "saudação"),
    ("Pra quem não me conhece, eu sou o Gabul", "apresentação"),
    ("No vídeo de hoje eu vou mostrar", "anúncio do vídeo"),
    ("Então BORA LÁ", "bora lá"),
    ("deixa eu ajustar a câmera", "logística de gravação"),
    ("se inscreve no canal", "pedido de inscrição"),
    ("Olha isso daqui, a interface nova", None),
    ("A bateria durou 14 horas", None),
])
def test_preamble_kind(text, kind):
    assert opening.preamble_kind(text) == kind


def test_real_opening_is_too_slow():
    rep = opening.report(REAL, window=60)
    kinds = [ln["preamble"] for ln in rep["lines"]]
    assert kinds == ["saudação", None, "bora lá", "anúncio do vídeo", "apresentação", "logística de gravação", None]
    assert rep["preamble_until"] == 55.3
    assert rep["too_slow"] is True


def test_tight_opening_passes():
    tight = {"segments": [
        {"start": 0.0, "end": 1.5, "text": "Fala galera!"},
        {"start": 1.5, "end": 6.0, "text": "Olha essa interface nova editando vídeo sozinha."},
    ]}
    rep = opening.report(tight)
    assert rep["too_slow"] is False
    assert rep["preamble_seconds"] == 1.5


def test_window_cuts_off_later_lines():
    rep = opening.report(REAL, window=20)
    assert [ln["start"] for ln in rep["lines"]] == [0.0, 4.1, 8.0]


def test_format_report_marks_lines():
    text = opening.format_report(opening.report(REAL, window=60))
    assert "[0:53] Deixa só virar a câmera aqui.  ← preâmbulo (logística de gravação)" in text
    assert "Preâmbulo até 0:55" in text and "Passa do limite" in text
    assert opening.format_report(opening.report({"segments": []})) == "(nenhuma fala nos primeiros segundos)"


def _ws(tmp_path):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "pipeline.json").write_text(json.dumps({"type": "long", "context": "c", "stages": {}}))
    (ws / "transcription.json").write_text(json.dumps({"duration": 60, "segments": [
        {"start": 0.0, "end": 3.0, "text": "Fala galera, bora lá"},
        {"start": 3.0, "end": 20.0, "text": "para quem não me conhece eu sou dev"},
        {"start": 20.0, "end": 25.0, "text": "olha o resultado"},
    ], "words": []}))
    return ws


def test_dry_run_uses_the_planned_cut(tmp_path):
    ws = _ws(tmp_path)
    (ws / "reviewed_plan.json").write_text(json.dumps({"kept_segments": [{"start": 0, "end": 3}, {"start": 20, "end": 25}]}))
    rep = opening.for_workspace(ws)
    assert [ln["text"] for ln in rep["lines"]] == ["Fala galera, bora lá", "olha o resultado"]
    assert rep["too_slow"] is False


def test_rendered_edit_wins_over_the_plan(tmp_path):
    ws = _ws(tmp_path)
    (ws / "post_cut_transcription.json").write_text(json.dumps({"segments": [{"start": 0, "end": 2, "text": "olha"}]}))
    assert opening.for_workspace(ws)["lines"][0]["text"] == "olha"


def test_evaluate_prompt_carries_the_report(tmp_path):
    ws = _ws(tmp_path)
    (ws / "post_cut_transcription.json").write_text(json.dumps(REAL))
    prompt = runner.build_prompt("evaluate", ws, Path("agents/evaluator.md"))
    assert "## Abertura do vídeo editado" in prompt
    assert "← preâmbulo (apresentação)" in prompt


def test_invalid_plan_is_no_report(tmp_path):
    ws = _ws(tmp_path)
    (ws / "reviewed_plan.json").write_text("null")
    assert opening.for_workspace(ws) is None
