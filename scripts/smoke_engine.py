"""Smoke-test a staged engine the way the installed app runs it.

The CI used to only compile the app; Windows users then installed a build
where nothing worked (no Python, no bash…). This runs, in CI, with nothing
but the staged engine on PATH — the environment the Tauri shell builds:

1. the Python imports the pipeline needs;
2. ffmpeg with the subtitles filter (captions);
3. bash and `bash -n ralph.sh`;
4. a real Whisper transcription of a few seconds of generated audio;
5. the React thumbnail renderer (auto-edit-render) drawing a real thumbnail;
6. `auto-edit serve` answering /api/health.

    python scripts/smoke_engine.py desktop/src-tauri/engine
"""
from __future__ import annotations

import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

WIN = sys.platform == "win32"


def log(msg: str) -> None:
    print(f"[smoke] {msg}", flush=True)


def app_env(engine: Path) -> tuple[Path, dict]:
    """Same env as desktop/src-tauri/src/main.rs → engine_command()."""
    python = engine / "python" / ("python.exe" if WIN else "bin/python3")
    bindir = engine / "bin"
    dirs = [bindir, engine / "git" / "usr" / "bin", engine / "git" / "bin"]
    # Only the bundle plus the bare OS: what a machine with nothing installed has.
    if WIN:
        base = [os.path.join(os.environ.get("SystemRoot", r"C:\\Windows"), p) for p in ("System32", "")]
    else:
        base = ["/usr/bin", "/bin", "/usr/sbin", "/sbin"]
    env = {k: v for k, v in os.environ.items() if not k.startswith(("PYTHON", "VIRTUAL_ENV", "CONDA"))}
    env.update({
        "PATH": os.pathsep.join([str(d) for d in dirs] + base),
        "AUTO_EDIT_REPO_ROOT": str(engine / "repo"),
        "AUTO_EDIT_FFMPEG": str(bindir / ("ffmpeg.exe" if WIN else "ffmpeg")),
        "PYTHON": str(python),
        "PYTHONNOUSERSITE": "1",
        "PYTHONUTF8": "1",
        "PYTHONDONTWRITEBYTECODE": "1",
        "NUMBA_CACHE_DIR": os.path.join(tempfile.gettempdir(), "auto-edit-smoke-numba"),
    })
    return python, env


def run(cmd: list[str], env: dict, label: str, **kw) -> str:
    res = subprocess.run(cmd, env=env, capture_output=True, text=True, **kw)
    if res.returncode != 0:
        raise SystemExit(f"FAIL {label}: rc {res.returncode}\n{res.stdout[-1500:]}\n{res.stderr[-1500:]}")
    log(f"ok: {label}")
    return res.stdout


def main(engine: Path) -> None:
    engine = engine.resolve()
    python, env = app_env(engine)
    before = {p for p in engine.rglob("*")}
    exe = ".exe" if WIN else ""
    ffmpeg = str(engine / "bin" / f"ffmpeg{exe}")

    run([str(python), "-c", "import auto_edit, whisper, torch, flask, numpy, pysubs2"], env, "python imports")

    filters = run([ffmpeg, "-hide_banner", "-filters"], env, "ffmpeg")
    if " subtitles " not in filters:
        raise SystemExit("FAIL ffmpeg: no subtitles filter (libass) — captions would fail")

    # Resolve on the app's PATH: on Windows a child started with a custom env
    # is still looked up on the *parent's* PATH.
    bash = shutil.which("bash", path=env["PATH"])
    if not bash:
        raise SystemExit("FAIL bash: not on the engine's PATH (Windows needs the bundled PortableGit)")
    log(f"bash: {bash}")
    run([bash, "--version"], env, "bash runs")
    run([bash, "-n", str(engine / "repo" / "ralph.sh")], env, "ralph.sh syntax")
    for tool in ("tr", "tee", "mktemp"):  # what ralph.sh calls
        run([bash, "-c", f"command -v {tool}"], env, f"{tool} on PATH")
    # timeout: coreutils, or ralph.sh's own fallback (a bare Mac has none).
    portable = ('eval "$(sed -n "/^# >>> portable/,/^# <<< portable/p" "$1")"; '
                'timeout 5 true || exit 1; timeout 1 sleep 5; [ $? = 124 ]')
    run([bash, "-c", portable, "_", str(engine / "repo" / "ralph.sh")], env, "timeout works (or ralph.sh fallback)")

    with tempfile.TemporaryDirectory() as d:
        wav = Path(d) / "tone.wav"
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "sine=frequency=440:duration=3",
             "-ar", "16000", str(wav)], env, "ffmpeg generates audio")
        out = run([str(python), "-c",
                   "import sys, json, whisper; m = whisper.load_model('tiny'); "
                   "r = m.transcribe(sys.argv[1], fp16=False); print(json.dumps({'ok': True, 'segments': len(r['segments'])}))",
                   str(wav)], env, "whisper transcribes (tiny model)", timeout=900)
        log(out.strip().splitlines()[-1])

        # The thumbnailer finds auto-edit-render on the app's PATH and draws
        # the React layout (it would silently fall back to Pillow: check it didn't).
        frame = Path(d) / "frame.jpg"
        run([ffmpeg, "-hide_banner", "-loglevel", "error", "-f", "lavfi", "-i", "testsrc2=s=1920x1080",
             "-frames:v", "1", str(frame)], env, "ffmpeg extracts a frame")
        thumb = Path(d) / "thumb.png"
        out = run([str(python), "-c",
                   "import sys; sys.path.insert(0, sys.argv[1]); import thumbnailer as T; "
                   "ok = T._render_react({'kind': 'short', 'width': 1080, 'height': 1920, 'main_text': 'Teste da thumbnail', "
                   "'sub_text': 'é React', 'accent': [55, 224, 160], 'background': sys.argv[2]}, T.Path(sys.argv[3])); "
                   "sys.exit(0 if ok else 1)",
                   str(engine / "repo" / "tools"), str(frame), str(thumb)], env, "React thumbnail renders", timeout=120)
        if not thumb.read_bytes().startswith(b"\x89PNG"):
            raise SystemExit("FAIL renderer: output is not a PNG")

    port = "8799"
    proc = subprocess.Popen([str(python), "-m", "auto_edit.cli", "serve", "--port", port],
                            env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    try:
        for _ in range(60):
            try:
                with urllib.request.urlopen(f"http://127.0.0.1:{port}/api/health", timeout=2) as r:
                    body = json.loads(r.read())
                if body.get("ok"):
                    log(f"ok: engine serves /api/health (repo_root={body.get('repo_root')})")
                    break
            except OSError:
                time.sleep(1)
        else:
            proc.kill()
            raise SystemExit(f"FAIL engine never answered /api/health:\n{proc.stdout.read()[-2000:]}")
    finally:
        proc.terminate()
    # The installed app must never write inside itself: on macOS a new file
    # breaks the signed app's seal ("damaged" on the next launch).
    new = sorted(str(p.relative_to(engine)) for p in set(engine.rglob("*")) - before)
    if new:
        raise SystemExit(f"FAIL the engine wrote {len(new)} files inside the app, e.g.:\n" + "\n".join(new[:15]))
    log("ok: nothing written inside the app")
    log("engine OK")


if __name__ == "__main__":
    main(Path(sys.argv[1]))
