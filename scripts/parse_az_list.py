"""Parse the MFT NHS A-Z list of laboratory tests into structured records.

Source: https://mft.nhs.uk/the-trust/other-departments/laboratory-medicine/a-z-list-of-laboratory-tests/

The page is a series of <h1 id="LETTER"> headings, each followed by a table whose
rows are: [test name] | [department] | [notes]. Names may link to a per-test PDF
spec sheet or to a department page. Names wrapped in <em> are synonyms/aliases
that cross-reference a canonical entry via "See ..." in the notes column.
"""
import html
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "raw" / "az-list.html"
OUT = ROOT / "raw" / "az-rows.json"
SOURCE_URL = ("https://mft.nhs.uk/the-trust/other-departments/laboratory-medicine/"
              "a-z-list-of-laboratory-tests/")

TAG_RE = re.compile(r"<[^>]+>")
WS_RE = re.compile(r"\s+")


def text_of(fragment: str) -> str:
    """Strip tags/entities from an HTML fragment and normalise whitespace."""
    s = re.sub(r"<br\s*/?>", " ", fragment, flags=re.I)
    s = TAG_RE.sub("", s)
    s = html.unescape(s)
    s = s.replace("\xa0", " ")
    s = unicodedata.normalize("NFKC", s)
    return WS_RE.sub(" ", s).strip()


def links_of(fragment: str):
    return [html.unescape(h) for h in re.findall(r'href="([^"]+)"', fragment)]


def parse():
    raw = SRC.read_text(encoding="utf-8", errors="replace")

    # Restrict to the page's content body so nav/footer tables can't leak in.
    start = raw.find('<div class="c-content__body">')
    end = raw.find('<div class="c-content__after"', start)
    if end == -1:
        end = raw.find("</article>", start)
    body = raw[start:end]

    rows = []
    # Split the body on letter headings so each row inherits its A-Z section.
    parts = re.split(r'<h1 id="([^"]+)"[^>]*>', body)
    # parts = [preamble, id1, chunk1, id2, chunk2, ...]
    for i in range(1, len(parts), 2):
        letter = html.unescape(parts[i]).strip()
        chunk = parts[i + 1]
        if letter.lower() == "top":
            continue
        for tr in re.finditer(r"<tr([^>]*)>(.*?)</tr>", chunk, re.S | re.I):
            attrs, inner = tr.group(1), tr.group(2)
            anchor = re.search(r'id="([^"]+)"', attrs)
            cells = re.findall(r"<t[dh][^>]*>(.*?)</t[dh]>", inner, re.S | re.I)
            if len(cells) < 2:
                continue
            name_html = cells[0]
            dept_html = cells[1]
            note_html = cells[2] if len(cells) > 2 else ""

            name = text_of(name_html)
            if not name:
                continue
            # Header rows repeat the column titles; skip them.
            if name.lower() in {"test", "test name", "name", "examination"}:
                continue

            name_links = links_of(name_html)
            pdf = next((u for u in name_links if u.lower().endswith(".pdf")), None)
            page = next((u for u in name_links
                         if not u.lower().endswith(".pdf") and u.startswith("http")), None)

            rows.append({
                "letter": letter,
                "anchor": anchor.group(1) if anchor else None,
                "name": name,
                # <em> marks a synonym pointing at a canonical entry
                "is_alias": bool(re.search(r"<(em|i)\b", name_html, re.I)),
                "detail_pdf": pdf,
                "detail_page": page,
                "department": text_of(dept_html),
                "department_url": next((u for u in links_of(dept_html) if u.startswith("http")), None),
                "notes": text_of(note_html),
                "see_refs": [u[1:] for u in links_of(note_html) if u.startswith("#")],
                "note_links": [u for u in links_of(note_html) if u.startswith("http")],
            })
    return rows


if __name__ == "__main__":
    rows = parse()
    OUT.write_text(json.dumps({"source_url": SOURCE_URL, "rows": rows},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    aliases = sum(1 for r in rows if r["is_alias"])
    print(f"rows={len(rows)}  aliases={aliases}  canonical={len(rows)-aliases}")
    print(f"with_pdf={sum(1 for r in rows if r['detail_pdf'])}  "
          f"with_page={sum(1 for r in rows if r['detail_page'])}")
    print(f"-> {OUT.relative_to(ROOT)}")
