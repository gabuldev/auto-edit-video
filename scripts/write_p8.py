"""Write the App Store Connect API key (AuthKey_XXXX.p8) for notarization.

The key comes from a secret store (Doppler), where pasting a PEM easily loses
its line breaks, turns them into literal "\\n", or gets base64-encoded — and
the notarization then fails with "invalidPEMDocument". Accept all of those
and write a proper PEM.

    APPLE_API_KEY_P8=... python scripts/write_p8.py "$RUNNER_TEMP/AuthKey.p8"
"""
from __future__ import annotations

import base64
import binascii
import os
import re
import sys
import textwrap

HEADER, FOOTER = "-----BEGIN PRIVATE KEY-----", "-----END PRIVATE KEY-----"


def normalize(raw: str) -> str:
    text = raw.strip().replace("\\n", "\n")
    if "BEGIN" not in text:
        try:  # the whole .p8 file, base64-encoded
            decoded = base64.b64decode(text, validate=False).decode()
            if "BEGIN" in decoded:
                text = decoded
        except (binascii.Error, UnicodeDecodeError):
            pass
    body = re.sub(r"-----(BEGIN|END) [A-Z ]*PRIVATE KEY-----", "", text)
    body = re.sub(r"\s+", "", body)
    if not body:
        raise ValueError("empty key")
    try:
        der = base64.b64decode(body, validate=True)
    except binascii.Error as exc:
        raise ValueError(f"not base64 key material ({exc})") from exc
    if not der.startswith(b"\x30"):  # a PKCS#8 key is a DER SEQUENCE
        raise ValueError("doesn't look like a private key")
    return "\n".join([HEADER, *textwrap.wrap(body, 64), FOOTER]) + "\n"


def main(out: str) -> None:
    try:
        pem = normalize(os.environ.get("APPLE_API_KEY_P8", ""))
    except ValueError as exc:
        raise SystemExit(f"::error::APPLE_API_KEY_P8 is not a valid AuthKey_XXXX.p8 ({exc}): "
                         "paste the whole file content, BEGIN/END lines included")
    with open(out, "w") as f:
        f.write(pem)
    os.chmod(out, 0o600)
    print("AuthKey.p8 ok")


if __name__ == "__main__":
    main(sys.argv[1])
