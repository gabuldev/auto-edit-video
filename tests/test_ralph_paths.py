r"""Guard against interpolating paths into Python source inside ralph.sh.

`$PIPELINE` and `$WORKSPACE` used to be pasted straight into Python string
literals. Any backslash in the path then became an escape sequence: on Windows
`workspace\bench_x` was read as `workspace<backspace>ench_x`, and `C:\Users`
blew up as an invalid \U escape — the pipeline could not read its own
pipeline.json. Paths must reach Python through argv instead.
"""
from pathlib import Path

RALPH = Path(__file__).parent.parent / "ralph.sh"

# The bug shape: a shell variable holding a path, quoted as a Python string.
FORBIDDEN = ("'$PIPELINE'", "'$WORKSPACE'", '"$PIPELINE"', '"$WORKSPACE"')


def test_no_shell_path_inside_a_python_literal():
    text = RALPH.read_text(encoding="utf-8")
    # Only the `python -c` blocks matter; elsewhere "$WORKSPACE" is correct shell
    # quoting. Those blocks are the ones that open( ... ) a path.
    offenders = [pattern for pattern in FORBIDDEN if f"open({pattern}" in text or f"Path({pattern}" in text]
    assert not offenders, (
        f"caminho interpolado dentro de literal Python em ralph.sh: {offenders} — passe por sys.argv"
    )


def test_paths_arrive_through_argv():
    assert "sys.argv[1]" in RALPH.read_text(encoding="utf-8")


def test_python_is_always_quoted():
    r"""$PYTHON is a path (the engine passes sys.executable): unquoted, a space
    in it — `D:\Flutter Projects\...\.venv\Scripts\python.exe` — split the
    command and extract died with "D:\Flutter: No such file or directory"."""
    import re

    unquoted = [
        f"{n}: {line.strip()}"
        for n, line in enumerate(RALPH.read_text(encoding="utf-8").splitlines(), 1)
        if re.search(r'(^|[^"])\$PYTHON\b', line) and not line.lstrip().startswith(("#", "log "))
    ]
    assert not unquoted, "use \"$PYTHON\" (com aspas) em ralph.sh:\n" + "\n".join(unquoted)
