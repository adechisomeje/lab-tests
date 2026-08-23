package labtests

import (
	"errors"
	"fmt"
	"sort"
)

// ErrNoProvider is returned when a draw plan cannot determine whose order of
// draw to apply.
var ErrNoProvider = errors.New("labtests: no provider selected for order of draw")

// DrawPlan is a phlebotomy plan for a set of ordered tests: which tubes to
// fill, in what order, and how much blood each needs.
type DrawPlan struct {
	Tubes []DrawTube

	// Unresolved lists ordered tests with no published tube requirement. They
	// still need collecting -- consult the test's Specimen.Container field.
	Unresolved []*Test

	// Provider whose order of draw was applied.
	Provider string
	// OrderSource is the published statement the sequence came from, for audit.
	OrderSource string
	// Warnings must be surfaced to the collecting clinician.
	Warnings []string
}

// DrawTube is one tube in a draw plan.
type DrawTube struct {
	Type      TubeType
	CapColour string
	// Position is the 1-based order in which to draw this tube.
	Position int
	Tests    []*Test
	// TotalVolumeML sums the published minimum volumes of the tests assigned to
	// this tube. It is a conservative upper bound: laboratories often run
	// several assays from one draw. VolumeKnown is false when no test in the
	// tube publishes a volume.
	TotalVolumeML float64
	VolumeKnown   bool
	// SequenceKnown is false when the provider does not document where this
	// tube belongs in the order; such tubes are placed last.
	SequenceKnown bool
}

// Draw builds a phlebotomy plan using the configured provider's order of draw,
// or the dataset's sole provider when only one is present.
func (c *Catalogue) Draw(testIDs []string) (*DrawPlan, error) {
	providerID := c.rangeProvider
	if providerID == "" {
		if len(c.providers) != 1 {
			return nil, ErrNoProvider
		}
		for id := range c.providers {
			providerID = id
		}
	}
	return c.DrawFor(providerID, testIDs)
}

// DrawFor builds a phlebotomy plan using a named provider's order of draw.
//
// Order of draw is provider-specific and published sequences genuinely
// disagree with one another, so the plan reports which provider's rule it
// applied and warns when that rule conflicts with the CLSI consensus order or
// does not cover a tube in the plan. Follow your own laboratory's SOP.
func (c *Catalogue) DrawFor(providerID string, testIDs []string) (*DrawPlan, error) {
	prov, ok := c.providers[providerID]
	if !ok {
		return nil, fmt.Errorf("labtests: unknown provider %q", providerID)
	}

	plan := &DrawPlan{Provider: prov.Name}
	grouped := map[TubeType]*DrawTube{}

	for _, id := range testIDs {
		t, ok := c.byID[id]
		if !ok {
			return nil, fmt.Errorf("%w: %s", ErrUnknownTest, id)
		}
		if t.Specimen.Tube == nil {
			plan.Unresolved = append(plan.Unresolved, t)
			continue
		}
		tube := grouped[t.Specimen.Tube.Type]
		if tube == nil {
			tube = &DrawTube{
				Type:      t.Specimen.Tube.Type,
				CapColour: t.Specimen.Tube.CapColour,
			}
			grouped[t.Specimen.Tube.Type] = tube
		}
		tube.Tests = append(tube.Tests, t)
		if v := t.Specimen.Volume; v != nil {
			tube.TotalVolumeML += v.Value
			tube.VolumeKnown = true
		}
	}

	// Rank by the provider's documented sequence; anything it does not cover
	// is placed last rather than guessed at.
	rank := map[TubeType]int{}
	if prov.OrderOfDraw != nil {
		for i, tt := range prov.OrderOfDraw.Sequence {
			rank[tt] = i
		}
		plan.OrderSource = prov.OrderOfDraw.SourceQuote
	}

	for _, tube := range grouped {
		_, known := rank[tube.Type]
		tube.SequenceKnown = known
		plan.Tubes = append(plan.Tubes, *tube)
	}
	sort.SliceStable(plan.Tubes, func(i, j int) bool {
		ri, oki := rank[plan.Tubes[i].Type]
		rj, okj := rank[plan.Tubes[j].Type]
		if oki != okj {
			return oki // known positions first
		}
		if oki && okj {
			return ri < rj
		}
		return plan.Tubes[i].Type < plan.Tubes[j].Type
	})
	for i := range plan.Tubes {
		plan.Tubes[i].Position = i + 1
	}

	// Warnings
	if prov.OrderOfDraw == nil {
		plan.Warnings = append(plan.Warnings,
			"this provider publishes no order of draw; tube sequence is not authoritative")
	} else {
		for _, tube := range plan.Tubes {
			if !tube.SequenceKnown {
				plan.Warnings = append(plan.Warnings, fmt.Sprintf(
					"provider does not specify where the %s tube (%s) belongs in the "+
						"order of draw; it has been placed last -- confirm against your SOP",
					tube.Type, tube.CapColour))
			}
		}
		if prov.OrderOfDraw.ConflictsWithCLSI && len(plan.Tubes) > 1 {
			plan.Warnings = append(plan.Warnings, prov.OrderOfDraw.ConflictNote)
		}
	}
	if len(plan.Unresolved) > 0 {
		plan.Warnings = append(plan.Warnings, fmt.Sprintf(
			"%d ordered test(s) publish no tube requirement; check each test's "+
				"container guidance", len(plan.Unresolved)))
	}
	return plan, nil
}

// Turnaround reports the expected time to a final result, in days.
func (c *Catalogue) Turnaround(testID string) (*DayRange, error) {
	t, ok := c.byID[testID]
	if !ok {
		return nil, fmt.Errorf("%w: %s", ErrUnknownTest, testID)
	}
	if t.Turnaround.FinalWorkingDays != nil {
		return t.Turnaround.FinalWorkingDays, nil
	}
	if t.Turnaround.Days != nil {
		return t.Turnaround.Days, nil
	}
	return nil, fmt.Errorf("labtests: no turnaround published for %s", testID)
}

// SlowestTurnaround returns the longest expected turnaround across a set of
// tests, which is when a batched report can be expected. Tests without a
// published turnaround are named in the second return value.
func (c *Catalogue) SlowestTurnaround(testIDs []string) (*DayRange, []string, error) {
	var worst *DayRange
	var unknown []string
	for _, id := range testIDs {
		d, err := c.Turnaround(id)
		if err != nil {
			if errors.Is(err, ErrUnknownTest) {
				return nil, nil, err
			}
			unknown = append(unknown, id)
			continue
		}
		if worst == nil || d.Max > worst.Max {
			worst = d
		}
	}
	return worst, unknown, nil
}
