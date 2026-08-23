package labtests

import (
	"errors"
	"fmt"
	"math"
	"strings"
)

var (
	// ErrNoRangeSource is returned by Interpret when the catalogue was loaded
	// without an explicit reference-range source. This is deliberate: reference
	// intervals are specific to a laboratory's analysers and population, and
	// silently applying another provider's intervals is a patient-safety error.
	ErrNoRangeSource = errors.New("labtests: no reference-range source configured; " +
		"load with WithProviderRanges or WithCustomRanges")

	// ErrUnknownTest is returned for an unrecognised test ID.
	ErrUnknownTest = errors.New("labtests: unknown test")

	// ErrNoIntervals is returned when a test carries no reference intervals.
	ErrNoIntervals = errors.New("labtests: no reference intervals for test")

	// ErrNoApplicableStratum is returned when intervals exist but none apply to
	// the given patient, e.g. a paediatric-only interval for an adult.
	ErrNoApplicableStratum = errors.New("labtests: no reference interval applies to this patient")
)

// Flag classifies a result against its reference interval.
type Flag string

const (
	FlagLow    Flag = "low"
	FlagNormal Flag = "normal"
	FlagHigh   Flag = "high"
)

// Age is a patient age with its unit. The zero value means "unknown", which
// restricts matching to strata that carry no age constraint.
type Age struct {
	Value float64
	Unit  AgeUnit
	Known bool
}

// Years, Months, Weeks and Days build an Age in the named unit.
func Years(v float64) Age  { return Age{Value: v, Unit: UnitYears, Known: true} }
func Months(v float64) Age { return Age{Value: v, Unit: UnitMonths, Known: true} }
func Weeks(v float64) Age  { return Age{Value: v, Unit: UnitWeeks, Known: true} }
func Days(v float64) Age   { return Age{Value: v, Unit: UnitDays, Known: true} }

// Patient carries the demographics that select a reference interval.
type Patient struct {
	Sex Sex
	Age Age
}

// Interpretation is the result of comparing a value to a reference interval.
type Interpretation struct {
	TestID string
	Value  float64
	Units  string
	Flag   Flag

	// Stratum is the age/sex band that was applied.
	Stratum Stratum
	// Attribution names where the interval came from, for display and audit.
	Attribution string
	// Warnings surface anything a clinical user should know before trusting
	// this result, such as an interval linked by fuzzy name matching.
	Warnings []string
}

// approximate days per unit; used only to compare a patient's age against
// interval bands, never to compute an exact age.
const (
	daysPerYear  = 365.25
	daysPerMonth = 30.4375
	daysPerWeek  = 7
)

func (a Age) days() (float64, bool) {
	if !a.Known {
		return 0, false
	}
	switch a.Unit {
	case UnitYears:
		return a.Value * daysPerYear, true
	case UnitMonths:
		return a.Value * daysPerMonth, true
	case UnitWeeks:
		return a.Value * daysPerWeek, true
	case UnitDays:
		return a.Value, true
	}
	return 0, false
}

// stratumUnitDays converts a stratum's declared age unit to days. Returns false
// when the unit is absent or ambiguous (the source contains a few entries like
// "months/ years"), in which case the band's age bounds are not applied.
func stratumUnitDays(unit string) (float64, bool) {
	switch strings.ToLower(strings.TrimSpace(unit)) {
	case "year", "years", "yr", "yrs", "y":
		return daysPerYear, true
	case "month", "months", "mth", "mths":
		return daysPerMonth, true
	case "week", "weeks", "wk", "wks":
		return daysPerWeek, true
	case "day", "days", "d":
		return 1, true
	}
	return 0, false
}

// exclusiveUpper reports whether a stratum's upper age bound is exclusive.
// The source writes both "<14" (exclusive) and "28" (inclusive).
func (s Stratum) exclusiveUpper() bool {
	if s.Raw == nil {
		return false
	}
	if v, ok := s.Raw["age_max"]; ok && v != nil {
		return strings.HasPrefix(strings.TrimSpace(*v), "<")
	}
	return false
}

// appliesTo reports whether a stratum covers this patient, and how specific the
// match is. Higher specificity wins when several strata apply.
func (s Stratum) appliesTo(p Patient) (ok bool, specificity float64) {
	// Sex
	switch s.Sex {
	case SexUnknown, SexAll:
		// applies to anyone
	default:
		if p.Sex == SexUnknown || p.Sex != s.Sex {
			return false, 0
		}
		specificity += 2
	}

	hasBand := s.AgeMin != nil || s.AgeMax != nil
	if !hasBand {
		// No age constraint: applies at any age.
		return true, specificity
	}
	unitDays, unitOK := stratumUnitDays(s.AgeUnit)
	if !unitOK {
		// The band has bounds but an uninterpretable unit (the source contains
		// a few entries like "days to years"). Refuse it rather than treat an
		// unverifiable band as universally applicable.
		return false, 0
	}

	ageDays, known := p.Age.days()
	if !known {
		// A banded interval cannot be safely applied to an unknown age.
		return false, 0
	}
	if s.AgeMin != nil && ageDays < *s.AgeMin*unitDays {
		return false, 0
	}
	if s.AgeMax != nil {
		hi := *s.AgeMax * unitDays
		if s.exclusiveUpper() {
			if ageDays >= hi {
				return false, 0
			}
		} else if ageDays > hi {
			return false, 0
		}
	}

	specificity++
	// Prefer the narrowest band that still fits.
	span := math.Inf(1)
	if s.AgeMin != nil && s.AgeMax != nil {
		span = (*s.AgeMax - *s.AgeMin) * unitDays
	}
	if !math.IsInf(span, 1) && span > 0 {
		specificity += 1 / (1 + span)
	}
	return true, specificity
}

// strataFor returns the intervals to use for a test under the configured
// range source, plus an attribution string and any warnings.
func (c *Catalogue) strataFor(t *Test) ([]Stratum, string, []string, error) {
	switch c.rangeMode {
	case rangesDisabled:
		return nil, "", nil, ErrNoRangeSource

	case rangesCustom:
		s, ok := c.customRanges[t.ID]
		if !ok || len(s) == 0 {
			return nil, "", nil, fmt.Errorf("%w: %s", ErrNoIntervals, t.ID)
		}
		return s, "local laboratory reference intervals", nil, nil

	case rangesProvider:
		ri := t.ReferenceIntervals
		if ri == nil || len(ri.Strata) == 0 {
			return nil, "", nil, fmt.Errorf("%w: %s", ErrNoIntervals, t.ID)
		}
		if t.Source.Provider != "" && t.Source.Provider != c.rangeProvider {
			return nil, "", nil, fmt.Errorf("%w: %s belongs to provider %q, not %q",
				ErrNoIntervals, t.ID, t.Source.Provider, c.rangeProvider)
		}
		var warnings []string
		if strings.HasPrefix(ri.MatchMethod, "fuzzy") {
			warnings = append(warnings, fmt.Sprintf(
				"reference interval was linked to this test by fuzzy name matching "+
					"(%s, source name %q); verify before clinical use",
				ri.MatchMethod, ri.MatchedName))
		}
		attribution := ri.Source
		if p, ok := c.providers[c.rangeProvider]; ok {
			attribution = p.Name
		}
		return ri.Strata, attribution, warnings, nil
	}
	return nil, "", nil, ErrNoRangeSource
}

// Interpret compares a numeric result against the applicable reference
// interval for a patient and returns a low/normal/high flag.
//
// It returns ErrNoRangeSource unless the catalogue was loaded with an explicit
// reference-range source. See the package documentation for why.
func (c *Catalogue) Interpret(testID string, value float64, p Patient) (*Interpretation, error) {
	t, ok := c.byID[testID]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownTest, testID)
	}
	strata, attribution, warnings, err := c.strataFor(t)
	if err != nil {
		return nil, err
	}

	best, bestScore, found := Stratum{}, math.Inf(-1), false
	for _, s := range strata {
		ok, score := s.appliesTo(p)
		if ok && score > bestScore {
			best, bestScore, found = s, score, true
		}
	}
	if !found {
		return nil, fmt.Errorf("%w: %s", ErrNoApplicableStratum, testID)
	}

	units := t.Analysis.Units
	if t.ReferenceIntervals != nil && t.ReferenceIntervals.Units != "" {
		units = t.ReferenceIntervals.Units
	}

	out := &Interpretation{
		TestID:      testID,
		Value:       value,
		Units:       units,
		Flag:        best.classify(value),
		Stratum:     best,
		Attribution: attribution,
		Warnings:    warnings,
	}
	if best.Low == nil && best.High == nil {
		out.Warnings = append(out.Warnings,
			"matched interval has no numeric bounds; flag is not meaningful")
	}
	return out, nil
}

// classify compares a value against this stratum's bounds, honouring the
// bound operators: "<= 50" and "< 50" differ at exactly 50.
func (s Stratum) classify(v float64) Flag {
	if s.High != nil {
		if s.HighOp == "lt" {
			if v >= *s.High {
				return FlagHigh
			}
		} else if v > *s.High {
			return FlagHigh
		}
	}
	if s.Low != nil {
		if s.LowOp == "gt" {
			if v <= *s.Low {
				return FlagLow
			}
		} else if v < *s.Low {
			return FlagLow
		}
	}
	return FlagNormal
}
