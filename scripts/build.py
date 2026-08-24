"""Build the lab-tests JSON library from scraped A-Z rows and parsed PDF fields.

Outputs everything under data/:
  tests.json              full library (one record per test)
  index.json              lightweight name/alias search index
  departments.json        department roll-up
  categories.json         clinical categories with member test ids
  clinic-profiles.json    practice-setting profiles with member test ids
  specimens.json          specimen-type roll-up
  by-department/*.json    per-department slices
  by-clinic/*.json        per-clinic-profile slices
"""
import collections
import datetime as dt
import json
import pathlib
import re
import sys
import unicodedata

sys.path.insert(0, str(pathlib.Path(__file__).resolve().parent))
from match import Matcher, fold  # noqa: E402
from result_templates import (  # noqa: E402
    build_templates,
    classify_result_format,
    derive_from_notes,
)

ROOT = pathlib.Path(__file__).resolve().parent.parent
RAW = ROOT / "raw"
DATA = ROOT / "data"
TAX = ROOT / "taxonomy"

VERSION = "0.1.0"
RETRIEVED = dt.date.today().isoformat()
PROVIDER = {
    "id": "mft-nhs",
    "name": "Manchester University NHS Foundation Trust",
    "division": "Division of Laboratory Medicine",
    "country": "GB",
    "source_url": ("https://mft.nhs.uk/the-trust/other-departments/laboratory-medicine/"
                   "a-z-list-of-laboratory-tests/"),
}

# --------------------------------------------------------------------------
# Controlled vocabularies
# --------------------------------------------------------------------------

# Order matters: the most specific pattern wins when several could match.
SPECIMEN_RULES = [
    ("dried-blood-spot", ["dried blood spot", "blood spot", "bloodspot", "guthrie"]),
    ("edta-whole-blood", ["edta whole blood", "edta blood", "whole blood edta", "edta"]),
    ("citrated-plasma", ["citrate", "citrated"]),
    ("fluoride-plasma", ["fluoride", "oxalate"]),
    ("heparinised-plasma", ["lithium heparin", "heparinised", "heparinized", "heparin tube"]),
    ("bone-marrow", ["bone marrow", "trephine"]),
    ("serum", ["serum"]),
    ("plasma", ["plasma"]),
    ("whole-blood", ["whole blood", "venous blood", "arterial blood", "peripheral blood",
                     "capillary blood", "cord blood"]),
    ("csf", ["csf", "cerebrospinal"]),
    ("urine", ["urine", "msu", "csu", "urinary"]),
    ("faeces", ["faeces", "faecal", "stool"]),
    ("swab", ["swab", "eswab"]),
    ("pus", ["pus", "abscess"]),
    ("sputum-respiratory", ["sputum", "bronchoalveolar", "bronchial", "nasopharyngeal",
                            "throat", "respiratory sample", "respiratory specimen", "bal"]),
    ("synovial-fluid", ["synovial", "joint fluid"]),
    ("body-fluid", ["pleural", "ascitic", "peritoneal", "sterile fluid", "capd",
                    "pericardial", "aspirate", "drain fluid"]),
    ("tissue", ["tissue", "biopsy", "histolog"]),
    ("saliva", ["saliva", "salivary"]),
    ("semen", ["semen", "seminal"]),
    ("skin-hair-nail", ["nail clipping", "skin scraping", "hair sample", "nail", "hair"]),
    ("breath", ["breath"]),
    ("sweat", ["sweat"]),
    ("cells", ["stem cell", "lymphocyte", "leucocyte", "white cell"]),
]

# UK vacutainer conventions - a genuinely useful facet for phlebotomy tooling.
TUBE_RULES = [
    ("edta", "Purple / lavender", ["edta"]),
    ("sodium-citrate", "Light blue", ["citrate", "citrated"]),
    ("fluoride-oxalate", "Grey", ["fluoride", "oxalate"]),
    ("lithium-heparin", "Green", ["lithium heparin", "heparin"]),
    ("trace-element", "Royal blue", ["trace element", "trace metal"]),
    ("serum-gel", "Gold / yellow (SST)", ["sst", "gel", "serum separator"]),
    ("plain-serum", "Red", ["plain tube", "clotted", "serum tube", "serum"]),
]

STOP = {"the", "a", "of", "and", "for", "in", "to"}


def norm(s: str) -> str:
    """Lowercase, dash- and quote-normalised text for matching."""
    s = unicodedata.normalize("NFKC", s or "")
    for ch in "‐‑‒–—−":
        s = s.replace(ch, "-")
    s = s.replace("’", "'").replace("\xa0", " ")
    return re.sub(r"\s+", " ", s).strip().lower()


def slugify(s: str) -> str:
    """Stable ASCII slug.

    Folds accents and Greek letters to ASCII first, so "Anti-Müllerian" yields
    "anti-mullerian..." rather than dropping the character and producing
    "anti-m-llerian...".
    """
    s = fold(s)
    s = re.sub(r"[^a-z0-9]+", "-", s).strip("-")
    return re.sub(r"-{2,}", "-", s)[:80].strip("-") or "test"


# --------------------------------------------------------------------------
# Derived facets
# --------------------------------------------------------------------------

def detect_specimens(*texts: str) -> list[str]:
    blob = norm(" | ".join(t for t in texts if t))
    found = []
    for key, pats in SPECIMEN_RULES:
        if any(p in blob for p in pats) and key not in found:
            found.append(key)
    # Prefer the specific form over the generic one.
    if "edta-whole-blood" in found and "whole-blood" in found:
        found.remove("whole-blood")
    specific_plasma = {"edta-whole-blood", "citrated-plasma", "fluoride-plasma",
                       "heparinised-plasma"}
    if "plasma" in found and specific_plasma & set(found):
        found.remove("plasma")
    return found


def detect_tube(*texts: str):
    blob = norm(" | ".join(t for t in texts if t))
    for key, colour, pats in TUBE_RULES:
        if any(p in blob for p in pats):
            return {"type": key, "cap_colour": colour}
    return None


NUM = r"(\d+(?:\.\d+)?)"


def parse_days(value: str):
    """Pull a day count out of free-text turnaround wording."""
    if not value:
        return None
    v = norm(value)
    m = re.search(NUM + r"\s*(?:-|to)\s*" + NUM + r"\s*(?:working\s*|calendar\s*)?days?", v)
    if m:
        return {"min": float(m.group(1)), "max": float(m.group(2))}
    m = re.search(NUM + r"\s*(?:working\s*|calendar\s*)?(?:days?|d\b)", v)
    if m:
        return {"min": float(m.group(1)), "max": float(m.group(1))}
    m = re.search(r"(?:median|mean|average)\s*[-:]?\s*" + NUM, v)
    if m:
        return {"min": float(m.group(1)), "max": float(m.group(1))}
    m = re.search(NUM + r"\s*(?:working\s*)?hours?", v)
    if m:
        h = float(m.group(1))
        return {"min": round(h / 24, 2), "max": round(h / 24, 2)}
    if re.fullmatch(r"\s*" + NUM + r"\s*", v):
        return {"min": float(v.strip()), "max": float(v.strip())}
    return None


def parse_volume(*texts: str):
    """Extract a numeric sample volume in millilitres where stated."""
    blob = norm(" | ".join(t for t in texts if t))
    m = re.search(NUM + r"\s*(ml|mls|millilitre)", blob)
    if m:
        return {"value": float(m.group(1)), "unit": "mL"}
    m = re.search(NUM + r"\s*(µl|ul|microlitre|mcl)", blob)
    if m:
        return {"value": round(float(m.group(1)) / 1000, 4), "unit": "mL"}
    return None


# --------------------------------------------------------------------------
# Taxonomy application
# --------------------------------------------------------------------------

def match_name(name: str) -> str:
    """Name reduced for rule matching.

    Drops explanatory parentheticals -- e.g. the formula inside "Osmolar Gap
    (calculated as: ... + glucose + urea)" -- which would otherwise make a test
    match unrelated analyte keywords. Short parentheticals such as "(HBV)" or
    "(ANA)" are real name content and are kept.
    """
    return re.sub(r"\(([^()]{40,}|[^()]*calculated[^()]*)\)", " ", name or "")


def any_hit(patterns, *texts) -> bool:
    if not patterns:
        return False
    blob = norm(" | ".join(t for t in texts if t))
    return any(norm(p) in blob for p in patterns)


def apply_categories(tests, categories):
    """Assign categories in two passes.

    Pass 1 uses the specific name/text rules. Pass 2 applies department_any only
    to tests that pass 1 left uncategorised, so a broad department rule acts as a
    safety net rather than sweeping every test in that department into the
    category (which would make e.g. every Biochemistry test "clinical chemistry").
    """
    for t in tests:
        name_blob = " | ".join([match_name(t["name"]), *t["aliases"]])
        text_blob = " | ".join(filter(None, [
            t.get("description") or "",
            (t.get("clinical") or {}).get("indications") or "",
        ]))
        hits, fallback = [], []
        for cat in categories:
            m = cat["match"]
            if any_hit(m.get("exclude_name_any"), name_blob):
                continue
            if (any_hit(m.get("name_any"), name_blob)
                    or any_hit(m.get("text_any"), text_blob)):
                hits.append(cat["id"])
            elif t["department"] in m.get("department_any", []):
                fallback.append(cat["id"])
        t["categories"] = hits or fallback
        t["_category_source"] = "rules" if hits else ("department" if fallback else "none")


def apply_profiles(tests, profiles):
    for t in tests:
        name_blob = " | ".join([match_name(t["name"]), *t["aliases"]])
        hits = []
        for prof in profiles:
            m = prof["match"]
            if any_hit(m.get("exclude_name_any"), name_blob):
                continue
            core = any_hit(m.get("core_any"), name_blob)
            by_cat = bool(set(m.get("categories_any", [])) & set(t["categories"]))
            by_name = any_hit(m.get("name_any"), name_blob)
            if core or by_cat or by_name:
                hits.append({"profile": prof["id"], "core": core})
        t["clinic_profiles"] = hits


# --------------------------------------------------------------------------
# Record assembly
# --------------------------------------------------------------------------

def build_records():
    az = json.loads((RAW / "az-rows.json").read_text(encoding="utf-8"))
    rows = az["rows"]
    pdf_fields = json.loads((RAW / "pdf-fields.json").read_text(encoding="utf-8"))
    manifest = {m["url"]: m for m in json.loads((RAW / "pdf-manifest.json").read_text(encoding="utf-8"))}
    by_stem = {v["pdf_stem"]: v for v in pdf_fields.values()}

    anchor_to_row = {r["anchor"]: r for r in rows if r.get("anchor")}

    # Aliases (italic "See X" rows) attach to their canonical target.
    alias_map = collections.defaultdict(list)
    unresolved_aliases = []
    for r in rows:
        if not r["is_alias"]:
            continue
        target = next((anchor_to_row[a] for a in r["see_refs"] if a in anchor_to_row), None)
        if target:
            alias_map[id(target)].append(r["name"])
        else:
            unresolved_aliases.append(r)

    records, seen = [], {}
    for r in rows:
        if r["is_alias"] and any(r["name"] in v for v in alias_map.values()):
            continue
        if r["is_alias"] and r in unresolved_aliases:
            # Keep as a standalone stub so the name is still searchable.
            pass

        key = norm(r["name"])
        pdf = None
        if r["detail_pdf"]:
            stem = manifest.get(r["detail_pdf"], {}).get("file", "")
            pdf = by_stem.get(pathlib.Path(stem).stem) if stem else None

        if key in seen:
            # Merge duplicates, preferring the entry that carries a PDF.
            prev = seen[key]
            for a in alias_map.get(id(r), []):
                if a not in prev["aliases"]:
                    prev["aliases"].append(a)
            if pdf and not prev["source"].get("detail_url"):
                records.remove(prev)
            else:
                continue

        f = (pdf or {}).get("fields", {})
        aliases = sorted(set(alias_map.get(id(r), [])))

        specimen_texts = [f.get("specimen_type"), f.get("volume_and_sample_type"),
                          f.get("sample_type_container"), f.get("container"),
                          f.get("typical_volume"), f.get("minimum_volume")]
        turnaround = {
            "raw": f.get("turnaround_time"),
            "provisional_raw": f.get("turnaround_provisional"),
            "final_raw": f.get("turnaround_final"),
            "days": parse_days(f.get("turnaround_time")),
            "provisional_working_days": parse_days(f.get("turnaround_provisional")),
            "final_working_days": parse_days(f.get("turnaround_final")),
        }

        rec = {
            "id": None,  # assigned after dedupe
            "name": r["name"],
            "aliases": aliases,
            "description": (pdf or {}).get("description"),
            "department": r["department"],
            "letter": r["letter"],
            "categories": [],
            "clinic_profiles": [],
            "specimen": {
                "types": detect_specimens(*specimen_texts),
                "specimen_type_raw": f.get("specimen_type") or f.get("volume_and_sample_type"),
                "container": f.get("container") or f.get("sample_type_container"),
                "tube": detect_tube(f.get("container"), f.get("volume_and_sample_type"),
                                    f.get("sample_type_container"), f.get("specimen_type")),
                "minimum_volume_raw": f.get("minimum_volume") or f.get("typical_volume"),
                "volume": parse_volume(f.get("minimum_volume"), f.get("typical_volume"),
                                       f.get("volume_and_sample_type")),
                "collection": f.get("collection"),
                "transport": f.get("transport"),
                "special_precautions": f.get("special_precautions"),
                "additional_requirements": f.get("additional_requirements"),
            },
            "analysis": {
                "analyte": f.get("analyte"),
                "method": f.get("method"),
                "units": f.get("units") or f.get("reference_units"),
                "reference_range": f.get("reference_range"),
                "clinical_decision_points": f.get("clinical_decision_points"),
                "interferences": f.get("interferences"),
                "limitations": f.get("limitations"),
                "false_positives": f.get("false_positives"),
                "false_negatives": f.get("false_negatives"),
                "eqa_scheme": f.get("eqa_scheme"),
                "frequency_of_analysis": f.get("frequency_of_analysis"),
            },
            "turnaround": turnaround,
            "clinical": {
                "indications": f.get("indications"),
                "interpretation": f.get("interpretation"),
                "repeat_frequency": f.get("repeat_frequency"),
                "references": f.get("references"),
            },
            "referred_to": f.get("referred_to"),
            "notes": r["notes"] or None,
            "source": {
                "provider": PROVIDER["id"],
                "az_url": PROVIDER["source_url"],
                "detail_url": r["detail_pdf"] or r["detail_page"],
                "detail_type": "pdf" if r["detail_pdf"] else ("page" if r["detail_page"] else None),
                "department_url": r["department_url"],
                "last_updated": (pdf or {}).get("last_updated"),
                "retrieved": RETRIEVED,
            },
            "completeness": None,
        }
        records.append(rec)
        seen[key] = rec

    # Stable unique ids
    used = collections.Counter()
    for rec in records:
        base = slugify(rec["name"])
        used[base] += 1
        rec["id"] = base if used[base] == 1 else f"{base}-{used[base]}"

    return records, unresolved_aliases


# Departments whose analytes appear in the Biochemistry reference-range document.
# Haematinics (ferritin, B12, folate) are listed under Haematology in the A-Z but
# are measured on the Biochemistry platform, so they legitimately match.
RANGE_DEPARTMENTS = {"Biochemistry", "Haematology"}


def merge_reference_ranges(records) -> dict:
    """Attach age/sex-stratified reference intervals from the Biochemistry document.

    Every link records how it was made (match_method) so downstream users can
    audit or discard fuzzy links.
    """
    path = RAW / "biochem-ranges.json"
    if not path.exists():
        return {"linked": 0, "skipped": "biochem-ranges.json not built"}

    doc = json.loads(path.read_text(encoding="utf-8"))
    matcher = Matcher(doc["tests"])
    tally = collections.Counter()

    for rec in records:
        if rec["department"] not in RANGE_DEPARTMENTS:
            continue
        hit, how = matcher.match(rec["name"], rec.get("aliases", []))
        if not hit:
            tally["unmatched"] += 1
            continue
        tally[how.split(":")[0]] += 1

        rec["reference_intervals"] = {
            "source": "mft-biochemistry-reference-ranges",
            "source_url": doc["source_url"],
            "matched_name": hit["test"],
            "match_method": how,
            "units": hit.get("units"),
            "notes": hit.get("notes"),
            "strata": hit.get("reference_ranges") or [],
        }

        # Backfill requirement detail this record was missing.
        sp = rec["specimen"]
        if hit.get("sample_types_raw"):
            raw = hit["sample_types_raw"]
            # The source column is "Sample Type (Preferred, Acceptable)", so the
            # first listed option is the preferred specimen.
            options = [o.strip() for o in raw.split(",") if o.strip()]
            if not sp.get("specimen_type_raw"):
                sp["specimen_type_raw"] = raw
            if not sp.get("accepted_specimens"):
                sp["accepted_specimens"] = options
            if options and not sp.get("preferred_specimen"):
                sp["preferred_specimen"] = options[0]
            if not sp.get("types"):
                sp["types"] = detect_specimens(raw)
            if not sp.get("tube"):
                sp["tube"] = detect_tube(options[0] if options else raw)
        if hit.get("turnaround_hours") and not rec["turnaround"].get("raw"):
            hours = hit["turnaround_hours"]
            rec["turnaround"]["raw"] = hit.get("turnaround_raw")
            rec["turnaround"]["days"] = {"min": round(hours / 24, 2),
                                         "max": round(hours / 24, 2)}
        an = rec["analysis"]
        if hit.get("units") and not an.get("units"):
            an["units"] = hit["units"]
        if not an.get("reference_range") and hit.get("reference_ranges"):
            an["reference_range"] = summarise_range(hit["reference_ranges"], hit.get("units"))

    return dict(tally)


def summarise_range(strata, units) -> str | None:
    """One-line human-readable range, preferring the adult all-sex stratum."""
    if not strata:
        return None
    def fmt(s):
        lo, hi = s.get("low"), s.get("high")
        if lo is None and hi is None:
            return None
        if lo is not None and hi is not None:
            body = f"{lo:g} - {hi:g}"
        elif hi is not None:
            body = f"{'<=' if s.get('high_op') in ('lte', None) else '<'} {hi:g}"
        else:
            body = f">= {lo:g}"
        return f"{body} {units}".strip() if units else body
    adult = next((s for s in strata if s.get("sex") in (None, "all")), strata[0])
    out = fmt(adult)
    if out and len(strata) > 1:
        out += f" (adult; {len(strata)} age/sex strata available)"
    return out


    # Completeness score: how much of the requirement detail we actually have.
def score_completeness(records):
    """Rate how much requirement detail each record carries."""
    weighted = [
        ("specimen.types", lambda r: bool(r["specimen"]["types"])),
        ("specimen.container", lambda r: bool(r["specimen"]["container"])),
        ("specimen.transport", lambda r: bool(r["specimen"]["transport"])),
        ("specimen.volume", lambda r: bool(r["specimen"]["minimum_volume_raw"])),
        ("analysis.method", lambda r: bool(r["analysis"]["method"])),
        ("analysis.units", lambda r: bool(r["analysis"]["units"])),
        ("analysis.reference_range", lambda r: bool(r["analysis"]["reference_range"])),
        ("reference_intervals", lambda r: bool((r.get("reference_intervals") or {}).get("strata"))),
        ("turnaround", lambda r: bool(r["turnaround"]["raw"] or r["turnaround"]["final_raw"])),
        ("clinical.indications", lambda r: bool(r["clinical"]["indications"])),
        ("description", lambda r: bool(r["description"])),
    ]
    for rec in records:
        got = [k for k, fn in weighted if fn(rec)]
        rec["completeness"] = {
            "score": round(len(got) / len(weighted), 2),
            "has_detail_sheet": rec["source"]["detail_type"] == "pdf",
            "present": got,
        }



def attach_result_templates(records) -> dict:
    """Attach starter result templates and classify each test's result shape."""
    tax = json.loads((TAX / "result-templates.json").read_text(encoding="utf-8"))
    ids = {r["id"] for r in records}
    templates, warns = build_templates(ids)
    for w in warns:
        print(f"  WARN template: {w}")

    by_test = {}
    for tpl in templates:
        for tid in tpl["applies_to"]:
            by_test[tid] = tpl

    # Panels whose constituent markers the source lists in its notes column.
    derived = 0
    for rec in records:
        if rec["id"] in by_test:
            continue
        d = derive_from_notes(rec, tax["version"], tax["notice"])
        if d:
            by_test[rec["id"]] = d
            templates.append(d)
            derived += 1

    for rec in records:
        tpl = by_test.get(rec["id"])
        if tpl:
            rec["result_template"] = tpl
        rec["result_format"] = classify_result_format(rec, bool(tpl))

    kinds = collections.Counter(r["result_format"]["kind"] for r in records)
    return {
        "templates": len(templates),
        "curated": len(templates) - derived,
        "derived": derived,
        "tests_with_template": len(by_test),
        "formats": dict(kinds),
        "_templates": templates,
    }


def strip_nulls(obj):
    """Drop null/empty leaves so the published JSON stays readable."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            v = strip_nulls(v)
            if v in (None, "", [], {}):
                continue
            out[k] = v
        return out
    if isinstance(obj, list):
        return [strip_nulls(v) for v in obj if v not in (None, "", [], {})]
    return obj


def write(path: pathlib.Path, payload):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")


def main():
    categories = json.loads((TAX / "categories.json").read_text(encoding="utf-8"))["categories"]
    profiles = json.loads((TAX / "clinic-profiles.json").read_text(encoding="utf-8"))["profiles"]

    records, unresolved = build_records()
    range_stats = merge_reference_ranges(records)
    template_stats = attach_result_templates(records)
    score_completeness(records)
    apply_categories(records, categories)
    apply_profiles(records, profiles)

    for r in records:
        r.pop("_category_source", None)
    # Flag detail sheets that no longer resolve upstream, so consumers can tell
    # "no spec sheet published" apart from "spec sheet link is broken".
    fetched = {m["url"] for m in json.loads((RAW / "pdf-manifest.json").read_text(encoding="utf-8"))
               if m["status"] in ("ok", "cached")}
    for r in records:
        url = r["source"].get("detail_url")
        if r["source"].get("detail_type") == "pdf":
            r["source"]["detail_available"] = url in fetched
            if url not in fetched:
                r["completeness"]["has_detail_sheet"] = False

    KEY_ORDER = ["id", "name", "aliases", "description", "department", "letter",
                 "categories", "clinic_profiles", "specimen", "analysis",
                 "reference_intervals", "turnaround", "result_format",
                 "result_template", "clinical", "referred_to", "notes",
                 "source", "completeness"]
    clean = []
    for r in records:
        c = strip_nulls(r)
        for k in ("aliases", "categories", "clinic_profiles"):
            c.setdefault(k, [])
        clean.append({k: c[k] for k in KEY_ORDER if k in c})

    meta = {
        "name": "lab-tests",
        "version": VERSION,
        "description": "Open JSON library of medical laboratory tests, their specimen "
                       "requirements, turnaround times and clinical categorisation.",
        "license": "CC-BY-4.0",
        "generated": RETRIEVED,
        "test_count": len(clean),
        "sources": [PROVIDER],
        "disclaimer": "Informational dataset compiled from published NHS laboratory "
                      "handbooks. Not medical advice. Requirements, reference ranges and "
                      "turnaround times are provider- and method-specific: always confirm "
                      "against your own laboratory's current user handbook before clinical use.",
    }

    write(DATA / "tests.json", {"meta": meta, "tests": clean})
    write(DATA / "index.json", {
        "meta": {k: meta[k] for k in ("name", "version", "generated", "test_count")},
        "tests": [{
            "id": t["id"], "name": t["name"], "aliases": t.get("aliases", []),
            "department": t["department"], "categories": t.get("categories", []),
            "specimens": t.get("specimen", {}).get("types", []),
        } for t in clean],
    })

    # Roll-ups
    dept = collections.defaultdict(list)
    for t in clean:
        dept[t["department"]].append(t["id"])
    write(DATA / "departments.json", {"meta": {"version": VERSION}, "departments": [
        {"id": slugify(d), "name": d, "test_count": len(v), "test_ids": sorted(v)}
        for d, v in sorted(dept.items())]})

    cat_index = {c["id"]: {"id": c["id"], "name": c["name"],
                           "description": c["description"], "test_ids": []} for c in categories}
    for t in clean:
        for c in t.get("categories", []):
            cat_index[c]["test_ids"].append(t["id"])
    write(DATA / "categories.json", {"meta": {"version": VERSION}, "categories": [
        {**v, "test_count": len(v["test_ids"])} for v in cat_index.values()]})

    prof_index = {p["id"]: {"id": p["id"], "name": p["name"], "description": p["description"],
                            "rationale": p["rationale"], "test_ids": [], "core_test_ids": []}
                  for p in profiles}
    for t in clean:
        for entry in t.get("clinic_profiles", []):
            prof_index[entry["profile"]]["test_ids"].append(t["id"])
            if entry.get("core"):
                prof_index[entry["profile"]]["core_test_ids"].append(t["id"])
    write(DATA / "clinic-profiles.json", {"meta": {"version": VERSION}, "profiles": [
        {**v, "test_count": len(v["test_ids"]), "core_test_count": len(v["core_test_ids"])}
        for v in prof_index.values()]})

    write(DATA / "result-templates.json", {
        "meta": {
            "version": VERSION,
            "notice": json.loads(
                (TAX / "result-templates.json").read_text(encoding="utf-8"))["notice"],
        },
        "templates": template_stats.pop("_templates"),
    })

    guidance = json.loads((TAX / "collection-guidance.json").read_text(encoding="utf-8"))
    write(DATA / "providers.json", {
        "meta": {"version": VERSION},
        "providers": [{**PROVIDER, **{k: v for k, v in g.items() if k != "id"}}
                      if g["id"] == PROVIDER["id"] else g
                      for g in guidance["providers"]],
    })

    spec = collections.defaultdict(list)
    for t in clean:
        for s in t.get("specimen", {}).get("types", []):
            spec[s].append(t["id"])
    write(DATA / "specimens.json", {"meta": {"version": VERSION}, "specimens": [
        {"id": k, "test_count": len(v), "test_ids": sorted(v)} for k, v in sorted(spec.items())]})

    for d, ids in dept.items():
        subset = [t for t in clean if t["department"] == d]
        write(DATA / "by-department" / f"{slugify(d)}.json",
              {"meta": {"department": d, "version": VERSION, "test_count": len(subset)},
               "tests": subset})

    for p in profiles:
        ids = set(prof_index[p["id"]]["test_ids"])
        subset = [t for t in clean if t["id"] in ids]
        write(DATA / "by-clinic" / f"{p['id']}.json",
              {"meta": {"profile": p["id"], "name": p["name"], "version": VERSION,
                        "rationale": p["rationale"], "test_count": len(subset)},
               "tests": subset})

    # Report
    print(f"tests: {len(clean)}   departments: {len(dept)}")
    print(f"reference-range linkage: {range_stats}")
    print(f"result templates: {template_stats}")
    print(f"unresolved aliases: {len(unresolved)}")
    with_pdf = sum(1 for t in clean if t.get("completeness", {}).get("has_detail_sheet"))
    avg = sum(t["completeness"]["score"] for t in clean) / len(clean)
    print(f"with detail sheet: {with_pdf}   mean completeness: {avg:.2f}")
    uncat = [t["name"] for t in clean if not t.get("categories")]
    print(f"uncategorised: {len(uncat)}")
    for u in uncat[:15]:
        print("   -", u)
    print("\nclinic profiles:")
    for v in prof_index.values():
        print(f"  {v['id']:34s} {len(v['test_ids']):4d} tests  ({len(v['core_test_ids'])} core)")


if __name__ == "__main__":
    main()
