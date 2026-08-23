"""Download the per-test PDF spec sheets linked from the A-Z list.

Polite by design: small worker pool, per-request delay, resumable (skips files
already cached in raw/pdfs/), and it never re-fetches on a rerun.
"""
import hashlib
import json
import pathlib
import ssl
import sys
import threading
import time
import urllib.parse
import urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = pathlib.Path(__file__).resolve().parent.parent
ROWS = ROOT / "raw" / "az-rows.json"
PDF_DIR = ROOT / "raw" / "pdfs"
MANIFEST = ROOT / "raw" / "pdf-manifest.json"

UA = "lab-tests-dataset/0.1 (open dataset builder; +https://github.com/)"
WORKERS = 4
DELAY = 0.35  # seconds between requests per worker


def ssl_context() -> ssl.SSLContext:
    """Verified TLS context, falling back to certifi's bundle.

    Some Python builds (notably python.org macOS installers) ship without a
    populated CA store; certifi supplies one. Verification stays ON either way.
    """
    ctx = ssl.create_default_context()
    if ctx.cert_store_stats().get("x509_ca", 0) == 0:
        try:
            import certifi
            ctx = ssl.create_default_context(cafile=certifi.where())
        except ImportError:
            raise SystemExit(
                "No CA certificates available. Install certifi "
                "(pip install certifi) or run 'Install Certificates.command'."
            )
    return ctx


SSL_CTX = ssl_context()
_lock = threading.Lock()


def local_name(url: str) -> str:
    """Stable, collision-free filename derived from the URL path."""
    base = urllib.parse.unquote(url.rsplit("/", 1)[-1])
    stem = pathlib.Path(base).stem[:80]
    digest = hashlib.sha1(url.encode()).hexdigest()[:8]
    return f"{stem}--{digest}.pdf"


def encode_url(url: str) -> str:
    """Percent-encode non-ASCII path characters.

    A few links contain U+2010 (unicode hyphen) rather than ASCII '-', which
    urllib refuses to send raw.
    """
    parts = urllib.parse.urlsplit(url)
    return urllib.parse.urlunsplit((
        parts.scheme, parts.netloc,
        urllib.parse.quote(parts.path, safe="/%"),
        urllib.parse.quote(parts.query, safe="=&%"),
        parts.fragment,
    ))


def fetch(url: str) -> dict:
    dest = PDF_DIR / local_name(url)
    rec = {"url": url, "file": dest.name}
    if dest.exists() and dest.stat().st_size > 0:
        rec["status"] = "cached"
        rec["bytes"] = dest.stat().st_size
        return rec
    try:
        req = urllib.request.Request(encode_url(url), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=60, context=SSL_CTX) as resp:
            data = resp.read()
        if not data.startswith(b"%PDF"):
            rec["status"] = "not-a-pdf"
            return rec
        dest.write_bytes(data)
        rec["status"] = "ok"
        rec["bytes"] = len(data)
    except Exception as exc:  # noqa: BLE001 - record and continue
        rec["status"] = "error"
        rec["error"] = f"{type(exc).__name__}: {exc}"
    time.sleep(DELAY)
    return rec


# Department-level source documents that are not linked from the A-Z rows.
EXTRA_SOURCES = {
    "https://mft.nhs.uk/app/uploads/2026/06/Biochemistry-reference-ranges-240626.pdf":
        ROOT / "raw" / "biochem-reference-ranges.pdf",
}


def fetch_extras():
    for url, dest in EXTRA_SOURCES.items():
        if dest.exists() and dest.stat().st_size > 0:
            print(f"  cached {dest.name}")
            continue
        req = urllib.request.Request(encode_url(url), headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=120, context=SSL_CTX) as resp:
            dest.write_bytes(resp.read())
        print(f"  fetched {dest.name} ({dest.stat().st_size} bytes)")


def main():
    PDF_DIR.mkdir(parents=True, exist_ok=True)
    rows = json.loads(ROWS.read_text(encoding="utf-8"))["rows"]
    urls = sorted({r["detail_pdf"] for r in rows if r.get("detail_pdf")})
    print(f"fetching {len(urls)} pdfs -> {PDF_DIR.relative_to(ROOT)}", flush=True)

    results = []
    done = 0
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        for rec in pool.map(fetch, urls):
            results.append(rec)
            done += 1
            if done % 25 == 0:
                print(f"  {done}/{len(urls)}", flush=True)

    MANIFEST.write_text(json.dumps(results, indent=2), encoding="utf-8")

    print("department-level sources:")
    fetch_extras()
    tally = {}
    for r in results:
        tally[r["status"]] = tally.get(r["status"], 0) + 1
    print("status:", tally)
    for r in results:
        if r["status"] not in ("ok", "cached"):
            print("  FAIL", r["url"], r.get("error", r["status"]), file=sys.stderr)


if __name__ == "__main__":
    main()
