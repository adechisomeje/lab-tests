"""Fetch the MFT A-Z list of laboratory tests page into raw/."""
import pathlib
import ssl
import urllib.request

ROOT = pathlib.Path(__file__).resolve().parent.parent
DEST = ROOT / "raw" / "az-list.html"
URL = ("https://mft.nhs.uk/the-trust/other-departments/laboratory-medicine/"
       "a-z-list-of-laboratory-tests/")
UA = "lab-tests-dataset/0.1 (open dataset builder)"


def ssl_context() -> ssl.SSLContext:
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        import certifi
        ctx = ssl.create_default_context(cafile=certifi.where())
    return ctx


if __name__ == "__main__":
    DEST.parent.mkdir(parents=True, exist_ok=True)
    req = urllib.request.Request(URL, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=60, context=ssl_context()) as resp:
        DEST.write_bytes(resp.read())
    print(f"fetched {DEST.relative_to(ROOT)} ({DEST.stat().st_size} bytes)")
