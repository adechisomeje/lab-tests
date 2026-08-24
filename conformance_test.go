package labtests

import (
	"encoding/json"
	"errors"
	"fmt"
	"os"
	"strings"
	"testing"
)

// The conformance suite is the shared contract between every port of this
// library. Expected values come from the published source data, so a port
// cannot pass merely by agreeing with another port's bug.

type vectors struct {
	Version        string `json:"version"`
	DatasetVersion string `json:"dataset_version"`
	Fold           []struct {
		In  string `json:"in"`
		Out string `json:"out"`
	} `json:"fold"`
	Classify []struct {
		Name   string   `json:"name"`
		Low    *float64 `json:"low"`
		High   *float64 `json:"high"`
		LowOp  string   `json:"low_op"`
		HighOp string   `json:"high_op"`
		Value  float64  `json:"value"`
		Expect string   `json:"expect"`
	} `json:"classify"`
	Interpret []struct {
		Name         string               `json:"name"`
		Ranges       string               `json:"ranges"`
		CustomRanges map[string][]Stratum `json:"custom_ranges"`
		TestID       string               `json:"test_id"`
		Value        float64              `json:"value"`
		Patient      vecPatient           `json:"patient"`
		Expect       *vecExpect           `json:"expect"`
		ExpectError  string               `json:"expect_error"`
	} `json:"interpret"`
	Draw []struct {
		Name             string   `json:"name"`
		Provider         string   `json:"provider"`
		TestIDs          []string `json:"test_ids"`
		ExpectTubeOrder  []string `json:"expect_tube_order"`
		ExpectMinWarn    int      `json:"expect_min_warnings"`
		ExpectUnresolved int      `json:"expect_unresolved"`
		ExpectError      string   `json:"expect_error"`
	} `json:"draw"`
	Search []struct {
		Query          string `json:"query"`
		ExpectContains string `json:"expect_contains"`
		ExpectFirst    string `json:"expect_first"`
		ExpectEmpty    bool   `json:"expect_empty"`
	} `json:"search"`
	ResultFormat []struct {
		Name   string `json:"name"`
		TestID string `json:"test_id"`
		Expect struct {
			Kind            string `json:"kind"`
			StructuredEntry bool   `json:"structured_entry"`
		} `json:"expect"`
	} `json:"result_format"`
	ResultTemplate []struct {
		Name             string `json:"name"`
		TestID           string `json:"test_id"`
		TemplateID       string `json:"template_id"`
		ExpectNoTemplate bool   `json:"expect_no_template"`
		Expect           struct {
			TemplateID        string                    `json:"template_id"`
			ComponentIDs      []string                  `json:"component_ids"`
			ComponentCount    int                       `json:"component_count"`
			CompletenessScore *float64                  `json:"completeness_score"`
			AppliesTo         []string                  `json:"applies_to"`
			TemplateSource    string                    `json:"template_source"`
			NoComponentKeys   []string                  `json:"no_component_keys"`
			Components        map[string]map[string]any `json:"components"`
		} `json:"expect"`
	} `json:"result_template"`
	OrderSet []struct {
		Profile     string `json:"profile"`
		CoreOnly    bool   `json:"core_only"`
		ExpectCount int    `json:"expect_count"`
		ExpectError string `json:"expect_error"`
	} `json:"order_set"`
}

type vecPatient struct {
	Sex string `json:"sex"`
	Age *struct {
		Value float64 `json:"value"`
		Unit  string  `json:"unit"`
	} `json:"age"`
}

func (v vecPatient) toPatient() Patient {
	p := Patient{Sex: Sex(v.Sex)}
	if v.Age != nil {
		p.Age = Age{Value: v.Age.Value, Unit: AgeUnit(v.Age.Unit), Known: true}
	}
	return p
}

type vecExpect struct {
	Flag        string   `json:"flag"`
	StratumLow  *float64 `json:"stratum_low"`
	StratumHigh *float64 `json:"stratum_high"`
	Units       string   `json:"units"`
	Warns       bool     `json:"warns"`
}

// errCode maps a Go error to the suite's language-neutral code.
func errCode(err error) string {
	switch {
	case err == nil:
		return ""
	case errors.Is(err, ErrNoRangeSource):
		return "no_range_source"
	case errors.Is(err, ErrUnknownTest):
		return "unknown_test"
	case errors.Is(err, ErrNoIntervals):
		return "no_intervals"
	case errors.Is(err, ErrNoApplicableStratum):
		return "no_applicable_stratum"
	}
	return "other:" + err.Error()
}

func loadVectors(t *testing.T) vectors {
	t.Helper()
	b, err := os.ReadFile("conformance/vectors.json")
	if err != nil {
		t.Fatalf("reading vectors: %v", err)
	}
	var v vectors
	if err := json.Unmarshal(b, &v); err != nil {
		t.Fatalf("parsing vectors: %v", err)
	}
	return v
}

func TestConformanceVersion(t *testing.T) {
	v := loadVectors(t)
	c := load(t)
	if v.DatasetVersion != c.Meta().Version {
		t.Errorf("vectors target dataset %s but embedded dataset is %s",
			v.DatasetVersion, c.Meta().Version)
	}
}

func TestConformanceFold(t *testing.T) {
	for _, tc := range loadVectors(t).Fold {
		if got := foldText(tc.In); got != tc.Out {
			t.Errorf("fold(%q) = %q, want %q", tc.In, got, tc.Out)
		}
	}
}

func TestConformanceClassify(t *testing.T) {
	for _, tc := range loadVectors(t).Classify {
		s := Stratum{Low: tc.Low, High: tc.High, LowOp: tc.LowOp, HighOp: tc.HighOp}
		if got := string(s.classify(tc.Value)); got != tc.Expect {
			t.Errorf("%s: classify(%v) = %s, want %s", tc.Name, tc.Value, got, tc.Expect)
		}
	}
}

func TestConformanceInterpret(t *testing.T) {
	for _, tc := range loadVectors(t).Interpret {
		t.Run(tc.Name, func(t *testing.T) {
			var opts []Option
			switch {
			case tc.Ranges == "custom":
				opts = append(opts, WithCustomRanges(tc.CustomRanges))
			case strings.HasPrefix(tc.Ranges, "provider:"):
				opts = append(opts, WithProviderRanges(strings.TrimPrefix(tc.Ranges, "provider:")))
			}
			c := load(t, opts...)

			got, err := c.Interpret(tc.TestID, tc.Value, tc.Patient.toPatient())
			if tc.ExpectError != "" {
				if code := errCode(err); code != tc.ExpectError {
					t.Fatalf("want error %q, got %q", tc.ExpectError, code)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			e := tc.Expect
			if e.Flag != "" && string(got.Flag) != e.Flag {
				t.Errorf("flag = %s, want %s", got.Flag, e.Flag)
			}
			if e.StratumHigh != nil {
				if got.Stratum.High == nil || *got.Stratum.High != *e.StratumHigh {
					t.Errorf("stratum high = %v, want %v", got.Stratum.High, *e.StratumHigh)
				}
			}
			if e.StratumLow != nil {
				if got.Stratum.Low == nil || *got.Stratum.Low != *e.StratumLow {
					t.Errorf("stratum low = %v, want %v", got.Stratum.Low, *e.StratumLow)
				}
			}
			if e.Units != "" && got.Units != e.Units {
				t.Errorf("units = %q, want %q", got.Units, e.Units)
			}
			if e.Warns && len(got.Warnings) == 0 {
				t.Error("expected at least one warning")
			}
		})
	}
}

func TestConformanceDraw(t *testing.T) {
	c := load(t)
	for _, tc := range loadVectors(t).Draw {
		t.Run(tc.Name, func(t *testing.T) {
			plan, err := c.DrawFor(tc.Provider, tc.TestIDs)
			if tc.ExpectError != "" {
				if code := errCode(err); code != tc.ExpectError {
					t.Fatalf("want error %q, got %q", tc.ExpectError, code)
				}
				return
			}
			if err != nil {
				t.Fatalf("unexpected error: %v", err)
			}
			if len(plan.Tubes) != len(tc.ExpectTubeOrder) {
				t.Fatalf("got %d tubes, want %d", len(plan.Tubes), len(tc.ExpectTubeOrder))
			}
			for i, want := range tc.ExpectTubeOrder {
				if string(plan.Tubes[i].Type) != want {
					t.Errorf("tube %d = %s, want %s", i+1, plan.Tubes[i].Type, want)
				}
				if plan.Tubes[i].Position != i+1 {
					t.Errorf("tube %d position = %d", i+1, plan.Tubes[i].Position)
				}
			}
			if len(plan.Warnings) < tc.ExpectMinWarn {
				t.Errorf("got %d warnings, want >= %d", len(plan.Warnings), tc.ExpectMinWarn)
			}
			if len(plan.Unresolved) != tc.ExpectUnresolved {
				t.Errorf("got %d unresolved, want %d", len(plan.Unresolved), tc.ExpectUnresolved)
			}
		})
	}
}

func TestConformanceSearch(t *testing.T) {
	c := load(t)
	for _, tc := range loadVectors(t).Search {
		got := c.Search(tc.Query, 10)
		if tc.ExpectEmpty {
			if len(got) != 0 {
				t.Errorf("Search(%q): want empty, got %d", tc.Query, len(got))
			}
			continue
		}
		found := false
		for _, m := range got {
			if m.Test.ID == tc.ExpectContains {
				found = true
			}
		}
		if !found {
			t.Errorf("Search(%q): want %s in results", tc.Query, tc.ExpectContains)
		}
		if tc.ExpectFirst != "" && (len(got) == 0 || got[0].Test.ID != tc.ExpectFirst) {
			t.Errorf("Search(%q): want first = %s", tc.Query, tc.ExpectFirst)
		}
	}
}

func TestConformanceOrderSet(t *testing.T) {
	c := load(t)
	for _, tc := range loadVectors(t).OrderSet {
		got, err := c.OrderSet(tc.Profile, tc.CoreOnly)
		if tc.ExpectError != "" {
			if err == nil {
				t.Errorf("OrderSet(%q): expected error", tc.Profile)
			}
			continue
		}
		if err != nil {
			t.Fatalf("OrderSet(%q): %v", tc.Profile, err)
		}
		if len(got) != tc.ExpectCount {
			t.Errorf("OrderSet(%q, core=%v) = %d, want %d",
				tc.Profile, tc.CoreOnly, len(got), tc.ExpectCount)
		}
	}
}

func TestConformanceResultFormat(t *testing.T) {
	c := load(t)
	for _, tc := range loadVectors(t).ResultFormat {
		test, ok := c.Get(tc.TestID)
		if !ok {
			t.Errorf("%s: unknown test %s", tc.Name, tc.TestID)
			continue
		}
		if test.ResultFormat.Kind != tc.Expect.Kind {
			t.Errorf("%s: kind = %q, want %q", tc.Name, test.ResultFormat.Kind, tc.Expect.Kind)
		}
		if test.ResultFormat.StructuredEntry != tc.Expect.StructuredEntry {
			t.Errorf("%s: structured_entry = %v, want %v",
				tc.Name, test.ResultFormat.StructuredEntry, tc.Expect.StructuredEntry)
		}
	}
}

func TestConformanceResultTemplate(t *testing.T) {
	c := load(t)
	for _, tc := range loadVectors(t).ResultTemplate {
		t.Run(tc.Name, func(t *testing.T) {
			var tpl *ResultTemplate
			var ok bool
			if tc.TestID != "" {
				tpl, ok = c.ResultTemplate(tc.TestID)
			} else {
				tpl, ok = c.Template(tc.TemplateID)
			}
			if tc.ExpectNoTemplate {
				if ok {
					t.Fatalf("expected no template, got %s", tpl.ID)
				}
				return
			}
			if !ok {
				t.Fatal("expected a template, got none")
			}
			e := tc.Expect
			if e.TemplateID != "" && tpl.ID != e.TemplateID {
				t.Errorf("template id = %s, want %s", tpl.ID, e.TemplateID)
			}
			if len(e.ComponentIDs) > 0 {
				got := make([]string, len(tpl.Components))
				for i, comp := range tpl.Components {
					got[i] = comp.ID
				}
				if strings.Join(got, ",") != strings.Join(e.ComponentIDs, ",") {
					t.Errorf("component ids = %v, want %v", got, e.ComponentIDs)
				}
			}
			if e.ComponentCount > 0 && len(tpl.Components) != e.ComponentCount {
				t.Errorf("component count = %d, want %d", len(tpl.Components), e.ComponentCount)
			}
			if e.CompletenessScore != nil && tpl.Completeness.Score != *e.CompletenessScore {
				t.Errorf("completeness = %v, want %v", tpl.Completeness.Score, *e.CompletenessScore)
			}
			if e.AppliesTo != nil && len(tpl.AppliesTo) != len(e.AppliesTo) {
				t.Errorf("applies_to = %v, want %v", tpl.AppliesTo, e.AppliesTo)
			}
			if e.TemplateSource != "" && tpl.Provenance["template_source"] != e.TemplateSource {
				t.Errorf("template_source = %q, want %q",
					tpl.Provenance["template_source"], e.TemplateSource)
			}
			for id, want := range e.Components {
				comp := findComponent(tpl, id)
				if comp == nil {
					t.Errorf("component %s missing", id)
					continue
				}
				checkComponent(t, id, comp, want)
			}
			// Templates must never assert reference ranges or critical limits:
			// those belong to the activating clinic, not a global library.
			if len(e.NoComponentKeys) > 0 {
				checkAbsentKeys(t, tpl.ID, e.NoComponentKeys)
			}
		})
	}
}

func findComponent(tpl *ResultTemplate, id string) *ResultComponent {
	for i := range tpl.Components {
		if tpl.Components[i].ID == id {
			return &tpl.Components[i]
		}
	}
	return nil
}

func checkComponent(t *testing.T, id string, c *ResultComponent, want map[string]any) {
	t.Helper()
	for k, v := range want {
		var got any
		switch k {
		case "type":
			got = c.Type
		case "entry_mode":
			got = c.EntryMode
		case "required":
			got = c.Required
		case "unitless":
			got = c.Unitless
		case "suggested_units":
			got = c.SuggestedUnits
		case "has_calculation":
			got = c.Calculation != nil
		default:
			t.Errorf("%s: vector checks unknown field %q", id, k)
			continue
		}
		if fmt.Sprint(got) != fmt.Sprint(v) {
			t.Errorf("%s.%s = %v, want %v", id, k, got, v)
		}
	}
}

// checkAbsentKeys walks the raw published JSON, so it catches a forbidden key
// even though the Go struct would silently drop it.
func checkAbsentKeys(t *testing.T, templateID string, forbidden []string) {
	t.Helper()
	var doc struct {
		Templates []map[string]any `json:"templates"`
	}
	if err := json.Unmarshal(rawTemplates, &doc); err != nil {
		t.Fatalf("parsing raw templates: %v", err)
	}
	for _, raw := range doc.Templates {
		if raw["id"] != templateID {
			continue
		}
		comps, _ := raw["components"].([]any)
		for _, ci := range comps {
			cm, _ := ci.(map[string]any)
			for _, key := range forbidden {
				if _, present := cm[key]; present {
					t.Errorf("component %v carries forbidden key %q", cm["id"], key)
				}
			}
		}
	}
}
