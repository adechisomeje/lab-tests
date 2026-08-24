# Integrating lab-tests into a Go EMR

How to build a Laboratory module on top of this dataset: what to put in your
database, what to leave to the library, and where the safety boundaries are.

---

## 1. The split

Draw one line and hold it:

| Concern | Owner | Why |
| --- | --- | --- |
| Test catalogue, aliases, categories, panels | **lab-tests** | Reference data. Upgrades as a unit. |
| Specimen/tube requirements, turnaround | **lab-tests** | Same. |
| Order-of-draw and interval **resolution logic** | **lab-tests** | Fiddly, safety-relevant, tested once. |
| Orders, specimens, results, audit | **your DB** | Your clinical records. |
| **Reference interval values** | **your DB** | See §4. This is the one that matters. |
| External codes (LOINC, local lab codes) | **your DB** | Provider-specific mapping. |

The library is stateless and holds no patient data. It answers "what does this
test need" and "what does this number mean for this patient". Everything about
*a specific patient's* order stays in your database.

---

## 2. Mirror the catalogue into Postgres

You *could* keep the catalogue only in the binary, but EMRs do too much SQL
reporting and need real foreign keys on orders. So mirror it as a **read-only
projection**, re-seeded by migration. The library stays authoritative for logic.

```sql
-- Mirrored from the dataset. Never edited by hand; re-seeded by migration.
CREATE TABLE lab_test (
    id                   TEXT PRIMARY KEY,     -- dataset slug, e.g. 'ferritin'
    name                 TEXT NOT NULL,
    department           TEXT NOT NULL,
    specimen_types       TEXT[] NOT NULL DEFAULT '{}',
    tube_type            TEXT,
    tube_cap_colour      TEXT,
    turnaround_max_days  NUMERIC,
    completeness         NUMERIC NOT NULL,
    dataset_version      TEXT NOT NULL
);

CREATE TABLE lab_test_alias (
    test_id TEXT NOT NULL REFERENCES lab_test(id) ON DELETE CASCADE,
    alias   TEXT NOT NULL,
    PRIMARY KEY (test_id, alias)
);

CREATE TABLE lab_test_category (
    test_id  TEXT NOT NULL REFERENCES lab_test(id) ON DELETE CASCADE,
    category TEXT NOT NULL,
    PRIMARY KEY (test_id, category)
);

-- Your mapping to coding systems. The dataset ships none; you own this.
CREATE TABLE lab_test_code (
    test_id TEXT NOT NULL REFERENCES lab_test(id),
    system  TEXT NOT NULL,          -- 'loinc' | 'snomed' | 'local'
    code    TEXT NOT NULL,
    PRIMARY KEY (test_id, system)
);
```

Your clinical tables reference `lab_test(id)`:

```sql
CREATE TABLE lab_order (
    id             UUID PRIMARY KEY,
    patient_id     UUID NOT NULL REFERENCES patient(id),
    clinician_id   UUID NOT NULL,
    clinic_profile TEXT,            -- which panel it came from, for audit
    ordered_at     TIMESTAMPTZ NOT NULL DEFAULT now(),
    status         TEXT NOT NULL
);

CREATE TABLE lab_order_item (
    id       UUID PRIMARY KEY,
    order_id UUID NOT NULL REFERENCES lab_order(id) ON DELETE CASCADE,
    test_id  TEXT NOT NULL REFERENCES lab_test(id),
    status   TEXT NOT NULL,
    UNIQUE (order_id, test_id)
);

CREATE TABLE lab_specimen (
    id           UUID PRIMARY KEY,
    order_id     UUID NOT NULL REFERENCES lab_order(id),
    tube_type    TEXT NOT NULL,
    draw_position INT NOT NULL,
    volume_ml    NUMERIC,
    collected_at TIMESTAMPTZ,
    collected_by UUID
);

CREATE TABLE lab_result (
    id            UUID PRIMARY KEY,
    order_item_id UUID NOT NULL REFERENCES lab_order_item(id),
    value_num     NUMERIC,
    value_text    TEXT,
    units         TEXT,
    flag          TEXT,             -- 'low' | 'normal' | 'high'
    resulted_at   TIMESTAMPTZ NOT NULL,

    -- Audit: which interval set produced this flag, and from what band.
    interpreted_with TEXT,          -- e.g. 'local:2026-01-15' or 'provider:mft-nhs'
    interval_low     NUMERIC,
    interval_high    NUMERIC
);
```

`lab_result.interpreted_with` matters. A flag is only meaningful relative to the
interval that produced it, and intervals change when a lab changes analysers. If
you cannot say which interval flagged a historical result, you cannot defend it.

---

## 3. Seed from the embedded dataset

A small command, run as part of your migration step:

```go
// cmd/seed-lab-catalogue/main.go
package main

import (
	"context"
	"log"

	labtests "github.com/adechisomeje/lab-tests"
)

func main() {
	cat, err := labtests.Load() // catalogue only; no ranges needed to seed
	if err != nil {
		log.Fatal(err)
	}
	version := cat.Meta().Version

	ctx := context.Background()
	tx, err := db.Begin(ctx)
	if err != nil {
		log.Fatal(err)
	}
	defer tx.Rollback(ctx)

	for _, t := range cat.Tests() {
		var tubeType, tubeCap *string
		if t.Specimen.Tube != nil {
			s := string(t.Specimen.Tube.Type)
			tubeType, tubeCap = &s, &t.Specimen.Tube.CapColour
		}
		var tat *float64
		if d, err := cat.Turnaround(t.ID); err == nil {
			tat = &d.Max
		}

		if _, err := tx.Exec(ctx, `
            INSERT INTO lab_test (id, name, department, specimen_types,
                                  tube_type, tube_cap_colour,
                                  turnaround_max_days, completeness, dataset_version)
            VALUES ($1,$2,$3,$4,$5,$6,$7,$8,$9)
            ON CONFLICT (id) DO UPDATE SET
                name = EXCLUDED.name,
                department = EXCLUDED.department,
                specimen_types = EXCLUDED.specimen_types,
                tube_type = EXCLUDED.tube_type,
                tube_cap_colour = EXCLUDED.tube_cap_colour,
                turnaround_max_days = EXCLUDED.turnaround_max_days,
                completeness = EXCLUDED.completeness,
                dataset_version = EXCLUDED.dataset_version`,
			t.ID, t.Name, t.Department, t.Specimen.Types,
			tubeType, tubeCap, tat, t.Completeness.Score, version); err != nil {
			log.Fatal(err)
		}
		// aliases and categories similarly
	}
	if err := tx.Commit(ctx); err != nil {
		log.Fatal(err)
	}
}
```

**Pin the version.** On startup, compare the binary's dataset version against
what is seeded and refuse to run on a mismatch. A silent divergence between the
catalogue your code reasons about and the one your foreign keys point at is a
bug you will not notice until it matters:

```go
if seeded != cat.Meta().Version {
    return fmt.Errorf("lab catalogue seeded at %s but binary embeds %s; run migrations",
        seeded, cat.Meta().Version)
}
```

Test IDs are stable slugs, but they *can* change when an upstream name is
corrected. Treat a dataset upgrade as a migration, diff the IDs, and remap any
that moved before deploying.

---

## 4. Reference ranges: the part to get right

**Do not ship this dataset's reference intervals to production.** They belong to
one trust's analysers, methods and population. An interval from a Roche platform
is not valid on an Abbott one. Using them to flag your patients' results is a
patient-safety error, not a data-quality compromise.

The library enforces this: `Interpret` returns `ErrNoRangeSource` unless you
name a source explicitly. Point it at *your* table.

```go
// internal/lab/service.go
package lab

import (
	"context"
	"fmt"

	labtests "github.com/adechisomeje/lab-tests"
)

type Service struct {
	cat     *labtests.Catalogue
	version string
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
	return &Service{cat: cat, version: cat.Meta().Version}, nil
}

// loadLocalRanges reads YOUR laboratory's current intervals.
func loadLocalRanges(ctx context.Context, db DB) (map[string][]labtests.Stratum, error) {
	rows, err := db.Query(ctx, `
        SELECT test_id, sex, age_unit, age_min, age_max, low, high, low_op, high_op
        FROM lab_reference_range
        WHERE effective_from <= now()
        ORDER BY test_id`)
	if err != nil {
		return nil, err
	}
	defer rows.Close()

	out := map[string][]labtests.Stratum{}
	for rows.Next() {
		var id string
		var s labtests.Stratum
		if err := rows.Scan(&id, &s.Sex, &s.AgeUnit, &s.AgeMin, &s.AgeMax,
			&s.Low, &s.High, &s.LowOp, &s.HighOp); err != nil {
			return nil, err
		}
		out[id] = append(out[id], s)
	}
	return out, rows.Err()
}
```

`WithCustomRanges` never falls back. A test absent from your table returns
`ErrNoIntervals`, so an unconfigured test surfaces as "no reference range
available" rather than silently borrowing someone else's numbers.

**Bootstrapping.** Starting with an empty range table is correct but impractical.
Use the dataset's intervals as a *drafting aid*, not a default: export them,
have your lab lead review and sign off each one, then load the approved set.

```go
// One-off: export provider intervals for clinical review before go-live.
draft, _ := labtests.Load(labtests.WithProviderRanges("mft-nhs"))
for _, t := range draft.Tests() {
    if t.ReferenceIntervals == nil {
        continue
    }
    // Emit to CSV for sign-off. Flag anything where MatchMethod starts with
    // "fuzzy" for extra scrutiny -- that link was made heuristically.
}
```

---

## 5. The four touchpoints

### Order entry

```go
func (s *Service) SearchTests(q string, limit int) []labtests.Match {
	return s.cat.Search(q, limit)
}

// Panels: seed your editable lab_panel tables from the clinic profiles once,
// then let clinics customise. Use the CORE set as the starting point --
// non-core membership is browse-and-discover breadth, not an order set.
func (s *Service) SuggestedPanel(profileID string) ([]*labtests.Test, error) {
	return s.cat.OrderSet(profileID, true)
}
```

### Collection

```go
func (s *Service) CollectionPlan(ctx context.Context, orderID uuid.UUID) (*labtests.DrawPlan, error) {
	ids, err := s.testIDsForOrder(ctx, orderID)
	if err != nil {
		return nil, err
	}
	plan, err := s.cat.Draw(ids)
	if err != nil {
		return nil, err
	}
	// plan.Warnings MUST reach the phlebotomist, not just the log.
	return plan, nil
}
```

Persist one `lab_specimen` row per `plan.Tubes` entry, carrying `draw_position`,
so the label printer emits tubes in the right order and you can audit what was
collected.

`plan.Unresolved` lists ordered tests with no published tube requirement — show
those to the collector with the test's container guidance rather than dropping
them.

### Result entry

```go
func (s *Service) RecordResult(ctx context.Context, itemID uuid.UUID,
	testID string, value float64, p labtests.Patient) error {

	r, err := s.cat.Interpret(testID, value, p)
	switch {
	case errors.Is(err, labtests.ErrNoIntervals),
		errors.Is(err, labtests.ErrNoApplicableStratum):
		// Store the value with no flag. This is a normal outcome, not a bug:
		// it means you have no approved interval for this patient.
		return s.storeResult(ctx, itemID, value, "", nil, nil, "unflagged")
	case err != nil:
		return err
	}

	return s.storeResult(ctx, itemID, value, string(r.Flag),
		r.Stratum.Low, r.Stratum.High, "local:"+s.rangeSetVersion)
}
```

Derive `Patient` from the patient record at the time of *collection*, not
reporting — a paediatric sample must be interpreted against the child's age
even if the result is entered weeks later.

### Display

Show the flag with the band that produced it, and surface `r.Warnings`
verbatim. A clinician looking at an abnormal flag needs to know which interval
applied and whether anything about it is uncertain.

---

## 5a. Structured result entry

Your team's design is right, and the library now supports it: **the library
seeds templates; your clinic's activated, versioned definition stays
authoritative.**

### Decide whether to render a form at all

Before templates, check `result_format`. Not every test has fields to fill in.

```go
t, _ := cat.Get(testID)
switch t.ResultFormat.Kind {
case "panel":          // several defined components -> render the template
case "single-analyte": // one measured quantity -> render one field
case "qualitative":    // organism / susceptibility report
case "narrative":      // cytology, histopathology -> free-text report, no fields
case "document":       // referral laboratory returns its own report
case "unstructured":   // nothing published to structure entry around
}
```

Across the 508 tests:

| Kind | Count | Internal entry |
| --- | --- | --- |
| `single-analyte` | 187 | one numeric field |
| `qualitative` | 83 | coded/organism report |
| `narrative` | 65 | free text — **never** fields |
| `panel` | 7 | render the template |
| `document` | 24 | attach the report |
| `unstructured` | 142 | free text |

`narrative` and `document` map directly onto your PDF-only path. Cytology and
histopathology results are written findings; forcing them into numeric fields
would lose the diagnosis.

### Seed the template, then own it

```go
tpl, ok := cat.ResultTemplate("lipid-profile-incl-total-cholesterol-ldl-hdl-triglyceride")
// tpl.Version == "0.1.0"
for _, c := range tpl.Components {
    // c.ID, c.Name, c.Type, c.EntryMode, c.Required
    // c.SuggestedUnits, c.AlternateUnits, c.UnitsProvenance
    // c.Calculation (nil unless derived)
}
```

Which produces exactly the table your team specified:

| Component | Type | Entry mode | Required | Suggested units |
| --- | --- | --- | --- | --- |
| Total cholesterol | numeric | measured | yes | mmol/L |
| HDL cholesterol | numeric | measured | yes | mmol/L |
| LDL cholesterol | numeric | **either** | yes | mmol/L |
| Triglycerides | numeric | measured | yes | mmol/L |
| Non-HDL cholesterol | numeric | calculated | no | mmol/L |
| Cholesterol / HDL ratio | numeric | calculated | no | *(ratio)* |

`entry_mode: "either"` is the LDL case your team raised: measure directly, or
apply a clinic-approved calculation. The library supplies the Friedewald
expression with its caveats and `clinic_approval_required: true`, but **never
computes it** — which equation to use is a clinical policy decision.

Some templates have no matching catalogue entry and are pure starting points
(`urea-and-electrolytes`, `bone-profile`, `thyroid-function-tests`,
`coagulation-screen`, `iron-studies`). Reach those by id:

```go
tpl, _ := cat.Template("urea-and-electrolytes")
```

### What the library deliberately withholds

**No reference ranges. No critical limits.** A conformance vector enforces this:
if a component ever gained a `reference_range` or `critical_high` key, the build
fails in all three languages. Those values vary by analyser and population, so a
global library asserting them would be actively unsafe. They belong in your
`lab_reference_range` table (§4) and your own critical-limit policy.

Units are **suggestions**, carrying `units_provenance` so you can see where each
came from. `alternate_units` names other measurement systems (mmol/L vs mg/dL)
but supplies **no conversion factors** — a wrong factor is worse than none.

### Persist the activated copy, versioned

```sql
CREATE TABLE lab_test_template (
    id              UUID PRIMARY KEY,
    test_id         TEXT NOT NULL REFERENCES lab_test(id),
    version         INT  NOT NULL,           -- your version, incremented on edit
    seeded_from     TEXT,                    -- e.g. 'lipid-profile'
    seeded_version  TEXT,                    -- library template version pinned
    status          TEXT NOT NULL,           -- draft | active | retired
    activated_at    TIMESTAMPTZ,
    activated_by    UUID,
    UNIQUE (test_id, version)
);

CREATE TABLE lab_test_template_component (
    template_id  UUID NOT NULL REFERENCES lab_test_template(id) ON DELETE CASCADE,
    component_id TEXT NOT NULL,
    name         TEXT NOT NULL,
    type         TEXT NOT NULL,
    entry_mode   TEXT NOT NULL,
    required     BOOLEAN NOT NULL,
    units        TEXT,                       -- CONFIRMED by your lab, not suggested
    sort_order   INT NOT NULL,
    PRIMARY KEY (template_id, component_id)
);
```

Then store `lab_order_item.template_id` at **order** time, so the result screen
renders the exact version the clinician ordered against — as your team
specified. Editing a template creates a new version; in-flight orders keep
theirs.

`lab_result` becomes one row per component rather than per order item, with the
`interpreted_with` audit field from §4 unchanged.

### Coverage, and how much to trust each template

**All 508 tests now carry a template**, but they are not equally trustworthy,
and `provenance.template_source` tells you which is which:

| Tier | Tests | Review effort |
| --- | --- | --- |
| `curated` | 4 | Components and units hand-checked. Confirm units against your analyser. |
| `derived-from-source-notes` | 2 | Markers the source enumerates itself. Verify the list. |
| `pattern` | 502 | A shape rule matched. Marked `confidence: low`. **Review before activating.** |

A pattern template gets the *shape* right — a culture reports an organism and a
susceptibility, a PCR reports detected/not detected, an autoantibody reports a
result, titre and pattern — but it was assigned by rule, not curated for that
specific test. Treat it as a first draft of the form, not a specification.

`entry_style` is what your UI should branch on:

| Style | Tests | Render |
| --- | --- | --- |
| `fields` | 405 | Discrete component fields |
| `report` | 65 | Sectioned free text: macroscopic, microscopic, diagnosis |
| `document` | 38 | Attach the referral laboratory's report; fields are optional metadata |

The 12 shape rules are editable data in `taxonomy/result-patterns.json`,
evaluated in order with first match winning. If a rule mis-assigns a test your
clinics care about, that is a one-line change plus a rebuild — not a code fix.

Coded components carry `suggested_values` (for example
`Detected / Not detected / Equivocal / Inhibitory`). It is a starting
vocabulary, not a closed set.

---

## 6. What this does not give you

Be clear-eyed about the boundary:

- **No LOINC or SNOMED codes.** You cannot emit a conformant FHIR `Observation`
  or HL7 v2 ORU without them, so **no external lab interfacing** until you map
  them. Map your high-volume tests by hand against the official LOINC table; a
  wrong code silently corrupts downstream records, so partial and correct beats
  complete and guessed.
- **No fasting or patient-prep field.** Present only as free text, if at all.
- **Result templates for only 7 of 508 tests**, and no reference ranges or
  critical limits inside them, by design (§5a).
- **Reference intervals for 17% of tests**, and provider-specific even then.
- **No pricing, billing codes, or turnaround SLAs** for your own lab.
- **No result validation rules** (delta checks, critical values, auto-verify).
  Critical-value alerting is yours to build and is a regulatory requirement in
  most jurisdictions.
- **Tube data for 49% of tests.** `plan.Unresolved` is not an edge case; design
  the collection UI around it being routinely non-empty.

## 7. Suggested build order

1. Mirror the catalogue and wire `Search` into order entry. Immediate value, low risk.
2. Seed panels from clinic profiles, make them editable per clinic.
3. Build the range table and the sign-off export. **Before** any flagging goes live.
4. Add `Draw` to the collection workflow, with warnings surfaced in the UI.
5. Add `Interpret` on result entry, storing `interpreted_with` from day one.
6. Map LOINC for your top tests, then build external interfacing.
