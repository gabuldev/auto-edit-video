"""`auto-edit status` curation summary (long-form dropped blocks)."""
from __future__ import annotations

import json

from auto_edit.cli import _print_curation_summary


def _write(ws, name, payload):
    ws.mkdir(exist_ok=True)
    (ws / name).write_text(json.dumps(payload), encoding="utf-8")


def test_prints_dropped_blocks(tmp_path, capsys):
    _write(
        tmp_path / "ws",
        "reviewed_plan.json",
        {
            "target_rationale": "45min bruto, 18min de conteudo unico",
            "estimated_final_duration": 1080,
            "dropped_blocks": [
                {"start": 610.0, "end": 1085.0, "topic": "troubleshooting", "reason": "sem payload"}
            ],
            "cuts": [],
            "kept_segments": [],
        },
    )
    _print_curation_summary(tmp_path / "ws")
    out = capsys.readouterr().out

    assert "Curadoria" in out
    assert "troubleshooting" in out
    assert "18.0min" in out


def test_falls_back_to_cut_plan(tmp_path, capsys):
    _write(
        tmp_path / "ws",
        "cut_plan.json",
        {"target_rationale": "video denso, mantem 40min", "dropped_blocks": []},
    )
    _print_curation_summary(tmp_path / "ws")

    assert "video denso" in capsys.readouterr().out


def test_silent_for_short_form_plan(tmp_path, capsys):
    _write(tmp_path / "ws", "reviewed_plan.json", {"cuts": [], "kept_segments": []})
    _print_curation_summary(tmp_path / "ws")

    assert capsys.readouterr().out == ""


def test_silent_without_workspace(tmp_path, capsys):
    _print_curation_summary(tmp_path / "missing")

    assert capsys.readouterr().out == ""


def test_silent_on_corrupt_plan(tmp_path, capsys):
    ws = tmp_path / "ws"
    ws.mkdir()
    (ws / "reviewed_plan.json").write_text("{not json", encoding="utf-8")
    _print_curation_summary(ws)

    assert capsys.readouterr().out == ""
