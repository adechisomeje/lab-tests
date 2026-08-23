"""Validate the built dataset: JSON Schema conformance plus referential integrity.

Exits non-zero on any error, so it can gate CI.
"""
import collections
import json
import pathlib
import sys

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TAX = ROOT / "taxonomy"

errors: list[str] = []
warnings: list[str] = []


def load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


def main() -> int:
    tests = load(DATA / "tests.json")["tests"]
    schema = load(ROOT / "schema" / "test.schema.json")
    categories = {c["id"] for c in load(TAX / "categories.json")["categories"]}
    profiles = {p["id"] for p in load(TAX / "clinic-profiles.json")["profiles"]}

    # --- schema conformance -------------------------------------------------
    try:
        from jsonschema import Draft202012Validator
        v = Draft202012Validator(schema)
        for t in tests:
            for e in v.iter_errors(t):
                path = "/".join(str(x) for x in e.path)
                errors.append(f"[schema] {t.get('id','?')}: {path}: {e.message}")
    except ImportError:
        warnings.append("jsonschema not installed - skipped schema validation "
                        "(pip install jsonschema)")

    # --- referential integrity ---------------------------------------------
    ids = [t["id"] for t in tests]
    for dup, n in collections.Counter(ids).items():
        if n > 1:
            errors.append(f"[ids] duplicate id {dup!r} ({n}x)")

    id_set = set(ids)
    for t in tests:
        for c in t.get("categories", []):
            if c not in categories:
                errors.append(f"[categories] {t['id']}: unknown category {c!r}")
        for entry in t.get("clinic_profiles", []):
            if entry["profile"] not in profiles:
                errors.append(f"[profiles] {t['id']}: unknown profile {entry['profile']!r}")

    # --- roll-ups agree with tests.json -------------------------------------
    for fname, key, listkey in [
        ("categories.json", "categories", "test_ids"),
        ("clinic-profiles.json", "profiles", "test_ids"),
        ("departments.json", "departments", "test_ids"),
        ("specimens.json", "specimens", "test_ids"),
    ]:
        for group in load(DATA / fname)[key]:
            missing = [i for i in group[listkey] if i not in id_set]
            if missing:
                errors.append(f"[{fname}] {group['id']}: {len(missing)} unknown test ids "
                              f"(e.g. {missing[:3]})")
            if group.get("test_count") is not None and group["test_count"] != len(group[listkey]):
                errors.append(f"[{fname}] {group['id']}: test_count disagrees with test_ids")

    idx = load(DATA / "index.json")["tests"]
    if {t["id"] for t in idx} != id_set:
        errors.append("[index] index.json ids do not match tests.json")

    # --- soft quality signals ----------------------------------------------
    no_cat = [t["id"] for t in tests if not t.get("categories")]
    if no_cat:
        warnings.append(f"{len(no_cat)} tests have no category (e.g. {no_cat[:3]})")
    thin = [t for t in tests if t.get("completeness", {}).get("score", 0) == 0]
    if thin:
        warnings.append(f"{len(thin)} tests carry no requirement detail at all")

    # --- report -------------------------------------------------------------
    print(f"validated {len(tests)} tests")
    for w in warnings:
        print(f"  WARN  {w}")
    for e in errors[:40]:
        print(f"  ERROR {e}")
    if len(errors) > 40:
        print(f"  ... and {len(errors)-40} more errors")
    print(f"\n{len(errors)} error(s), {len(warnings)} warning(s)")
    return 1 if errors else 0


if __name__ == "__main__":
    sys.exit(main())
