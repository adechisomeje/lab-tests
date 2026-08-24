// Package labtests provides a queryable catalogue of medical laboratory tests
// with specimen requirements, turnaround times and reference intervals.
//
// The dataset is embedded, so there is no runtime file or network dependency.
//
// Reference-interval interpretation is opt-in by design. Intervals in this
// dataset belong to one provider's analysers and population; using them for a
// different laboratory is a patient-safety error. Interpret returns
// ErrNoRangeSource until you explicitly choose a source:
//
//	cat, _ := labtests.Load()                                  // catalogue only
//	cat, _ := labtests.Load(labtests.WithProviderRanges("mft-nhs"))
//	cat, _ := labtests.Load(labtests.WithCustomRanges(myLabRanges))
package labtests

import (
	"encoding/json"
	"fmt"
	"sort"
	"strings"
)

// Catalogue is an immutable, in-memory view of the dataset. It is safe for
// concurrent use once loaded.
type Catalogue struct {
	meta       Meta
	tests      []*Test
	byID       map[string]*Test
	haystacks  map[string]string
	profiles   map[string]*ClinicProfile
	categories map[string]*Category
	providers  map[string]*Provider
	templates  map[string]*ResultTemplate

	rangeMode     rangeMode
	rangeProvider string
	customRanges  map[string][]Stratum
}

type Meta struct {
	Name        string `json:"name"`
	Version     string `json:"version"`
	Description string `json:"description"`
	License     string `json:"license"`
	Generated   string `json:"generated"`
	TestCount   int    `json:"test_count"`
	Disclaimer  string `json:"disclaimer"`
}

type rangeMode int

const (
	rangesDisabled rangeMode = iota
	rangesProvider
	rangesCustom
)

// Option configures a Catalogue at load time.
type Option func(*Catalogue)

// WithProviderRanges enables reference-interval interpretation using the
// intervals published by the named provider. You are asserting that those
// intervals are valid for your laboratory and population.
func WithProviderRanges(providerID string) Option {
	return func(c *Catalogue) {
		c.rangeMode = rangesProvider
		c.rangeProvider = providerID
	}
}

// WithCustomRanges enables interpretation using your own laboratory's
// intervals, keyed by test ID. This is the correct choice for production.
// Tests absent from the map fall back to nothing, not to provider data.
func WithCustomRanges(ranges map[string][]Stratum) Option {
	return func(c *Catalogue) {
		c.rangeMode = rangesCustom
		c.customRanges = ranges
	}
}

// Load parses the embedded dataset.
func Load(opts ...Option) (*Catalogue, error) {
	var testDoc struct {
		Meta  Meta    `json:"meta"`
		Tests []*Test `json:"tests"`
	}
	if err := json.Unmarshal(rawTests, &testDoc); err != nil {
		return nil, fmt.Errorf("labtests: parsing tests: %w", err)
	}

	c := &Catalogue{
		meta:       testDoc.Meta,
		tests:      testDoc.Tests,
		byID:       make(map[string]*Test, len(testDoc.Tests)),
		haystacks:  make(map[string]string, len(testDoc.Tests)),
		profiles:   map[string]*ClinicProfile{},
		categories: map[string]*Category{},
		providers:  map[string]*Provider{},
		templates:  map[string]*ResultTemplate{},
	}
	for _, t := range testDoc.Tests {
		c.byID[t.ID] = t
		parts := append([]string{t.Name}, t.Aliases...)
		c.haystacks[t.ID] = foldText(strings.Join(parts, " "))
	}

	var profDoc struct {
		Profiles []*ClinicProfile `json:"profiles"`
	}
	if err := json.Unmarshal(rawProfiles, &profDoc); err != nil {
		return nil, fmt.Errorf("labtests: parsing clinic profiles: %w", err)
	}
	for _, p := range profDoc.Profiles {
		c.profiles[p.ID] = p
	}

	var catDoc struct {
		Categories []*Category `json:"categories"`
	}
	if err := json.Unmarshal(rawCategories, &catDoc); err != nil {
		return nil, fmt.Errorf("labtests: parsing categories: %w", err)
	}
	for _, x := range catDoc.Categories {
		c.categories[x.ID] = x
	}

	var provDoc struct {
		Providers []*Provider `json:"providers"`
	}
	if err := json.Unmarshal(rawProviders, &provDoc); err != nil {
		return nil, fmt.Errorf("labtests: parsing providers: %w", err)
	}
	for _, p := range provDoc.Providers {
		c.providers[p.ID] = p
	}

	var tplDoc struct {
		Templates []*ResultTemplate `json:"templates"`
	}
	if err := json.Unmarshal(rawTemplates, &tplDoc); err != nil {
		return nil, fmt.Errorf("labtests: parsing result templates: %w", err)
	}
	for _, t := range tplDoc.Templates {
		c.templates[t.ID] = t
	}

	for _, opt := range opts {
		opt(c)
	}
	if c.rangeMode == rangesProvider {
		if _, ok := c.providers[c.rangeProvider]; !ok {
			return nil, fmt.Errorf("labtests: unknown provider %q", c.rangeProvider)
		}
	}
	return c, nil
}

// Meta returns dataset metadata, including the disclaimer you should surface
// to clinical users.
func (c *Catalogue) Meta() Meta { return c.meta }

// Tests returns every test. The slice is a copy; the pointers are shared.
func (c *Catalogue) Tests() []*Test {
	out := make([]*Test, len(c.tests))
	copy(out, c.tests)
	return out
}

// Get returns a test by ID.
func (c *Catalogue) Get(id string) (*Test, bool) {
	t, ok := c.byID[id]
	return t, ok
}

// Provider returns a provider record by ID.
func (c *Catalogue) Provider(id string) (*Provider, bool) {
	p, ok := c.providers[id]
	return p, ok
}

// Profile returns a clinic profile by ID.
func (c *Catalogue) Profile(id string) (*ClinicProfile, bool) {
	p, ok := c.profiles[id]
	return p, ok
}

// Profiles returns every clinic profile, ordered by ID.
func (c *Catalogue) Profiles() []*ClinicProfile {
	out := make([]*ClinicProfile, 0, len(c.profiles))
	for _, p := range c.profiles {
		out = append(out, p)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// OrderSet returns the tests a clinic profile covers. When coreOnly is true it
// returns just the curated core panel, which is what you want for a default
// order set; the full list is better suited to browse and discovery.
func (c *Catalogue) OrderSet(profileID string, coreOnly bool) ([]*Test, error) {
	p, ok := c.profiles[profileID]
	if !ok {
		return nil, fmt.Errorf("labtests: unknown clinic profile %q", profileID)
	}
	ids := p.TestIDs
	if coreOnly {
		ids = p.CoreTestIDs
	}
	out := make([]*Test, 0, len(ids))
	for _, id := range ids {
		if t, ok := c.byID[id]; ok {
			out = append(out, t)
		}
	}
	return out, nil
}

// ByCategory returns every test in a clinical category.
func (c *Catalogue) ByCategory(categoryID string) ([]*Test, error) {
	cat, ok := c.categories[categoryID]
	if !ok {
		return nil, fmt.Errorf("labtests: unknown category %q", categoryID)
	}
	out := make([]*Test, 0, len(cat.TestIDs))
	for _, id := range cat.TestIDs {
		if t, ok := c.byID[id]; ok {
			out = append(out, t)
		}
	}
	return out, nil
}

// ResultTemplate returns the starter template seeding structured result entry
// for a test, if one is defined.
//
// The template is a starting point, not a specification: copy it into your own
// catalogue, confirm every component and unit against your analyser, and treat
// your versioned copy as authoritative. Check Test.ResultFormat first --
// narrative and document results should not be captured as fields at all.
func (c *Catalogue) ResultTemplate(testID string) (*ResultTemplate, bool) {
	t, ok := c.byID[testID]
	if !ok || t.ResultTemplate == nil {
		return nil, false
	}
	return t.ResultTemplate, true
}

// Template returns a starter template by its own id. Some templates -- such as
// urea-and-electrolytes -- are reusable starting points with no matching test
// in this catalogue.
func (c *Catalogue) Template(templateID string) (*ResultTemplate, bool) {
	t, ok := c.templates[templateID]
	return t, ok
}

// Templates returns every starter template, ordered by id.
func (c *Catalogue) Templates() []*ResultTemplate {
	out := make([]*ResultTemplate, 0, len(c.templates))
	for _, t := range c.templates {
		out = append(out, t)
	}
	sort.Slice(out, func(i, j int) bool { return out[i].ID < out[j].ID })
	return out
}

// Match is a search hit. Higher Score is a better match.
type Match struct {
	Test  *Test
	Score float64
}

// Search finds tests by name or alias. Matching is case- and
// accent-insensitive, so "mullerian" finds "Anti-Müllerian Hormone".
// Results are ranked: exact name, then name prefix, then alias, then substring.
func (c *Catalogue) Search(query string, limit int) []Match {
	q := foldText(query)
	if q == "" {
		return nil
	}
	var out []Match
	for _, t := range c.tests {
		name := foldText(t.Name)
		var score float64
		switch {
		case name == q:
			score = 1.0
		case strings.HasPrefix(name, q):
			score = 0.9
		default:
			for _, a := range t.Aliases {
				if fa := foldText(a); fa == q {
					score = 0.85
					break
				} else if strings.HasPrefix(fa, q) {
					score = 0.75
				}
			}
			if score == 0 && strings.Contains(c.haystacks[t.ID], q) {
				// Shorter names containing the query are likelier the intent.
				score = 0.5 - float64(len(name))/10000
			}
		}
		if score > 0 {
			out = append(out, Match{Test: t, Score: score})
		}
	}
	sort.SliceStable(out, func(i, j int) bool {
		if out[i].Score != out[j].Score {
			return out[i].Score > out[j].Score
		}
		return out[i].Test.Name < out[j].Test.Name
	})
	if limit > 0 && len(out) > limit {
		out = out[:limit]
	}
	return out
}

// Latin letters with diacritics, mapped to their unaccented base. Kept as
// paired strings rather than pulling in golang.org/x/text: this library is
// meant to drop into clinical systems, where a zero-dependency build is worth
// more than full Unicode normalisation.
const (
	accented = "àáâãäåāăąçćĉċčďđèéêëēĕėęěĝğġģĥħìíîïĩīĭįıĵķĺļľłñńņňòóôõöøōŏőŕŗřśŝşšţťŧùúûüũūŭůűųŵýÿŷźżž"
	plain    = "aaaaaaaaacccccddeeeeeeeeegggghhiiiiiiiiijkllllnnnnooooooooorrrsssstttuuuuuuuuuuwyyyzzz"
)

// Multi-character expansions, which cannot be handled by the paired table.
// "ß" maps to "beta", not "ss": in this corpus it is used as a beta glyph
// ("ß2 Microglobulin"), and the dataset's IDs are generated the same way, so
// a search for "beta2 microglobulin" must reach beta2-microglobulin.
var foldPairs = strings.NewReplacer(
	"ß", "beta", "æ", "ae", "œ", "oe", "þ", "th", "ð", "d",
	"–", "-", "—", "-", "‐", "-", "’", "'", "°", "",
)

var foldRunes map[rune]rune

func init() {
	src, dst := []rune(accented), []rune(plain)
	foldRunes = make(map[rune]rune, len(src))
	for i, r := range src {
		if i < len(dst) {
			foldRunes[r] = dst[i]
		}
	}
}

// foldText lowercases and strips diacritics so search is insensitive to both.
func foldText(s string) string {
	s = foldPairs.Replace(strings.ToLower(strings.TrimSpace(s)))
	var b strings.Builder
	b.Grow(len(s))
	for _, r := range s {
		if base, ok := foldRunes[r]; ok {
			b.WriteRune(base)
		} else {
			b.WriteRune(r)
		}
	}
	return b.String()
}
