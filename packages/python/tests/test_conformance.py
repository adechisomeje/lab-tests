"""Run the shared conformance suite against the Python implementation.

The vectors in conformance/vectors.json are the contract every port must meet.
Expected values derive from the published source data, so passing cannot mean
merely agreeing with another port.
"""

from __future__ import annotations

import json
import pathlib
import sys

import pytest

ROOT = pathlib.Path(__file__).resolve().parents[3]
sys.path.insert(0, str(pathlib.Path(__file__).resolve().parents[1] / "src"))

import lab_tests as lt  # noqa: E402
from lab_tests.errors import LabTestsError  # noqa: E402

VECTORS = json.loads((ROOT / "conformance" / "vectors.json").read_text(encoding="utf-8"))


def code_of(fn) -> str:
    """Run fn and return the neutral error code it raised, or '' on success."""
    try:
        fn()
        return ""
    except LabTestsError as e:
        return e.code
    except Exception as e:  # noqa: BLE001
        return f"other:{type(e).__name__}: {e}"


def catalogue_for(spec: str, custom=None) -> lt.Catalogue:
    if spec == "custom":
        return lt.load(custom_ranges=custom or {})
    if spec.startswith("provider:"):
        return lt.load(provider_ranges=spec.split(":", 1)[1])
    return lt.load()


def patient_of(spec: dict | None) -> lt.Patient:
    spec = spec or {}
    age = spec.get("age")
    return lt.Patient(
        sex=spec.get("sex", ""),
        age=lt.Age(age["value"], age["unit"]) if age else None,
    )


def test_dataset_version_matches_vectors():
    assert lt.load().meta["version"] == VECTORS["dataset_version"]


@pytest.mark.parametrize("tc", VECTORS["fold"], ids=lambda tc: tc["in"])
def test_fold(tc):
    assert lt.fold(tc["in"]) == tc["out"]


@pytest.mark.parametrize("tc", VECTORS["classify"], ids=lambda tc: tc["name"])
def test_classify(tc):
    stratum = {
        "low": tc.get("low"),
        "high": tc.get("high"),
        "low_op": tc.get("low_op", ""),
        "high_op": tc.get("high_op", ""),
    }
    assert lt.classify(stratum, tc["value"]) == tc["expect"]


@pytest.mark.parametrize("tc", VECTORS["interpret"], ids=lambda tc: tc["name"][:60])
def test_interpret(tc):
    cat = catalogue_for(tc["ranges"], tc.get("custom_ranges"))
    patient = patient_of(tc.get("patient"))

    if tc.get("expect_error"):
        assert code_of(lambda: cat.interpret(tc["test_id"], tc["value"], patient)) == tc[
            "expect_error"
        ]
        return

    r = cat.interpret(tc["test_id"], tc["value"], patient)
    e = tc["expect"]
    if "flag" in e:
        assert r.flag == e["flag"]
    if "stratum_high" in e:
        assert r.stratum.get("high") == e["stratum_high"]
    if "stratum_low" in e:
        assert r.stratum.get("low") == e["stratum_low"]
    if "units" in e:
        assert r.units == e["units"]
    if e.get("warns"):
        assert r.warnings


@pytest.mark.parametrize("tc", VECTORS["draw"], ids=lambda tc: tc["name"][:60])
def test_draw(tc):
    cat = lt.load()
    if tc.get("expect_error"):
        assert code_of(lambda: cat.draw_for(tc["provider"], tc["test_ids"])) == tc[
            "expect_error"
        ]
        return

    plan = cat.draw_for(tc["provider"], tc["test_ids"])
    assert [t.type for t in plan.tubes] == tc["expect_tube_order"]
    assert [t.position for t in plan.tubes] == list(range(1, len(plan.tubes) + 1))
    assert len(plan.warnings) >= tc.get("expect_min_warnings", 0)
    assert len(plan.unresolved) == tc.get("expect_unresolved", 0)


@pytest.mark.parametrize("tc", VECTORS["search"], ids=lambda tc: tc["query"] or "(empty)")
def test_search(tc):
    cat = lt.load()
    got = cat.search(tc["query"], 10)
    if tc.get("expect_empty"):
        assert got == []
        return
    assert any(m.test["id"] == tc["expect_contains"] for m in got)
    if tc.get("expect_first"):
        assert got[0].test["id"] == tc["expect_first"]


@pytest.mark.parametrize("tc", VECTORS["order_set"], ids=lambda tc: tc["profile"])
def test_order_set(tc):
    cat = lt.load()
    if tc.get("expect_error"):
        assert code_of(lambda: cat.order_set(tc["profile"], tc["core_only"])) == tc[
            "expect_error"
        ]
        return
    assert len(cat.order_set(tc["profile"], tc["core_only"])) == tc["expect_count"]


@pytest.mark.parametrize("tc", VECTORS["result_format"], ids=lambda tc: tc["name"][:50])
def test_result_format(tc):
    cat = lt.load()
    if tc.get("coverage", {}).get("all_tests_have_format"):
        missing = [x["id"] for x in cat.tests() if not (x.get("result_format") or {}).get("kind")]
        assert not missing, f"tests without a result format: {missing[:3]}"
        return
    t = cat.get(tc["test_id"])
    assert t is not None, f"unknown test {tc['test_id']}"
    fmt = t.get("result_format") or {}
    assert fmt.get("kind") == tc["expect"]["kind"]
    assert fmt.get("structured_entry") == tc["expect"]["structured_entry"]


@pytest.mark.parametrize("tc", VECTORS["result_template"], ids=lambda tc: tc["name"][:50])
def test_result_template(tc):
    cat = lt.load()
    if tc.get("coverage", {}).get("all_tests_have_template"):
        missing = [x["id"] for x in cat.tests() if not x.get("result_template")]
        assert not missing, f"tests without a template: {missing[:3]}"
        return
    tpl = (
        cat.result_template(tc["test_id"])
        if tc.get("test_id")
        else cat.template(tc["template_id"])
    )

    if tc.get("expect_no_template"):
        assert tpl is None
        return

    assert tpl is not None
    e = tc["expect"]

    if "template_id" in e:
        assert tpl["id"] == e["template_id"]
    if "component_ids" in e:
        assert [c["id"] for c in tpl["components"]] == e["component_ids"]
    if "component_count" in e:
        assert len(tpl["components"]) == e["component_count"]
    if "completeness_score" in e:
        assert tpl["completeness"]["score"] == e["completeness_score"]
    if "applies_to" in e:
        assert tpl.get("applies_to", []) == e["applies_to"]
    if "template_source" in e:
        assert tpl["provenance"]["template_source"] == e["template_source"]
    if "confidence" in e:
        assert tpl["provenance"]["confidence"] == e["confidence"]
    if "entry_style" in e:
        assert tpl["entry_style"] == e["entry_style"]

    for cid, want in (e.get("components") or {}).items():
        comp = next((c for c in tpl["components"] if c["id"] == cid), None)
        assert comp is not None, f"component {cid} missing"
        for key, value in want.items():
            got = (comp.get("calculation") is not None) if key == "has_calculation" else comp.get(key)
            assert got == value, f"{cid}.{key}"

    # Templates must never assert reference ranges or critical limits: those
    # belong to the activating clinic, not a global library.
    for key in e.get("no_component_keys", []):
        for comp in tpl["components"]:
            assert key not in comp, f"{comp['id']} carries forbidden key {key}"
