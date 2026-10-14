"""The notarization key survives however the secret store mangled it."""
import base64
import importlib.util
from pathlib import Path

import pytest

spec = importlib.util.spec_from_file_location("write_p8", Path(__file__).parent.parent / "scripts" / "write_p8.py")
write_p8 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(write_p8)

# Not a real key: a DER SEQUENCE header plus filler, long enough to wrap.
BODY = base64.b64encode(b"\x30\x81\x93" + bytes(range(150))).decode()
PEM = "-----BEGIN PRIVATE KEY-----\n" + "\n".join(BODY[i:i + 64] for i in range(0, len(BODY), 64)) + "\n-----END PRIVATE KEY-----\n"


@pytest.mark.parametrize("stored", [
    PEM,                                        # intact
    PEM.replace("\n", " "),                     # line breaks became spaces
    PEM.replace("\n", ""),                      # line breaks lost
    PEM.replace("\n", "\\n"),                   # literal \n
    base64.b64encode(PEM.encode()).decode(),    # the whole file base64'd
    BODY,                                       # just the key material
])
def test_normalizes_to_the_same_pem(stored):
    assert write_p8.normalize(stored) == PEM


@pytest.mark.parametrize("stored", ["", "ABC123XYZ", "-----BEGIN PRIVATE KEY-----\nnão é base64\n-----END PRIVATE KEY-----"])
def test_rejects_what_isnt_a_key(stored):
    with pytest.raises(ValueError):
        write_p8.normalize(stored)
