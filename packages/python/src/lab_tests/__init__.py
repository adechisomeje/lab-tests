"""Medical laboratory test catalogue with specimen requirements and reference intervals."""

from .catalogue import Catalogue, Match, load
from .draw import DrawPlan, DrawTube
from .errors import (
    LabTestsError,
    NoApplicableStratumError,
    NoIntervalsError,
    NoRangeSourceError,
    UnknownCategoryError,
    UnknownProfileError,
    UnknownProviderError,
    UnknownTestError,
)
from .fold import fold
from .interpret import (
    Age,
    Interpretation,
    Patient,
    applies_to,
    classify,
    days,
    months,
    select_stratum,
    weeks,
    years,
)

__version__ = "0.1.0"

__all__ = [
    "Age", "Catalogue", "DrawPlan", "DrawTube", "Interpretation", "LabTestsError",
    "Match", "NoApplicableStratumError", "NoIntervalsError", "NoRangeSourceError",
    "Patient", "UnknownCategoryError", "UnknownProfileError", "UnknownProviderError",
    "UnknownTestError", "applies_to", "classify", "days", "fold", "load", "months",
    "select_stratum", "weeks", "years",
]
