"""Tests for auto_edit/insights/connector.py."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

from auto_edit.insights import connector as cn


class TestMetricPoint:
    def test_as_store_dict_roundtrips_fields(self):
        p = cn.MetricPoint("v1", views=10, ctr=0.05, raw={"a": 1})
        d = p.as_store_dict()
        assert d["views"] == 10 and d["ctr"] == 0.05
        assert d["raw"] == {"a": 1}
        assert d["saves"] is None


class TestRegistry:
    def test_platforms_lists_youtube(self):
        assert "youtube" in cn.PLATFORMS

    def test_get_connector_unknown_raises(self):
        with pytest.raises(ValueError, match="youtube"):
            cn.get_connector("myspace")

    def test_get_connector_youtube(self):
        c = cn.get_connector("youtube")
        assert c.platform == "youtube"

    def test_detect_platform_from_youtube_url(self):
        assert cn.detect_platform("https://youtu.be/abc123") == "youtube"

    def test_detect_platform_unknown_none(self):
        assert cn.detect_platform("https://example.com/x") is None
