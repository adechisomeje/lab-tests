// Compile-check for the snippets in docs/EMR-INTEGRATION.md.
// It exercises the library API surface the guide relies on, against a stub DB.
package main

import (
	"context"
	"errors"
	"fmt"

	labtests "github.com/adechisomeje/lab-tests"
)

type DB interface{}

type Service struct {
	cat             *labtests.Catalogue
	rangeSetVersion string
}

func loadLocalRanges(ctx context.Context, db DB) (map[string][]labtests.Stratum, error) {
	// Stands in for the SQL query in the guide; the Stratum fields below are
	// exactly the columns it scans into.
	high, low := 400.0, 15.0
	return map[string][]labtests.Stratum{
		"ferritin": {{
			Sex: labtests.SexMale, AgeUnit: "years",
			Low: &low, High: &high, HighOp: "lte",
		}},
	}, nil
}

func New(ctx context.Context, db DB) (*Service, error) {
	ranges, err := loadLocalRanges(ctx, db)
	if err != nil {
		return nil, err
	}
	cat, err := labtests.Load(labtests.WithCustomRanges(ranges))
	if err != nil {
		return nil, err
	}
	return &Service{cat: cat, rangeSetVersion: "2026-01-15"}, nil
}

func (s *Service) SearchTests(q string, limit int) []labtests.Match {
	return s.cat.Search(q, limit)
}

func (s *Service) SuggestedPanel(id string) ([]*labtests.Test, error) {
	return s.cat.OrderSet(id, true)
}

func (s *Service) CollectionPlan(ids []string) (*labtests.DrawPlan, error) {
	return s.cat.Draw(ids)
}

func (s *Service) RecordResult(testID string, value float64, p labtests.Patient) (string, error) {
	r, err := s.cat.Interpret(testID, value, p)
	switch {
	case errors.Is(err, labtests.ErrNoIntervals),
		errors.Is(err, labtests.ErrNoApplicableStratum):
		return "unflagged", nil
	case err != nil:
		return "", err
	}
	_, _, _ = r.Stratum.Low, r.Stratum.High, r.Warnings
	return string(r.Flag), nil
}

// seedRow mirrors the seeding loop's field access.
func seedRow(cat *labtests.Catalogue, t *labtests.Test) (string, []string, *string, *float64, float64) {
	var tubeType *string
	if t.Specimen.Tube != nil {
		s := string(t.Specimen.Tube.Type)
		tubeType = &s
	}
	var tat *float64
	if d, err := cat.Turnaround(t.ID); err == nil {
		tat = &d.Max
	}
	return t.ID, t.Specimen.Types, tubeType, tat, t.Completeness.Score
}

func main() {
	ctx := context.Background()
	svc, err := New(ctx, nil)
	if err != nil {
		panic(err)
	}

	fmt.Println("dataset version:", svc.cat.Meta().Version)
	fmt.Println("search hits:", len(svc.SearchTests("ferritin", 5)))

	panel, _ := svc.SuggestedPanel("aesthetic-beauty-clinic")
	fmt.Println("suggested panel:", len(panel), "core tests")

	plan, _ := svc.CollectionPlan([]string{"ferritin", "ammonia"})
	fmt.Println("tubes:", len(plan.Tubes), "warnings:", len(plan.Warnings),
		"unresolved:", len(plan.Unresolved))

	// Local range says male ferritin 15-400.
	for _, v := range []float64{500, 20} {
		flag, _ := svc.RecordResult("ferritin", v,
			labtests.Patient{Sex: labtests.SexMale, Age: labtests.Years(34)})
		fmt.Printf("ferritin %.0f -> %s\n", v, flag)
	}

	// A test with no local range must NOT borrow provider data.
	flag, _ := svc.RecordResult("alanine-aminotransferase", 62,
		labtests.Patient{Sex: labtests.SexMale, Age: labtests.Years(34)})
	fmt.Println("ALT, no local range ->", flag)

	id, types, tube, tat, score := seedRow(svc.cat, panel[0])
	fmt.Printf("seed row: %s types=%v tube=%v tat=%v score=%.2f\n", id, types, tube, tat, score)
}
