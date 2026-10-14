"""Sign every Mach-O in the staged engine for notarization (macOS).

Apple notarizes an app only if *every* binary inside it is signed with a
Developer ID, hardened runtime on and a secure timestamp. Tauri signs the app's
own executable; the engine (Python, thousands of torch/numpy .so/.dylib,
ffmpeg) sits in Resources and has to be signed here, before bundling.

Executables (python3, ffmpeg, ffprobe) get engine.entitlements: under the
hardened runtime, Python needs to load extension modules and numba/llvmlite
JIT-compile code.

    python scripts/sign_macos_engine.py desktop/src-tauri/engine --identity "Developer ID Application: …"
    python scripts/sign_macos_engine.py desktop/src-tauri/engine --identity -   # ad-hoc (PR builds)
"""
from __future__ import annotations

import argparse
import struct
import subprocess
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

ENTITLEMENTS = Path(__file__).resolve().parent.parent / "desktop" / "src-tauri" / "engine.entitlements"

THIN = {b"\xcf\xfa\xed\xfe", b"\xce\xfa\xed\xfe"}  # 64/32-bit, little-endian
FAT = {b"\xca\xfe\xba\xbe", b"\xca\xfe\xba\xbf"}
MH_EXECUTE = 2


def macho_kind(path: Path) -> str | None:
    """'exe', 'lib' (dylib/bundle/.so) or None when it isn't Mach-O."""
    try:
        with path.open("rb") as f:
            head = f.read(32)
            if head[:4] in THIN:
                filetype = struct.unpack("<I", head[12:16])[0]
            elif head[:4] in FAT:
                nfat = struct.unpack(">I", head[4:8])[0]
                if not 0 < nfat < 10:  # Java .class files share the magic
                    return None
                wide = head[:4] == b"\xca\xfe\xba\xbf"
                offset = struct.unpack(">Q", head[16:24])[0] if wide else struct.unpack(">I", head[16:20])[0]
                f.seek(offset)
                arch = f.read(16)
                if arch[:4] not in THIN:
                    return None
                filetype = struct.unpack("<I", arch[12:16])[0]
            else:
                return None
    except OSError:
        return None
    return "exe" if filetype == MH_EXECUTE else "lib"


def find(engine: Path) -> tuple[list[Path], list[Path]]:
    libs, exes = [], []
    for p in engine.rglob("*"):
        if p.is_file() and not p.is_symlink() and p.stat().st_size > 1024:
            kind = macho_kind(p)
            if kind == "exe":
                exes.append(p)
            elif kind == "lib":
                libs.append(p)
    return libs, exes


def codesign(path: Path, identity: str, entitlements: Path | None) -> str | None:
    cmd = ["codesign", "--force", "--options", "runtime", "--sign", identity]
    if identity != "-":
        cmd.append("--timestamp")  # notarization requires a secure timestamp
    if entitlements:
        cmd += ["--entitlements", str(entitlements)]
    res = subprocess.run(cmd + [str(path)], capture_output=True, text=True)
    return None if res.returncode == 0 else f"{path}: {res.stderr.strip()}"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("engine", type=Path)
    ap.add_argument("--identity", required=True, help='Developer ID identity, or "-" for ad-hoc')
    args = ap.parse_args()

    libs, exes = find(args.engine.resolve())
    print(f"[sign] {len(libs)} libraries, {len(exes)} executables", flush=True)
    errors = []
    # Libraries first: an executable's signature doesn't cover them, but sign
    # leaves before what loads them, as Apple recommends.
    with ThreadPoolExecutor(max_workers=8) as pool:
        errors += [e for e in pool.map(lambda p: codesign(p, args.identity, None), libs) if e]
        errors += [e for e in pool.map(lambda p: codesign(p, args.identity, ENTITLEMENTS), exes) if e]
    if errors:
        print("\n".join(errors[:20]), file=sys.stderr)
        raise SystemExit(f"[sign] {len(errors)} files failed to sign")
    for exe in exes:
        print(f"[sign] {exe.relative_to(args.engine.resolve())}", flush=True)
    print("[sign] done", flush=True)


if __name__ == "__main__":
    main()
