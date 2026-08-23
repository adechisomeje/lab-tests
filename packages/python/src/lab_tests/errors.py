"""Errors, keyed by the language-neutral codes used in conformance/vectors.json."""

from __future__ import annotations


class LabTestsError(Exception):
    """Base error. ``code`` matches the conformance suite's neutral names."""

    code = "error"

    def __init__(self, message: str) -> None:
        super().__init__(message)


class NoRangeSourceError(LabTestsError):
    code = "no_range_source"


class UnknownTestError(LabTestsError):
    code = "unknown_test"


class NoIntervalsError(LabTestsError):
    code = "no_intervals"


class NoApplicableStratumError(LabTestsError):
    code = "no_applicable_stratum"


class UnknownProfileError(LabTestsError):
    code = "unknown_profile"


class UnknownProviderError(LabTestsError):
    code = "unknown_provider"


class UnknownCategoryError(LabTestsError):
    code = "unknown_category"
