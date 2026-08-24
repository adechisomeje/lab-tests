"""Build structured result-entry templates.

These are STARTER templates. A clinic activates a test, copies the template into
its own catalogue, confirms every component, unit and entry mode against its own
analyser, and versions it. The activated copy is authoritative; this library only
seeds it.

Reference ranges and critical limits are deliberately never emitted here. They
vary by laboratory, analyser and population, so a global library asserting them
would be actively unsafe. They live in the clinic's activated definition.
"""

from __future__ import annotations

import json
import pathlib
import re

ROOT = pathlib.Path(__file__).resolve().parent.parent
TAX = ROOT / "taxonomy" / "result-templates.json"
PATTERNS = ROOT / "taxonomy" / "result-patterns.json"
RANGES = ROOT / "raw" / "biochem-ranges.json"

UNITS_SOURCE = "mft-biochemistry-reference-ranges"

# Units that carry no information and should not be presented as a suggestion.
_EMPTY_UNITS = {"", "n/a", "na", "not applicable", "none", "-"}

# Departments whose result is a written report, not a set of numeric fields.
NARRATIVE_DEPARTMENTS = {
    "Histopathology",
    "Non-Gynaecology Cytology",
    "Gynaecological Cytology",
    "Synovial Fluid Cytology",
}

# Departments whose routine output is an organism/susceptibility report rather
# than a single measured quantity.
QUALITATIVE_DEPARTMENTS = {
    "Bacteriology", "Mycology", "Microbiology", "Molecular Microbiology",
    "Virology", "Meningococcal Reference Unit", "Vaccine Evaluation Unit",
}


def meaningful(units: str | None) -> bool:
    return bool(units) and units.strip().lower() not in _EMPTY_UNITS


def load_analyte_units() -> dict[str, str]:
    """Map analyte name -> published units from the reference-range document."""
    if not RANGES.exists():
        return {}
    out = {}
    for t in json.loads(RANGES.read_text(encoding="utf-8"))["tests"]:
        if meaningful(t.get("units")):
            out.setdefault(t["test"], t["units"])
    return out


def build_templates(test_ids: set[str]) -> tuple[list[dict], list[str]]:
    """Resolve the curated taxonomy into published templates.

    Returns (templates, warnings). Warnings flag dangling references so a typo
    in the taxonomy surfaces at build time rather than in a clinic's UI.
    """
    doc = json.loads(TAX.read_text(encoding="utf-8"))
    analyte_units = load_analyte_units()
    version = doc["version"]
    notice = doc["notice"]
    warnings: list[str] = []
    out: list[dict] = []

    for tpl in doc["templates"]:
        for tid in tpl["applies_to"]:
            if tid not in test_ids:
                warnings.append(f"template {tpl['id']}: applies_to unknown test {tid!r}")

        components = []
        for c in tpl["components"]:
            units = c.get("suggested_units")
            units_prov = None
            ref = c.get("analyte_ref")
            if c.get("unitless"):
                # Ratios and indices carry no units; analyte_ref is documentation.
                ref = None
            if ref:
                resolved = analyte_units.get(ref)
                if resolved:
                    units = units or resolved
                    units_prov = {"source": UNITS_SOURCE, "analyte": ref}
                else:
                    warnings.append(
                        f"template {tpl['id']}/{c['id']}: analyte_ref {ref!r} not found "
                        f"in the reference-range document")
            elif units:
                units_prov = {"source": "curated"}

            if c.get("catalogue_ref") and c["catalogue_ref"] not in test_ids:
                warnings.append(
                    f"template {tpl['id']}/{c['id']}: catalogue_ref "
                    f"{c['catalogue_ref']!r} is not a test id")

            comp = {
                "id": c["id"],
                "name": c["name"],
                "type": c.get("type", "numeric"),
                "entry_mode": c.get("entry_mode", "measured"),
                "required": bool(c.get("required")),
            }
            if c.get("unitless"):
                comp["unitless"] = True
            elif units:
                comp["suggested_units"] = units
                if c.get("alternate_units"):
                    comp["alternate_units"] = c["alternate_units"]
            if units_prov:
                comp["units_provenance"] = units_prov
            if c.get("catalogue_ref"):
                comp["catalogue_ref"] = c["catalogue_ref"]
            if c.get("calculation"):
                comp["calculation"] = c["calculation"]
            components.append(comp)

        numeric = [c for c in components if c["type"] == "numeric" and not c.get("unitless")]
        with_units = [c for c in numeric if c.get("suggested_units")]
        out.append({
            "id": tpl["id"],
            "name": tpl["name"],
            "description": tpl["description"],
            "version": version,
            "applies_to": tpl["applies_to"],
            "notice": notice,
            "components": components,
            "provenance": {
                "template_source": "curated",
                "units_source": UNITS_SOURCE,
                "reference_ranges": "not supplied; owned by the activating clinic",
                "critical_limits": "not supplied; owned by the activating clinic",
            },
            "completeness": {
                # Units are the only field this library can meaningfully supply,
                # so coverage of numeric components is the honest measure.
                "score": round(len(with_units) / len(numeric), 2) if numeric else 0.0,
                "components": len(components),
                "numeric_components": len(numeric),
                "with_suggested_units": len(with_units),
                "with_loinc": 0,
                "measured": sum(1 for c in components if c["entry_mode"] == "measured"),
                "calculated": sum(1 for c in components
                                  if c["entry_mode"] in ("calculated", "either")),
            },
        })
    return out, warnings


# --------------------------------------------------------------------------
# Components enumerated in the source's own notes column
# --------------------------------------------------------------------------

_INCLUDES = re.compile(r"(?:can include|includes)\s*:\s*(.+)", re.I)


def _split_markers(text: str) -> list[str]:
    """Split a marker list on commas that are not inside parentheses.

    "Ro (SS-A 52, SSA-60), La (SS-B), Sm" must yield three markers, not five.
    """
    parts, depth, current = [], 0, []
    for ch in text:
        if ch in "([":
            depth += 1
        elif ch in ")]":
            depth = max(0, depth - 1)
        if ch == "," and depth == 0:
            parts.append("".join(current))
            current = []
        else:
            current.append(ch)
    parts.append("".join(current))
    return [p.strip(" .;") for p in parts]


def derive_from_notes(test: dict, version: str, notice: str) -> dict | None:
    """Build a low-confidence template from a notes column that lists markers.

    Some panels publish their constituent markers as free text, e.g.
    "Can include: CD2, CD10, CD13, ...". These become coded components with no
    units, flagged as derived so a clinic reviews them before use.
    """
    # Only genuine panels. A test like "Antinuclear antibody (ANA)" mentions the
    # reflex ENA specificities in its notes, but those are not ANA's own result
    # fields -- ANA is reported as a result, titre and pattern.
    if "panel" not in test["name"].lower():
        return None

    note = test.get("notes") or ""
    m = _INCLUDES.search(note)
    if not m:
        return None
    markers = [p for p in _split_markers(m.group(1)) if p and len(p) <= 24]
    if len(markers) < 3:
        return None

    components = [{
        "id": re.sub(r"[^a-z0-9]+", "-", p.lower()).strip("-"),
        "name": p,
        "type": "coded",
        "entry_mode": "measured",
        "required": False,
    } for p in markers]
    # Deduplicate while preserving the published order.
    seen, unique = set(), []
    for c in components:
        if c["id"] and c["id"] not in seen:
            seen.add(c["id"])
            unique.append(c)

    return {
        "id": f"{test['id']}-derived",
        "name": test["name"],
        "description": f"Markers enumerated by the source for {test['name']}.",
        "version": version,
        "applies_to": [test["id"]],
        "notice": notice,
        "components": unique,
        "provenance": {
            "template_source": "derived-from-source-notes",
            "source_text": note,
            "confidence": "low",
            "reference_ranges": "not supplied; owned by the activating clinic",
            "critical_limits": "not supplied; owned by the activating clinic",
        },
        "completeness": {
            "score": 0.0,
            "components": len(unique),
            "numeric_components": 0,
            "with_suggested_units": 0,
            "with_loinc": 0,
            "measured": len(unique),
            "calculated": 0,
        },
    }


# --------------------------------------------------------------------------
# Shape templates assigned by rule
# --------------------------------------------------------------------------

def _name_blob(test: dict) -> str:
    return " | ".join([test["name"], *test.get("aliases", [])]).lower()


def _test_units(test: dict) -> str | None:
    units = (test.get("analysis") or {}).get("units") or (
        test.get("reference_intervals") or {}).get("units")
    return units if meaningful(units) else None


def pattern_matches(pattern: dict, test: dict) -> bool:
    """Evaluate a pattern's match block against a test.

    match_mode "all" (the default) requires every stated condition, so a
    Virology antibody rule cannot claim an Immunology autoantibody. "any"
    requires just one, for rules that should fire on either a department or a
    name cue.
    """
    m = pattern["match"]
    name = _name_blob(test)

    if any(x.lower() in name for x in m.get("exclude_name_any", [])):
        return False

    checks = []
    if "department_any" in m:
        checks.append(test["department"] in m["department_any"])
    if "name_any" in m:
        checks.append(any(x.lower() in name for x in m["name_any"]))
    if "has_units" in m:
        checks.append(bool(_test_units(test)) == m["has_units"])
    if "has_referred_to" in m:
        checks.append(bool(test.get("referred_to")) == m["has_referred_to"])

    if not checks:
        return False
    if pattern.get("match_mode") == "any":
        return any(checks)
    return all(checks)


def instantiate_pattern(pattern: dict, test: dict, version: str, notice: str) -> dict:
    """Build a concrete template for one test from a shape pattern."""
    units = _test_units(test)
    components = []
    for c in pattern["components"]:
        comp = {
            "id": c["id"],
            "name": test["name"] if c.get("name_from_test") else c["name"],
            "type": c["type"],
            "entry_mode": c.get("entry_mode", "measured"),
            "required": bool(c.get("required")),
        }
        if c.get("units_from_test") and units:
            comp["suggested_units"] = units
            comp["units_provenance"] = {"source": "test record"}
        elif c.get("suggested_units"):
            comp["suggested_units"] = c["suggested_units"]
        if c.get("suggested_values"):
            comp["suggested_values"] = c["suggested_values"]
        components.append(comp)

    numeric = [c for c in components if c["type"] == "numeric"]
    with_units = [c for c in numeric if c.get("suggested_units")]
    return {
        "id": f"{test['id']}--{pattern['id']}",
        "name": pattern["name"],
        "description": pattern["description"],
        "version": version,
        "applies_to": [test["id"]],
        "entry_style": pattern["entry_style"],
        "notice": notice,
        "components": components,
        "provenance": {
            "template_source": "pattern",
            "pattern": pattern["id"],
            "confidence": "low",
            "reference_ranges": "not supplied; owned by the activating clinic",
            "critical_limits": "not supplied; owned by the activating clinic",
        },
        "completeness": {
            "score": round(len(with_units) / len(numeric), 2) if numeric else 0.0,
            "components": len(components),
            "numeric_components": len(numeric),
            "with_suggested_units": len(with_units),
            "with_loinc": 0,
            "measured": sum(1 for c in components if c["entry_mode"] == "measured"),
            "calculated": sum(1 for c in components
                              if c["entry_mode"] in ("calculated", "either")),
        },
    }


def load_patterns() -> dict:
    return json.loads(PATTERNS.read_text(encoding="utf-8"))


def assign_pattern(test: dict, patterns: list[dict]) -> dict | None:
    """First matching pattern wins; rules are ordered most specific first."""
    for pattern in patterns:
        if pattern_matches(pattern, test):
            return pattern
    return None


# --------------------------------------------------------------------------
# Result-shape classification
# --------------------------------------------------------------------------

def classify_result_format(test: dict, template: dict | None,
                           pattern: dict | None) -> dict:
    """Describe how a result for this test should be captured.

    This is what tells a consuming system whether to render a structured entry
    form at all, and of what shape.
    """
    if pattern is not None:
        return {
            "kind": pattern["result_kind"],
            "structured_entry": bool(pattern["structured_entry"]),
            "entry_style": pattern["entry_style"],
            "basis": f"matched the {pattern['id']} shape rule",
        }
    if template is not None:
        return {"kind": "panel", "structured_entry": True, "entry_style": "fields",
                "basis": "a curated result template defines this test's components"}
    if test["department"] in NARRATIVE_DEPARTMENTS:
        return {"kind": "narrative", "structured_entry": False, "entry_style": "report",
                "basis": f"{test['department']} reports are written findings, not numeric fields"}
    if test.get("referred_to"):
        return {"kind": "document", "structured_entry": False, "entry_style": "document",
                "basis": "performed by a referral laboratory, which returns its own report"}
    return {"kind": "unstructured", "structured_entry": False,
            "basis": "no component definitions or units published for this test"}
