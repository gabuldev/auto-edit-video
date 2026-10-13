"""The desktop app starts the engine with `python -m auto_edit.cli serve`:
the module has to run the CLI, not just import it and exit."""
import subprocess
import sys


def test_python_m_auto_edit_cli_runs_the_cli():
    res = subprocess.run([sys.executable, "-m", "auto_edit.cli", "--help"], capture_output=True, text=True, timeout=60)
    assert res.returncode == 0
    assert "serve" in res.stdout
