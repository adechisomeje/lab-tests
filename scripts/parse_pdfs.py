"""Parse the per-test PDF spec sheets into normalised requirement fields.

Each MFT spec sheet follows a common template: a masthead (division, department,
page markers), the test title, then "Label: value" pairs grouped under
"General information" / "Laboratory information" / "Clinical information".
Values routinely wrap across several lines, so values are sliced as the text
between one known label and the next.
"""
import json
import pathlib
import re
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
TXT_DIR = ROOT / "raw" / "pdf-text"
OUT = ROOT / "raw" / "pdf-fields.json"

# Curated label -> canonical field. Only these act as value boundaries, so
# incidental "Word:" text inside a value cannot split it.
LABELS = {
    "specimen type": "specimen_type",
    "sample type": "specimen_type",
    "analyte": "analyte",
    "volume and sample type": "volume_and_sample_type",
    "type and volume of sample": "volume_and_sample_type",
    "sample type/container": "sample_type_container",
    "collection container (including preservatives)": "container",
    "collection container": "container",
    "specimen container": "container",
    "container": "container",
    "collection": "collection",
    "minimum volume of sample": "minimum_volume",
    "minimum volume": "minimum_volume",
    "typical volume": "typical_volume",
    "specimen transport": "transport",
    "transport": "transport",
    "special precautions": "special_precautions",
    "additional/special requirements": "additional_requirements",
    "repeat frequency": "repeat_frequency",
    "frequency of analysis": "frequency_of_analysis",
    "lab assay runs": "frequency_of_analysis",
    "method": "method",
    "measurement units": "units",
    "biological reference units": "reference_units",
    "units": "units",
    "normal reference range": "reference_range",
    "reference range": "reference_range",
    "normal range": "reference_range",
    "biological interval/clinical decision values": "reference_range",
    "clinical decision points": "clinical_decision_points",
    "turnaround time (calendar days from sample receipt to authorised result)": "turnaround_time",
    "turnaround time for provisional result (working days)": "turnaround_provisional",
    "turnaround time to final result (working days)": "turnaround_final",
    "turnaround time to final result": "turnaround_final",
    "turnaround times": "turnaround_time",
    "turnaround time": "turnaround_time",
    "factors known to significantly affect the results": "interferences",
    "factors affecting the test": "interferences",
    "assay interferences": "interferences",
    "limitations": "limitations",
    "possible causes of false negatives": "false_negatives",
    "possible causes of false positives": "false_positives",
    "indications for the test": "indications",
    "interpretation": "interpretation",
    "participation in eqa scheme": "eqa_scheme",
    "referred to": "referred_to",
    "references": "references",
}

SECTIONS = ["general information", "laboratory information", "clinical information",
            "additional information", "further information"]

BOILERPLATE = re.compile(
    r"^\s*(division of laboratory medicine|mft\.nhs\.uk/laboratorymedicine|"
    r"\d+\s*/\s*\d+|page \d+ of \d+)\s*$", re.I)

LABEL_RE = re.compile(
    r"^[ \t]*(" + "|".join(sorted((re.escape(k) for k in LABELS), key=len, reverse=True))
    + r")[ \t]*:[ \t]*", re.I | re.M)
SECTION_RE = re.compile(r"^[ \t]*(" + "|".join(SECTIONS) + r")[ \t]*:?[ \t]*$", re.I | re.M)
UPDATED_RE = re.compile(r"\(\s*last (?:updated|reviewed)\s*:?\s*([^)]{3,40})\)", re.I)


def clean(raw: str) -> str:
    s = unicodedata.normalize("NFKC", raw)
    # Unicode hyphens/dashes and odd spaces -> ASCII equivalents
    s = s.replace("‐", "-").replace("‑", "-").replace("–", "-")
    s = s.replace("’", "'").replace("\xa0", " ")
    return s


def strip_masthead(text: str):
    """Remove repeated header/footer lines; return (department, title, body)."""
    lines = [ln.rstrip() for ln in text.splitlines()]
    department, title = None, None
    kept = []
    for i, ln in enumerate(lines):
        stripped = ln.strip()
        if not stripped:
            kept.append("")
            continue
        if BOILERPLATE.match(stripped):
            # The department is the line immediately above the site URL.
            if stripped.lower().startswith("mft.nhs.uk") and department is None:
                for prev in reversed(kept):
                    if prev.strip():
                        department = prev.strip()
                        kept.remove(prev)
                        break
            continue
        kept.append(ln)

    body_lines = [ln for ln in kept]
    # Title: first substantive line that is not a section heading.
    for idx, ln in enumerate(body_lines):
        s = ln.strip()
        if s and not SECTION_RE.match(s) and not LABEL_RE.match(s + ":"):
            title = s
            body_lines = body_lines[idx + 1:]
            break
    return department, title, "\n".join(body_lines)


def parse_fields(body: str) -> dict:
    """Slice `Label: value` pairs, using labels and section headings as bounds."""
    marks = []
    for m in LABEL_RE.finditer(body):
        marks.append((m.start(), m.end(), LABELS[m.group(1).strip().lower()]))
    for m in SECTION_RE.finditer(body):
        marks.append((m.start(), m.end(), None))  # boundary only
    marks.sort()

    fields = {}
    for i, (start, end, key) in enumerate(marks):
        if key is None:
            continue
        stop = marks[i + 1][0] if i + 1 < len(marks) else len(body)
        value = tidy(body[end:stop])
        if not value:
            continue
        # Keep the longest value when a label legitimately repeats.
        if key not in fields or len(value) > len(fields[key]):
            fields[key] = value
    return fields


def tidy(value: str) -> str:
    """Normalise a sliced value: drop the doc trailer, unwrap soft line breaks."""
    value = UPDATED_RE.sub("", value)
    value = re.sub(r"[ \t]*\n[ \t]*", "\n", value).strip()
    # Blank line = real paragraph break; a lone newline is just PDF line wrap.
    parts = [re.sub(r"\s*\n\s*", " ", p).strip() for p in re.split(r"\n\s*\n", value)]
    value = "\n\n".join(p for p in parts if p)
    return re.sub(r"[ \t]{2,}", " ", value).strip(" :;\n")


def describe(body: str, fields: dict) -> str | None:
    """Free-text preamble before the first labelled field = test description."""
    first = LABEL_RE.search(body)
    cut = first.start() if first else len(body)
    intro = SECTION_RE.sub("", body[:cut])
    intro = tidy(intro).replace("\n\n", " ")
    intro = re.sub(r"\s{2,}", " ", intro).strip()
    return intro if len(intro) > 25 else None


def main():
    out = {}
    for f in sorted(TXT_DIR.glob("*.txt")):
        text = clean(f.read_text(encoding="utf-8"))
        department, title, body = strip_masthead(text)
        fields = parse_fields(body)
        upd = UPDATED_RE.search(text)
        out[f.stem] = {
            "pdf_stem": f.stem,
            "pdf_title": title,
            "pdf_department": department,
            "description": describe(body, fields),
            "last_updated": upd.group(1).strip() if upd else None,
            "fields": fields,
        }
    OUT.write_text(json.dumps(out, indent=2, ensure_ascii=False), encoding="utf-8")

    import collections
    tally = collections.Counter()
    for rec in out.values():
        tally.update(rec["fields"].keys())
    print(f"parsed {len(out)} pdfs -> {OUT.relative_to(ROOT)}")
    print(f"{'field':28s} docs")
    for k, v in tally.most_common():
        print(f"  {k:26s} {v}")
    empty = [k for k, v in out.items() if not v["fields"]]
    print(f"\npdfs with zero fields: {len(empty)}")
    for e in empty[:10]:
        print("   ", e)


if __name__ == "__main__":
    main()
