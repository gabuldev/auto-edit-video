"""Importing the YouTube Studio CTR export (auto_edit/insights/studio_csv.py)."""
import sys
from pathlib import Path

import pytest
from typer.testing import CliRunner

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights import store, studio_csv  # noqa: E402
from auto_edit.insights.cli import insights_app  # noqa: E402

EN = """Content,Video title,Video publish time,Impressions,Impressions click-through rate (%),Views,Average percentage viewed (%),Watch time (hours)
Total,,,"12,345",4.8,900,,
dQw4w9WgXcQ,Montei um AMS caseiro,"Oct 10, 2026",8000,5.25,500,41.2,30.5
abcdefghijk,Outro vídeo,"Oct 1, 2026",4345,3.9,400,35.0,10
"""

PT = """﻿Conteúdo,Título do vídeo,Horário de publicação do vídeo,Impressões,Taxa de cliques de impressões (%),Visualizações
Total,,,12345,"4,8",900
dQw4w9WgXcQ,Montei um AMS caseiro,10 de out. de 2026,8000,"5,25",500
"""


class TestParse:
    def test_english_export(self):
        rows = studio_csv.parse(EN)
        assert [r.video_id for r in rows] == ["dQw4w9WgXcQ", "abcdefghijk"]  # Total skipped
        r = rows[0]
        assert r.title == "Montei um AMS caseiro"
        assert r.impressions == 8000 and r.ctr == pytest.approx(5.25)
        assert r.views == 500 and r.avg_view_pct == pytest.approx(41.2)
        assert r.watch_time_min == pytest.approx(30.5 * 60)

    def test_portuguese_export_with_decimal_comma(self):
        rows = studio_csv.parse(PT)
        assert len(rows) == 1 and rows[0].ctr == pytest.approx(5.25) and rows[0].impressions == 8000

    @pytest.mark.parametrize("raw,value", [
        ("4.56", 4.56), ("4,56", 4.56), ("1,234", 1234.0), ("1.234,5", 1234.5), ("1,234.5", 1234.5),
        ("12 %", 12.0), ("", None), ("—", None),
    ])
    def test_numbers(self, raw, value):
        assert studio_csv._number(raw) == (pytest.approx(value) if value is not None else None)

    def test_without_ctr_column_says_what_to_export(self):
        with pytest.raises(studio_csv.StudioCsvError, match="CTR"):
            studio_csv.parse("Content,Views\ndQw4w9WgXcQ,5\n")

    def test_not_a_studio_export(self):
        with pytest.raises(studio_csv.StudioCsvError):
            studio_csv.parse("a,b\n1,2\n")
        with pytest.raises(studio_csv.StudioCsvError):
            studio_csv.parse("")


class TestImport:
    def _conn(self, tmp_path):
        return store.connect(tmp_path / "insights.db")

    def test_ctr_joins_the_api_metrics_without_overwriting_them(self, tmp_path):
        conn = self._conn(tmp_path)
        store.upsert_video(conn, "youtube", "dQw4w9WgXcQ", title="AMS", url="u",
                           thumbnail_url="t.jpg", published_at="2026-10-10", duration_sec=600)
        store.add_snapshot(conn, "youtube", "dQw4w9WgXcQ",
                           {"views": 1500, "avg_view_pct": 45.0, "likes": 30, "fetched_at": "2026-10-20T00:00:00"})
        res = studio_csv.import_rows(conn, studio_csv.parse(EN), source="t.csv")
        assert res.rows == 2 and res.new_videos == 1
        latest = {r["platform_video_id"]: r for r in store.latest_snapshots(conn, "youtube")}
        ams = latest["dQw4w9WgXcQ"]
        assert ams["ctr"] == pytest.approx(5.25) and ams["reach"] == 8000
        assert ams["views"] == 1500 and ams["avg_view_pct"] == 45.0 and ams["likes"] == 30  # the API's numbers
        assert ams["thumbnail_url"] == "t.jpg"  # the known video wasn't rewritten
        assert ams["raw"]["source"] == "studio_csv"
        other = latest["abcdefghijk"]
        assert other["ctr"] == pytest.approx(3.9) and other["views"] == 400  # new: the CSV fills it

    def test_rows_without_ctr_are_skipped(self, tmp_path):
        conn = self._conn(tmp_path)
        rows = studio_csv.parse("Content,Impressions click-through rate (%)\ndQw4w9WgXcQ,\n")
        res = studio_csv.import_rows(conn, rows)
        assert res.rows == 0 and res.skipped == 1
        assert store.list_videos(conn) == []


class TestCli:
    def test_import_ctr(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        f = tmp_path / "Table data.csv"
        f.write_text(EN, encoding="utf-8")
        result = CliRunner().invoke(insights_app, ["import-ctr", str(f)])
        assert result.exit_code == 0, result.output
        assert "2 vídeos" in result.output
        report = CliRunner().invoke(insights_app, ["report"])
        assert "5.25" in report.output

    def test_bad_file_fails_cleanly(self, tmp_path, monkeypatch):
        monkeypatch.setenv("AUTO_EDIT_HOME", str(tmp_path))
        f = tmp_path / "x.csv"
        f.write_text("a,b\n", encoding="utf-8")
        assert CliRunner().invoke(insights_app, ["import-ctr", str(f)]).exit_code == 1
        assert CliRunner().invoke(insights_app, ["import-ctr", str(tmp_path / "nope.csv")]).exit_code == 1
