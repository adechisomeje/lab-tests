"""Validate the built dataset: JSON Schema conformance plus referential integrity.

Exits non-zero on any error, so it can gate CI.
"""
import collections
import json
import pathlib
import subprocess
import sys
import unicodedata

ROOT = pathlib.Path(__file__).resolve().parent.parent
DATA = ROOT / "data"
TAX = ROOT / "taxonomy"

errors: list[str] = []
warnings: list[str] = []


def load(p: pathlib.Path):
    return json.loads(p.read_text(encoding="utf-8"))


# Mirrors golang.org/x/mod/module.fileNameOK. Go's module zip format rejects
# any non-ASCII rune that is not a Unicode letter, so a single U+2010 HYPHEN in
# a filename makes the whole Go module unpublishable -- and the failure only
# shows up at `go get` time, long after the commit that caused it.
_GO_ASCII_ALLOWED = set("!#$%&()+,-.=@[]^_{}~ ")


def _go_char_ok(ch: str) -> bool:
    if ord(ch) < 0x80:
        return ch.isascii() and (ch.isalnum() or ch in _GO_ASCII_ALLOWED)
    return unicodedata.category(ch).startswith("L")


def check_module_safe_paths() -> None:
    """Every tracked path must be legal inside a Go module zip."""
    try:
        out = subprocess.run(["git", "ls-files", "-z"], cwd=ROOT,
                             capture_output=True, check=True).stdout
    except (OSError, subprocess.CalledProcessError):
        warnings.append("git unavailable - skipped Go module path check")
        return

    for raw in out.split(b"\0"):
        if not raw:
            continue
        path = raw.decode("utf-8", "surrogateescape")
        for element in path.split("/"):
            if not element or element.strip(".") == "" or element.endswith("."):
                errors.append(f"[paths] {path}: invalid path element {element!r}")
                break
            bad = [c for c in element if not _go_char_ok(c)]
            if bad:
                shown = ", ".join(
                    f"U+{ord(c):04X} {unicodedata.name(c, '?')}" for c in dict.fromkeys(bad))
                errors.append(
                    f"[paths] {path}: character(s) rejected by Go's module zip "
                    f"format: {shown}")
                break


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

    # --- packaging ----------------------------------------------------------
    check_module_safe_paths()

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
