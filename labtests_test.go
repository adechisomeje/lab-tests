package labtests

import (
	"errors"
	"testing"
)

func load(t *testing.T, opts ...Option) *Catalogue {
	t.Helper()
	c, err := Load(opts...)
	if err != nil {
		t.Fatalf("Load: %v", err)
	}
	return c
}

func TestLoadEmbedded(t *testing.T) {
	c := load(t)
	if got := len(c.Tests()); got < 500 {
		t.Errorf("expected >=500 tests, got %d", got)
	}
	if c.Meta().Disclaimer == "" {
		t.Error("meta disclaimer must be present for clinical display")
	}
	if _, ok := c.Get("alanine-aminotransferase"); !ok {
		t.Error("expected alanine-aminotransferase in catalogue")
	}
}

func TestSearch(t *testing.T) {
	c := load(t)
	for _, tc := range []struct{ query, wantID string }{
		{"ferritin", "ferritin"},
		{"Ferritin", "ferritin"},
		{"mullerian", "anti-mullerian-hormone-amh"}, // accent-insensitive
		{"Anti-Müllerian", "anti-mullerian-hormone-amh"},
	} {
		got := c.Search(tc.query, 5)
		if len(got) == 0 {
			t.Errorf("Search(%q): no results", tc.query)
			continue
		}
		found := false
		for _, m := range got {
			if m.Test.ID == tc.wantID {
				found = true
			}
		}
		if !found {
			t.Errorf("Search(%q): want %s in results, got %s",
				tc.query, tc.wantID, got[0].Test.ID)
		}
	}
	if got := c.Search("", 5); got != nil {
		t.Error("empty query should return nil")
	}
}

func TestOrderSet(t *testing.T) {
	c := load(t)
	core, err := c.OrderSet("aesthetic-beauty-clinic", true)
	if err != nil {
		t.Fatal(err)
	}
	all, err := c.OrderSet("aesthetic-beauty-clinic", false)
	if err != nil {
		t.Fatal(err)
	}
	if len(core) == 0 || len(core) >= len(all) {
		t.Errorf("core set (%d) should be non-empty and smaller than full set (%d)",
			len(core), len(all))
	}
	if _, err := c.OrderSet("no-such-clinic", true); err == nil {
		t.Error("expected error for unknown profile")
	}
}

// Interpretation must be opt-in: applying another laboratory's reference
// intervals by default would be a patient-safety error.
func TestInterpretRequiresExplicitRangeSource(t *testing.T) {
	c := load(t)
	_, err := c.Interpret("alanine-aminotransferase", 62, Patient{Sex: SexMale, Age: Years(34)})
	if !errors.Is(err, ErrNoRangeSource) {
		t.Fatalf("want ErrNoRangeSource, got %v", err)
	}
}

func TestInterpretALT(t *testing.T) {
	c := load(t, WithProviderRanges("mft-nhs"))
	// Published MFT intervals for ALT:
	//   all sexes, 0-28 days  : <= 90 IU/L
	//   female, 29 days+      : <= 35 IU/L
	//   male,   29 days+      : <= 50 IU/L
	cases := []struct {
		name    string
		value   float64
		patient Patient
		want    Flag
	}{
		{"adult male normal", 45, Patient{SexMale, Years(34)}, FlagNormal},
		{"adult male high", 62, Patient{SexMale, Years(34)}, FlagHigh},
		{"adult male at limit is normal", 50, Patient{SexMale, Years(34)}, FlagNormal},
		{"adult female high at 40", 40, Patient{SexFemale, Years(34)}, FlagHigh},
		{"adult female normal at 30", 30, Patient{SexFemale, Years(34)}, FlagNormal},
		{"neonate uses wider band", 85, Patient{SexMale, Days(10)}, FlagNormal},
		{"neonate high", 95, Patient{SexMale, Days(10)}, FlagHigh},
	}
	for _, tc := range cases {
		t.Run(tc.name, func(t *testing.T) {
			got, err := c.Interpret("alanine-aminotransferase", tc.value, tc.patient)
			if err != nil {
				t.Fatalf("Interpret: %v", err)
			}
			if got.Flag != tc.want {
				t.Errorf("value %v %v: got %s, want %s (stratum high=%v)",
					tc.value, tc.patient.Sex, got.Flag, tc.want, deref(got.Stratum.High))
			}
			if got.Units != "IU/L" {
				t.Errorf("units: got %q want IU/L", got.Units)
			}
		})
	}
}

// Sex-specific bands must not be applied when the patient's sex is unknown.
func TestInterpretUnknownSexRejectsSexSpecificBand(t *testing.T) {
	c := load(t, WithProviderRanges("mft-nhs"))
	_, err := c.Interpret("alanine-aminotransferase", 45,
		Patient{Sex: SexUnknown, Age: Years(34)})
	if !errors.Is(err, ErrNoApplicableStratum) {
		t.Errorf("want ErrNoApplicableStratum for unknown sex, got %v", err)
	}
}

// A banded interval cannot be applied to a patient of unknown age.
func TestInterpretUnknownAgeRejectsBandedInterval(t *testing.T) {
	c := load(t, WithProviderRanges("mft-nhs"))
	_, err := c.Interpret("alanine-aminotransferase", 45, Patient{Sex: SexMale})
	if !errors.Is(err, ErrNoApplicableStratum) {
		t.Errorf("want ErrNoApplicableStratum for unknown age, got %v", err)
	}
}

func TestInterpretPicksNarrowestBand(t *testing.T) {
	c := load(t, WithProviderRanges("mft-nhs"))
	// Ferritin: male 0-5y is 12-400, male 5-120y is 15-400.
	got, err := c.Interpret("ferritin", 13, Patient{SexMale, Years(3)})
	if err != nil {
		t.Fatal(err)
	}
	if got.Flag != FlagNormal {
		t.Errorf("3y male ferritin 13: got %s, want normal (lower limit 12)", got.Flag)
	}
	got, err = c.Interpret("ferritin", 13, Patient{SexMale, Years(30)})
	if err != nil {
		t.Fatal(err)
	}
	if got.Flag != FlagLow {
		t.Errorf("30y male ferritin 13: got %s, want low (lower limit 15)", got.Flag)
	}
}

// Intervals linked by fuzzy name matching must warn.
func TestInterpretWarnsOnFuzzyLink(t *testing.T) {
	c := load(t, WithProviderRanges("mft-nhs"))
	got, err := c.Interpret("albumin-creatinine-ratio-acr", 5, Patient{SexMale, Years(40)})
	if err != nil {
		if errors.Is(err, ErrNoApplicableStratum) {
			t.Skip("no applicable stratum for this fixture")
		}
		t.Fatal(err)
	}
	if len(got.Warnings) == 0 {
		t.Error("expected a warning for a fuzzy-linked reference interval")
	}
}

func TestInterpretCustomRangesOverrideProvider(t *testing.T) {
	high := 10.0
	c := load(t, WithCustomRanges(map[string][]Stratum{
		"ferritin": {{Sex: SexAll, High: &high}},
	}))
	got, err := c.Interpret("ferritin", 20, Patient{SexMale, Years(30)})
	if err != nil {
		t.Fatal(err)
	}
	if got.Flag != FlagHigh {
		t.Errorf("custom range should flag 20 as high, got %s", got.Flag)
	}
	// A test absent from the custom map must not silently fall back.
	if _, err := c.Interpret("alanine-aminotransferase", 45,
		Patient{SexMale, Years(30)}); !errors.Is(err, ErrNoIntervals) {
		t.Errorf("want ErrNoIntervals for test absent from custom ranges, got %v", err)
	}
}

func TestBoundOperators(t *testing.T) {
	fifty := 50.0
	for _, tc := range []struct {
		name  string
		s     Stratum
		value float64
		want  Flag
	}{
		{"lte at limit", Stratum{High: &fifty, HighOp: "lte"}, 50, FlagNormal},
		{"lte above", Stratum{High: &fifty, HighOp: "lte"}, 50.1, FlagHigh},
		{"lt at limit", Stratum{High: &fifty, HighOp: "lt"}, 50, FlagHigh},
		{"gte low at limit", Stratum{Low: &fifty}, 50, FlagNormal},
		{"below low", Stratum{Low: &fifty}, 49.9, FlagLow},
		{"gt low at limit", Stratum{Low: &fifty, LowOp: "gt"}, 50, FlagLow},
	} {
		if got := tc.s.classify(tc.value); got != tc.want {
			t.Errorf("%s: got %s want %s", tc.name, got, tc.want)
		}
	}
}

func TestDrawPlanOrdersTubes(t *testing.T) {
	c := load(t)
	// lactate = fluoride-oxalate, ammonia = EDTA, ferritin = serum gel.
	// MFT order: serum -> lithium heparin -> fluoride -> EDTA last.
	plan, err := c.Draw([]string{"ammonia", "lactate", "ferritin"})
	if err != nil {
		t.Fatal(err)
	}
	if len(plan.Tubes) != 3 {
		t.Fatalf("expected 3 tubes, got %d", len(plan.Tubes))
	}
	want := []TubeType{TubeSerumGel, TubeFluorideOxalate, TubeEDTA}
	for i, w := range want {
		if plan.Tubes[i].Type != w {
			t.Errorf("position %d: got %s want %s", i+1, plan.Tubes[i].Type, w)
		}
		if plan.Tubes[i].Position != i+1 {
			t.Errorf("position field not set correctly at %d", i)
		}
	}
	if plan.OrderSource == "" {
		t.Error("plan should cite the published order-of-draw statement")
	}
	if len(plan.Warnings) == 0 {
		t.Error("multi-tube plan should warn about the CLSI conflict")
	}
}

func TestDrawPlanReportsUnresolvedTests(t *testing.T) {
	c := load(t)
	// Full blood count publishes no tube requirement in this dataset.
	plan, err := c.Draw([]string{"full-blood-count-and-automated-differential", "ferritin"})
	if err != nil {
		t.Fatal(err)
	}
	if len(plan.Unresolved) != 1 {
		t.Errorf("expected 1 unresolved test, got %d", len(plan.Unresolved))
	}
	if _, err := c.Draw([]string{"nope"}); !errors.Is(err, ErrUnknownTest) {
		t.Errorf("want ErrUnknownTest, got %v", err)
	}
}

func TestTurnaround(t *testing.T) {
	c := load(t)
	d, err := c.Turnaround("alanine-aminotransferase")
	if err != nil {
		t.Fatal(err)
	}
	if d.Max <= 0 {
		t.Errorf("expected positive turnaround, got %v", d.Max)
	}
	worst, unknown, err := c.SlowestTurnaround(
		[]string{"alanine-aminotransferase", "ferritin"})
	if err != nil {
		t.Fatal(err)
	}
	if worst == nil {
		t.Error("expected a slowest turnaround")
	}
	_ = unknown
}

func deref(f *float64) any {
	if f == nil {
		return nil
	}
	return *f
}
