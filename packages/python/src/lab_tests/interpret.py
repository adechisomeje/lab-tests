"""Reference-interval resolution."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Literal, Sequence

from .errors import NoApplicableStratumError

Flag = Literal["low", "normal", "high"]
AgeUnit = Literal["days", "weeks", "months", "years"]

DAYS_PER_YEAR = 365.25
DAYS_PER_MONTH = 30.4375
DAYS_PER_WEEK = 7.0


@dataclass(frozen=True)
class Age:
    value: float
    unit: AgeUnit

    def in_days(self) -> float | None:
        if self.unit == "years":
            return self.value * DAYS_PER_YEAR
        if self.unit == "months":
            return self.value * DAYS_PER_MONTH
        if self.unit == "weeks":
            return self.value * DAYS_PER_WEEK
        if self.unit == "days":
            return self.value
        return None


def years(v: float) -> Age:
    return Age(v, "years")


def months(v: float) -> Age:
    return Age(v, "months")


def weeks(v: float) -> Age:
    return Age(v, "weeks")


def days(v: float) -> Age:
    return Age(v, "days")


@dataclass(frozen=True)
class Patient:
    sex: str = ""
    age: Age | None = None


@dataclass
class Interpretation:
    test_id: str
    value: float
    flag: Flag
    stratum: dict[str, Any]
    attribution: str
    units: str | None = None
    warnings: list[str] = field(default_factory=list)


def _stratum_unit_days(unit: str | None) -> float | None:
    """Days per unit, or None when the unit is absent or ambiguous.

    The source contains a few entries such as "days to years"; a band whose
    bounds cannot be interpreted must be refused, never applied.
    """
    u = (unit or "").strip().lower()
    if u in ("year", "years", "yr", "yrs", "y"):
        return DAYS_PER_YEAR
    if u in ("month", "months", "mth", "mths"):
        return DAYS_PER_MONTH
    if u in ("week", "weeks", "wk", "wks"):
        return DAYS_PER_WEEK
    if u in ("day", "days", "d"):
        return 1.0
    return None


def _exclusive_upper(s: dict[str, Any]) -> bool:
    """The source writes both "<14" (exclusive) and "28" (inclusive)."""
    raw = (s.get("raw") or {}).get("age_max")
    return isinstance(raw, str) and raw.strip().startswith("<")


def applies_to(s: dict[str, Any], p: Patient) -> tuple[bool, float]:
    """Whether a stratum covers this patient, and how specific the match is."""
    specificity = 0.0

    sex = s.get("sex") or ""
    if sex not in ("", "all"):
        if not p.sex or p.sex != sex:
            return False, 0.0
        specificity += 2

    age_min, age_max = s.get("age_min"), s.get("age_max")
    if age_min is None and age_max is None:
        return True, specificity

    unit_days = _stratum_unit_days(s.get("age_unit"))
    if unit_days is None:
        # Bounds we cannot interpret are never universally valid.
        return False, 0.0

    patient_days = p.age.in_days() if p.age else None
    if patient_days is None:
        return False, 0.0

    if age_min is not None and patient_days < age_min * unit_days:
        return False, 0.0
    if age_max is not None:
        hi = age_max * unit_days
        if patient_days >= hi if _exclusive_upper(s) else patient_days > hi:
            return False, 0.0

    specificity += 1
    if age_min is not None and age_max is not None:
        span = (age_max - age_min) * unit_days
        if span > 0:
            specificity += 1 / (1 + span)  # prefer the narrowest band
    return True, specificity


def classify(s: dict[str, Any], v: float) -> Flag:
    """Compare a value with a stratum's bounds, honouring bound operators.

    "<= 50" and "< 50" differ at exactly 50.
    """
    high = s.get("high")
    if high is not None:
        if (v >= high) if s.get("high_op") == "lt" else (v > high):
            return "high"
    low = s.get("low")
    if low is not None:
        if (v <= low) if s.get("low_op") == "gt" else (v < low):
            return "low"
    return "normal"


def select_stratum(strata: Sequence[dict[str, Any]], p: Patient) -> dict[str, Any]:
    """Select the most specific applicable stratum."""
    best: dict[str, Any] | None = None
    best_score = float("-inf")
    for s in strata:
        ok, score = applies_to(s, p)
        if ok and score > best_score:
            best, best_score = s, score
    if best is None:
        raise NoApplicableStratumError("no reference interval applies to this patient")
    return best
