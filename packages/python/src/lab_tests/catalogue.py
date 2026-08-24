"""The catalogue: loading, search, order sets, draw planning and interpretation."""

from __future__ import annotations

import json
import pathlib
from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

from .draw import DrawPlan, build_draw_plan
from .errors import (
    NoIntervalsError,
    NoRangeSourceError,
    UnknownCategoryError,
    UnknownProfileError,
    UnknownProviderError,
    UnknownTestError,
)
from .fold import fold
from .interpret import Interpretation, Patient, classify, select_stratum

_DATA_FILES = (
    "tests.json",
    "clinic-profiles.json",
    "categories.json",
    "providers.json",
    "result-templates.json",
)


def _resolve_data_dir(explicit: str | pathlib.Path | None = None) -> pathlib.Path:
    if explicit:
        return pathlib.Path(explicit)
    here = pathlib.Path(__file__).resolve().parent
    # Packaged layout first, then walk up for the development checkout.
    candidates = [here / "data", *(parent / "data" for parent in here.parents)]
    for c in candidates:
        if (c / "tests.json").exists():
            return c
    raise FileNotFoundError(
        "lab-tests: could not locate the dataset; pass data_dir to load()"
    )


@dataclass(frozen=True)
class Match:
    test: dict[str, Any]
    score: float


class Catalogue:
    """An immutable, in-memory view of the dataset."""

    def __init__(
        self,
        data_dir: str | pathlib.Path | None = None,
        *,
        provider_ranges: str | None = None,
        custom_ranges: Mapping[str, Sequence[dict[str, Any]]] | None = None,
    ) -> None:
        d = _resolve_data_dir(data_dir)
        docs = {f: json.loads((d / f).read_text(encoding="utf-8")) for f in _DATA_FILES}

        self.meta: dict[str, Any] = docs["tests.json"]["meta"]
        self._tests: list[dict[str, Any]] = docs["tests.json"]["tests"]
        self._by_id = {t["id"]: t for t in self._tests}
        self._profiles = {p["id"]: p for p in docs["clinic-profiles.json"]["profiles"]}
        self._categories = {c["id"]: c for c in docs["categories.json"]["categories"]}
        self._providers = {p["id"]: p for p in docs["providers.json"]["providers"]}
        self._templates = {
            t["id"]: t for t in docs["result-templates.json"]["templates"]
        }

        self._haystack = {
            t["id"]: fold(" ".join([t["name"], *t.get("aliases", [])])) for t in self._tests
        }

        if provider_ranges is not None and custom_ranges is not None:
            raise ValueError("pass either provider_ranges or custom_ranges, not both")
        if provider_ranges is not None and provider_ranges not in self._providers:
            raise UnknownProviderError(f"unknown provider: {provider_ranges}")
        self._provider_ranges = provider_ranges
        self._custom_ranges = dict(custom_ranges) if custom_ranges is not None else None

    # -- catalogue -------------------------------------------------------

    def tests(self) -> list[dict[str, Any]]:
        return list(self._tests)

    def get(self, test_id: str) -> dict[str, Any] | None:
        return self._by_id.get(test_id)

    def provider(self, provider_id: str) -> dict[str, Any] | None:
        return self._providers.get(provider_id)

    def profile(self, profile_id: str) -> dict[str, Any] | None:
        return self._profiles.get(profile_id)

    def profiles(self) -> list[dict[str, Any]]:
        return sorted(self._profiles.values(), key=lambda p: p["id"])

    def order_set(self, profile_id: str, core_only: bool = False) -> list[dict[str, Any]]:
        """Tests a clinic profile covers.

        ``core_only`` returns the curated panel, which is what an order set
        should default to; the full list is browse-and-discover breadth.
        """
        p = self._profiles.get(profile_id)
        if p is None:
            raise UnknownProfileError(f"unknown clinic profile: {profile_id}")
        ids = p["core_test_ids"] if core_only else p["test_ids"]
        return [self._by_id[i] for i in ids if i in self._by_id]

    def by_category(self, category_id: str) -> list[dict[str, Any]]:
        c = self._categories.get(category_id)
        if c is None:
            raise UnknownCategoryError(f"unknown category: {category_id}")
        return [self._by_id[i] for i in c["test_ids"] if i in self._by_id]

    def search(self, query: str, limit: int = 0) -> list[Match]:
        """Find tests by name or alias, case- and accent-insensitively."""
        q = fold(query)
        if not q:
            return []
        out: list[Match] = []
        for t in self._tests:
            name = fold(t["name"])
            score = 0.0
            if name == q:
                score = 1.0
            elif name.startswith(q):
                score = 0.9
            else:
                for a in t.get("aliases", []):
                    fa = fold(a)
                    if fa == q:
                        score = 0.85
                        break
                    if fa.startswith(q):
                        score = 0.75
                if score == 0 and q in self._haystack[t["id"]]:
                    score = 0.5 - len(name) / 10000
            if score > 0:
                out.append(Match(test=t, score=score))
        out.sort(key=lambda m: (-m.score, m.test["name"]))
        return out[:limit] if limit > 0 else out

    def result_template(self, test_id: str) -> dict[str, Any] | None:
        """The starter template seeding structured result entry for a test.

        A starting point, not a specification: copy it into your own catalogue,
        confirm every component and unit against your analyser, and treat your
        versioned copy as authoritative. Check ``test["result_format"]`` first --
        narrative and document results should not be captured as fields at all.
        """
        t = self._by_id.get(test_id)
        return (t or {}).get("result_template")

    def template(self, template_id: str) -> dict[str, Any] | None:
        """A starter template by its own id.

        Some templates, such as ``urea-and-electrolytes``, are reusable starting
        points with no matching test in this catalogue.
        """
        return self._templates.get(template_id)

    def templates(self) -> list[dict[str, Any]]:
        """Every starter template, ordered by id."""
        return sorted(self._templates.values(), key=lambda t: t["id"])

    def turnaround(self, test_id: str) -> dict[str, float] | None:
        t = self._by_id.get(test_id)
        if t is None:
            raise UnknownTestError(f"unknown test: {test_id}")
        ta = t.get("turnaround") or {}
        return ta.get("final_working_days") or ta.get("days")

    # -- phlebotomy ------------------------------------------------------

    def draw(self, test_ids: Iterable[str]) -> DrawPlan:
        provider_id = self._provider_ranges
        if provider_id is None:
            if len(self._providers) != 1:
                raise UnknownProviderError("no provider selected for order of draw")
            provider_id = next(iter(self._providers))
        return self.draw_for(provider_id, test_ids)

    def draw_for(self, provider_id: str, test_ids: Iterable[str]) -> DrawPlan:
        """Draw plan using a named provider's order of draw.

        Order of draw is provider-specific and published sequences disagree, so
        the plan names the provider, quotes the source, and warns where the rule
        conflicts with CLSI or omits a tube. Follow your own laboratory's SOP.
        """
        prov = self._providers.get(provider_id)
        if prov is None:
            raise UnknownProviderError(f"unknown provider: {provider_id}")
        resolved = []
        for tid in test_ids:
            t = self._by_id.get(tid)
            if t is None:
                raise UnknownTestError(f"unknown test: {tid}")
            resolved.append(t)
        return build_draw_plan(prov, resolved)

    # -- interpretation --------------------------------------------------

    def _strata_for(self, t: dict[str, Any]) -> tuple[list[dict[str, Any]], str, list[str]]:
        if self._custom_ranges is not None:
            s = self._custom_ranges.get(t["id"])
            if not s:
                raise NoIntervalsError(f"no reference intervals for {t['id']}")
            return list(s), "local laboratory reference intervals", []

        if self._provider_ranges is None:
            raise NoRangeSourceError(
                "no reference-range source configured; load with provider_ranges "
                "or custom_ranges"
            )

        ri = t.get("reference_intervals") or {}
        strata = ri.get("strata") or []
        if not strata:
            raise NoIntervalsError(f"no reference intervals for {t['id']}")
        src_provider = (t.get("source") or {}).get("provider")
        if src_provider and src_provider != self._provider_ranges:
            raise NoIntervalsError(f"{t['id']} belongs to provider {src_provider}")

        warnings: list[str] = []
        if str(ri.get("match_method", "")).startswith("fuzzy"):
            warnings.append(
                "reference interval was linked to this test by fuzzy name matching "
                f"({ri['match_method']}, source name {ri.get('matched_name')!r}); "
                "verify before clinical use"
            )
        prov = self._providers.get(self._provider_ranges) or {}
        return strata, prov.get("name") or ri.get("source", ""), warnings

    def interpret(self, test_id: str, value: float, patient: Patient) -> Interpretation:
        """Compare a result with the applicable reference interval.

        Raises :class:`NoRangeSourceError` unless a range source was chosen at
        construction: applying one laboratory's intervals to another's analysers
        and population is a patient-safety error, so it is never the default.
        """
        t = self._by_id.get(test_id)
        if t is None:
            raise UnknownTestError(f"unknown test: {test_id}")

        strata, attribution, warnings = self._strata_for(t)
        stratum = select_stratum(strata, patient)

        units = (t.get("reference_intervals") or {}).get("units") or (
            t.get("analysis") or {}
        ).get("units")
        out = Interpretation(
            test_id=test_id,
            value=value,
            flag=classify(stratum, value),
            stratum=stratum,
            attribution=attribution,
            units=units,
            warnings=list(warnings),
        )
        if stratum.get("low") is None and stratum.get("high") is None:
            out.warnings.append(
                "matched interval has no numeric bounds; flag is not meaningful"
            )
        return out


def load(
    data_dir: str | pathlib.Path | None = None,
    *,
    provider_ranges: str | None = None,
    custom_ranges: Mapping[str, Sequence[dict[str, Any]]] | None = None,
) -> Catalogue:
    """Load the catalogue.

    Reference-interval interpretation is opt-in::

        load()                                   # catalogue only
        load(provider_ranges="mft-nhs")          # accept the provider's intervals
        load(custom_ranges=my_lab_ranges)        # production
    """
    return Catalogue(data_dir, provider_ranges=provider_ranges, custom_ranges=custom_ranges)
