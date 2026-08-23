"""Extract plain text from the cached PDF spec sheets.

Sits between fetch_pdfs.py and parse_pdfs.py: the parser reads text files, not
PDFs, so that the text layer is reviewable, diffable and committed. Keeping the
extracted text in the repository also lets the dataset rebuild without
re-downloading 48MB of source PDFs.
"""

import pathlib
import sys
import warnings

warnings.filterwarnings("ignore")

import fitz  # PyMuPDF

ROOT = pathlib.Path(__file__).resolve().parent.parent
PDF_DIR = ROOT / "raw" / "pdfs"
TXT_DIR = ROOT / "raw" / "pdf-text"


def extract(path: pathlib.Path) -> str:
    doc = fitz.open(path)
    try:
        return "\n".join(page.get_text() for page in doc)
    finally:
        doc.close()


def main() -> int:
    if not PDF_DIR.exists() or not any(PDF_DIR.glob("*.pdf")):
        print(f"no PDFs in {PDF_DIR.relative_to(ROOT)}; run scripts/fetch_pdfs.py first",
              file=sys.stderr)
        return 1

    TXT_DIR.mkdir(parents=True, exist_ok=True)
    pdfs = sorted(PDF_DIR.glob("*.pdf"))
    written, failed = 0, []

    for pdf in pdfs:
        dest = TXT_DIR / (pdf.stem + ".txt")
        try:
            dest.write_text(extract(pdf), encoding="utf-8")
            written += 1
        except Exception as exc:  # noqa: BLE001 - record and continue
            failed.append((pdf.name, f"{type(exc).__name__}: {exc}"))

    # Drop stale text whose PDF no longer exists, so a rename upstream cannot
    # leave an orphan behind that the parser would still pick up.
    stems = {p.stem for p in pdfs}
    removed = 0
    for txt in TXT_DIR.glob("*.txt"):
        if txt.stem not in stems:
            txt.unlink()
            removed += 1

    print(f"extracted {written}/{len(pdfs)} pdfs -> {TXT_DIR.relative_to(ROOT)}"
          + (f"  (removed {removed} orphaned)" if removed else ""))
    for name, err in failed:
        print(f"  FAIL {name}: {err}", file=sys.stderr)
    return 1 if failed else 0


if __name__ == "__main__":
    sys.exit(main())
