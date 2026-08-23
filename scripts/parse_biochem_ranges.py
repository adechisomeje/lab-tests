"""Parse the MFT Biochemistry reference-ranges PDF into structured records.

Source: Biochemistry user guide -> "Biochemistry test information"
        https://mft.nhs.uk/app/uploads/2026/06/Biochemistry-reference-ranges-240626.pdf

A 45-page table with columns:
  Test | Sample Type (Preferred, Acceptable) | Turn around time (hours) |
  Sex | Age unit | Lower age limit | Upper age limit | Lower limit | Upper limit | Units

One test spans several rows -- one per age/sex stratum -- with the test name
present only on the first. Tests also continue across page breaks. This yields
age- and sex-stratified reference intervals rather than free text.
"""
import json
import pathlib
import re
import unicodedata

import fitz

ROOT = pathlib.Path(__file__).resolve().parent.parent
SRC = ROOT / "raw" / "biochem-reference-ranges.pdf"
OUT = ROOT / "raw" / "biochem-ranges.json"
SOURCE_URL = "https://mft.nhs.uk/app/uploads/2026/06/Biochemistry-reference-ranges-240626.pdf"

HEADER0 = "test"

# Header label -> canonical column key. Column counts differ page to page (the
# extractor emits spurious empty columns on some pages), so columns are located
# by header text rather than by fixed position.
COLUMN_MAP = {
    "test": "name",
    "sample type (preferred, acceptable)": "sample",
    "sample type": "sample",
    "turn around time (hours)": "tat",
    "turnaround time (hours)": "tat",
    "sex": "sex",
    "age unit": "age_unit",
    "lower age limit": "age_min",
    "upper age limit": "age_max",
    "lower limit": "low",
    "upper limit": "high",
    "units": "units",
}
# Rows that are specimen-group separators rather than tests.
SECTIONS = {"blood", "urine", "csf", "faeces", "fluid", "other", "stone",
            "saliva", "sweat", "dialysate", "miscellaneous"}


def clean(s) -> str:
    s = unicodedata.normalize("NFKC", s or "")
    for ch in "‐‑‒–—−":
        s = s.replace(ch, "-")
    return re.sub(r"\s+", " ", s).strip()


def column_index(header) -> dict | None:
    """Map canonical keys to column positions using the header row."""
    idx = {}
    for i, cell in enumerate(header):
        key = COLUMN_MAP.get(clean(cell).lower())
        if key and key not in idx:
            idx[key] = i
    return idx if {"name", "low", "high"} <= idx.keys() else None


def is_data_table(rows) -> bool:
    return bool(rows) and len(rows[0]) >= 9 and clean(rows[0][0]).lower() == HEADER0


def parse_hours(text: str):
    """Turnaround wording -> hours."""
    t = clean(text).lower()
    if not t:
        return None
    m = re.search(r"(\d+(?:\.\d+)?)\s*hour", t)
    if m:
        return float(m.group(1))
    m = re.search(r"(\d+(?:\.\d+)?)\s*(day|working day)", t)
    if m:
        return float(m.group(1)) * 24
    m = re.search(r"(\d+(?:\.\d+)?)\s*week", t)
    if m:
        return float(m.group(1)) * 168
    m = re.search(r"(\d+(?:\.\d+)?)\s*month", t)
    if m:
        return float(m.group(1)) * 720
    m = re.fullmatch(r"(\d+(?:\.\d+)?)", t)
    return float(m.group(1)) if m else None


def norm_sex(text: str):
    t = clean(text).lower().rstrip(".")
    if not t:
        return None
    if t in {"both", "all", "m, f", "m,f", "m/f", "either"}:
        return "all"
    if t in {"m", "male", "males"}:
        return "male"
    if t in {"f", "female", "females"}:
        return "female"
    return None  # long free text -> handled as a note


def num(text: str):
    """Numeric bound, tolerating '<', '>=', 'None', 'unspecified'."""
    t = clean(text)
    if not t or t.lower() in {"none", "n/a", "na", "unspecified", "-", "nil"}:
        return None
    m = re.search(r"-?\d+(?:\.\d+)?", t.replace(",", ""))
    return float(m.group(0)) if m else None


def bound_op(text: str):
    t = clean(text)
    if t.startswith("≤") or t.startswith("<="):
        return "lte"
    if t.startswith("≥") or t.startswith(">="):
        return "gte"
    if t.startswith("<"):
        return "lt"
    if t.startswith(">"):
        return "gt"
    return None


def parse():
    doc = fitz.open(SRC)
    tests: list[dict] = []
    current = None
    section = None

    for page in doc:
        for tab in page.find_tables().tables:
            rows = tab.extract()
            if not is_data_table(rows):
                continue
            idx = column_index(rows[0])
            if not idx:
                continue
            for raw in rows[1:]:
                cells = [clean(c) for c in raw]
                get = lambda k: cells[idx[k]] if k in idx and idx[k] < len(cells) else ""
                name, sample, tat = get("name"), get("sample"), get("tat")
                sex, aunit = get("sex"), get("age_unit")
                alo, ahi = get("age_min"), get("age_max")
                lo, hi, units = get("low"), get("high"), get("units")

                # Specimen-group separator row: exactly one populated cell,
                # which may sit outside the mapped columns.
                filled = [c for c in cells if c]
                if len(filled) == 1 and filled[0].lower() in SECTIONS:
                    section = filled[0]
                    continue

                if name:
                    current = {
                        "test": name,
                        "section": section,
                        "sample_types_raw": sample or None,
                        "turnaround_raw": tat or None,
                        "turnaround_hours": parse_hours(tat),
                        "units": units or None,
                        "notes": [],
                        "reference_ranges": [],
                    }
                    tests.append(current)
                if current is None:
                    continue
                if units and not current["units"]:
                    current["units"] = units

                # Long prose in the Sex column is interpretive guidance.
                if sex and norm_sex(sex) is None and len(sex) > 20:
                    current["notes"].append(sex)
                    continue

                if not any([sex, aunit, alo, ahi, lo, hi]):
                    continue

                stratum = {
                    "sex": norm_sex(sex),
                    "age_unit": (aunit or None) and clean(aunit).lower(),
                    "age_min": num(alo),
                    "age_max": num(ahi),
                    "low": num(lo),
                    "high": num(hi),
                    "low_op": bound_op(lo),
                    "high_op": bound_op(hi),
                    "raw": {"sex": sex or None, "age_unit": aunit or None,
                            "age_min": alo or None, "age_max": ahi or None,
                            "low": lo or None, "high": hi or None},
                }
                if stratum["low"] is None and stratum["high"] is None and not stratum["sex"]:
                    continue
                current["reference_ranges"].append(stratum)

    for t in tests:
        t["notes"] = " ".join(t["notes"]) or None
    return tests


if __name__ == "__main__":
    tests = parse()
    OUT.write_text(json.dumps({"source_url": SOURCE_URL, "tests": tests},
                              indent=2, ensure_ascii=False), encoding="utf-8")
    strata = sum(len(t["reference_ranges"]) for t in tests)
    print(f"tests={len(tests)}  reference strata={strata}")
    print(f"with sample type={sum(1 for t in tests if t['sample_types_raw'])}  "
          f"with turnaround={sum(1 for t in tests if t['turnaround_hours'])}  "
          f"with units={sum(1 for t in tests if t['units'])}")
    print(f"-> {OUT.relative_to(ROOT)}")
    for t in tests[:3]:
        print("\n", t["test"], "|", t["sample_types_raw"], "|", t["units"])
        for s in t["reference_ranges"][:3]:
            print("    ", {k: s[k] for k in ("sex", "age_unit", "age_min", "age_max", "low", "high")})
