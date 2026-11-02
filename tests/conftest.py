"""Shared test setup."""
import pytest

from auto_edit import expression


@pytest.fixture(autouse=True)
def _no_expression_model(monkeypatch):
    """Tests never download MediaPipe's model: the optional expression score
    is off (as without the extra) unless a test turns it back on."""
    monkeypatch.setattr(expression, "_failed", True)
