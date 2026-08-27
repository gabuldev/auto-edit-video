"""Tests for auto_edit/probe.py — ffprobe JSON parsing."""
import json

import pytest

from auto_edit.probe import (
    ProbeError,
    parse_fps,
    parse_size,
    parse_streams,
    parse_timescale,
)

# Captured from a DJI clip that crashed `auto-edit merge`: the video stream
# carries side data, which the CSV writer renders as a trailing empty field
# (`3840x2160x`). Sibling clips from the same camera have no side_data_list.
DJI_WITH_SIDE_DATA = json.dumps({
    "programs": [],
    "stream_groups": [],
    "streams": [{"width": 3840, "height": 2160, "side_data_list": [{}]}],
})

DJI_PLAIN = json.dumps({
    "programs": [],
    "stream_groups": [],
    "streams": [{"width": 3840, "height": 2160}],
})


class TestParseSize:
    def test_side_data_does_not_break_parsing(self):
        assert parse_size(DJI_WITH_SIDE_DATA) == (3840, 2160)

    def test_matches_plain_stream(self):
        assert parse_size(DJI_PLAIN) == parse_size(DJI_WITH_SIDE_DATA)

    def test_portrait_size(self):
        payload = json.dumps({"streams": [{"width": 1080, "height": 1920}]})
        assert parse_size(payload) == (1080, 1920)

    def test_string_values_are_coerced(self):
        payload = json.dumps({"streams": [{"width": "1280", "height": "720"}]})
        assert parse_size(payload) == (1280, 720)

    def test_skips_stream_without_dimensions(self):
        payload = json.dumps({"streams": [{"index": 2}, {"width": 640, "height": 480}]})
        assert parse_size(payload) == (640, 480)

    def test_no_streams_raises(self):
        with pytest.raises(ProbeError):
            parse_size(json.dumps({"streams": []}))

    def test_garbage_payload_raises(self):
        with pytest.raises(ProbeError):
            parse_size("not json at all")


class TestParseFps:
    def test_reads_fraction(self):
        payload = json.dumps({"streams": [{"r_frame_rate": "30000/1001"}]})
        assert parse_fps(payload) == "30000/1001"

    def test_zero_rate_is_unknown(self):
        payload = json.dumps({"streams": [{"r_frame_rate": "0/0"}]})
        assert parse_fps(payload) is None

    def test_na_is_unknown(self):
        payload = json.dumps({"streams": [{"r_frame_rate": "N/A"}]})
        assert parse_fps(payload) is None

    def test_missing_is_unknown(self):
        assert parse_fps(json.dumps({"streams": [{"width": 100}]})) is None


class TestParseStreams:
    def test_empty_on_garbage(self):
        assert parse_streams("<html>nope</html>") == []

    def test_empty_on_missing_key(self):
        assert parse_streams(json.dumps({"format": {}})) == []

    def test_returns_all_streams(self):
        payload = json.dumps({"streams": [{"index": 0}, {"index": 1}]})
        assert len(parse_streams(payload)) == 2


class TestParseTimescale:
    def test_reads_time_base_denominator(self):
        payload = json.dumps({"streams": [{"time_base": "1/90000"}]})
        assert parse_timescale(payload) == 90000

    def test_thirty_thousand_timescale(self):
        payload = json.dumps({"streams": [{"time_base": "1/30000"}]})
        assert parse_timescale(payload) == 30000

    def test_missing_time_base_is_none(self):
        assert parse_timescale(json.dumps({"streams": [{"width": 1920}]})) is None

    def test_garbage_time_base_is_none(self):
        assert parse_timescale(json.dumps({"streams": [{"time_base": "N/A"}]})) is None

    def test_empty_payload_is_none(self):
        assert parse_timescale("") is None
