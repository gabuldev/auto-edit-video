"""Tests for auto_edit/workspace.py — naming logic with and without plan_id."""
from pathlib import Path

from auto_edit import workspace as ws


def test_get_workspace_default_uses_stem():
    p = ws.get_workspace(Path("/tmp/some_video.mp4"))
    assert p == Path("workspace") / "some_video"


def test_get_workspace_with_plan_id_namespaces():
    p = ws.get_workspace(Path("/tmp/some_video.mp4"), plan_id="2026-W19/S2")
    assert p == Path("workspace") / "2026-W19_S2_some_video"


def test_get_workspace_plan_id_with_month():
    p = ws.get_workspace(Path("/tmp/v.mp4"), plan_id="2026-06/L1")
    assert p == Path("workspace") / "2026-06_L1_v"
