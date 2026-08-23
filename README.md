# lab-tests

An open JSON library of medical laboratory tests — what each test needs, how
long it takes, what the reference intervals are, and which kind of clinic
typically orders it.

Built so you can `fetch` a JSON file and start building, without writing your
own scraper or inventing your own taxonomy.

```
508 tests · 14 departments · 44 clinical categories · 28 clinic profiles
462 age/sex-stratified reference intervals · 131 aliases
```

> **Not medical advice.** This is reference data for building software.
> Specimen requirements and reference intervals are specific to one provider,
> one method and one population. Always confirm against your own laboratory's
> current user handbook before clinical use. See [DATA-LICENSE.md](DATA-LICENSE.md).

---

## Quick start

**Go** — the dataset is embedded, plus reference-interval resolution and draw
planning. See [Using it from Go](#using-it-from-go).

```bash
go get github.com/adechisomeje/lab-tests
```

```go
cat, _ := labtests.Load(labtests.WithProviderRanges("mft-nhs"))

set, _ := cat.OrderSet("aesthetic-beauty-clinic", true)   // 38 curated tests
r, _ := cat.Interpret("alanine-aminotransferase", 62, labtests.Patient{
    Sex: labtests.SexMale, Age: labtests.Years(34),
})
fmt.Println(r.Flag)                                       // high
```

**JavaScript**

```bash
npm install lab-tests
```

```js
import { tests } from 'lab-tests';                    // full library
import { profiles } from 'lab-tests/clinics';         // clinic profiles

const beauty = profiles.find(p => p.id === 'aesthetic-beauty-clinic');
console.log(beauty.core_test_count);                  // 38
```

**Any language** — it is just JSON. No install, no build step:

```js
const { tests } = await fetch(
  'https://raw.githubusercontent.com/adechisomeje/lab-tests/main/data/tests.json'
).then(r => r.json());
```

```python
import json, urllib.request
url = "https://raw.githubusercontent.com/adechisomeje/lab-tests/main/data/tests.json"
tests = json.load(urllib.request.urlopen(url))["tests"]
```

---

## What a record looks like

```json
{
  "id": "alanine-aminotransferase",
  "name": "Alanine Aminotransferase",
  "department": "Biochemistry",
  "categories": [
    "liver-function"
  ],
  "clinic_profiles": [
    {
      "profile": "general-practice",
      "core": false
    },
    {
      "profile": "gastroenterology-hepatology",
      "core": false
    }
  ],
  "specimen": {
    "types": [
      "heparinised-plasma",
      "serum"
    ],
    "preferred_specimen": "Plain serum",
    "accepted_specimens": [
      "Plain serum",
      "gel serum",
      "lithium heparin plasma"
    ],
    "tube": {
      "type": "plain-serum",
      "cap_colour": "Red"
    }
  },
  "analysis": {
    "units": "IU/L",
    "reference_range": "<= 90 IU/L (adult; 3 age/sex strata available)"
  },
  "reference_intervals": {
    "matched_name": "Alanine aminotransferase (ALT)",
    "match_method": "exact",
    "strata": [
      {
        "sex": "all",
        "age_unit": "days",
        "age_min": 0.0,
        "age_max": 28.0,
        "high": 90.0,
        "high_op": "lte"
      },
      {
        "sex": "female",
        "age_unit": "days",
        "age_min": 29.0,
        "high": 35.0,
        "high_op": "lte"
      },
      {
        "sex": "male",
        "age_unit": "days",
        "age_min": 29.0,
        "high": 50.0,
        "high_op": "lte"
      }
    ]
  },
  "turnaround": {
    "raw": "4 hours",
    "days": {
      "min": 0.17,
      "max": 0.17
    }
  },
  "source": {
    "retrieved": "2026-08-23"
  },
  "completeness": {
    "score": 0.45,
    "has_detail_sheet": false
  }
}
```

Full field documentation: [`schema/test.schema.json`](schema/test.schema.json).

---

## Categorising tests

Two independent axes, because "what kind of test is this?" and "who orders it?"
are different questions.

### 1. Clinical categories — *what the test is*

44 domain tags in [`taxonomy/categories.json`](taxonomy/categories.json):
`liver-function`, `thyroid`, `coagulation`, `tumour-markers`,
`neurology-antibodies`, `nutrition-micronutrients`, … A test can hold several.

```js
const thyroid = tests.filter(t => t.categories.includes('thyroid'));
```

### 2. Clinic profiles — *who orders it*

28 practice settings in [`taxonomy/clinic-profiles.json`](taxonomy/clinic-profiles.json).
This is the axis for "a beauty clinic will need these tests".

Each membership is flagged `core` or not:

- **`core: true`** — curated, high-signal. This test genuinely belongs to that
  setting's usual panel.
- **`core: false`** — swept in by a broader category rule. Plausible, but
  wider. Use for browse/discovery, not for a default order set.

```js
// The 38 tests an aesthetic clinic actually runs
const beautyCore = tests.filter(t =>
  t.clinic_profiles.some(p => p.profile === 'aesthetic-beauty-clinic' && p.core)
);
```

Or grab the pre-built slice: [`data/by-clinic/aesthetic-beauty-clinic.json`](data/by-clinic/aesthetic-beauty-clinic.json).

<details>
<summary><strong>All 28 clinic profiles</strong></summary>

| Profile | Tests | Core |
| --- | --- | --- |
| `general-practice` | 105 | 37 |
| `womens-health-gynaecology` | 67 | 18 |
| `longevity-wellness` | 55 | 49 |
| `endocrinology-clinic` | 57 | 0 |
| `gastroenterology-hepatology` | 53 | 15 |
| `sexual-health-gum` | 51 | 16 |
| `aesthetic-beauty-clinic` | 50 | 38 |
| `weight-management-metabolic` | 49 | 44 |
| `nephrology-renal` | 48 | 13 |
| `neurology-clinic` | 45 | 0 |
| `antenatal-maternity` | 40 | 35 |
| `dermatology-clinic` | 40 | 25 |
| `critical-care-emergency` | 39 | 37 |
| `sports-performance` | 38 | 38 |
| `fertility-reproductive` | 32 | 31 |
| `allergy-clinic` | 31 | 0 |
| `oncology-haematology` | 28 | 8 |
| `pre-operative-assessment` | 27 | 27 |
| `cardiology-clinic` | 24 | 24 |
| `occupational-health` | 24 | 24 |
| `transplant-clinic` | 24 | 12 |
| `travel-clinic` | 22 | 17 |
| `paediatrics` | 21 | 21 |
| `drug-alcohol-services` | 18 | 14 |
| `rheumatology-clinic` | 67 | 4 |
| `infectious-disease-clinic` | 162 | 0 |
| `microbiology-infection-control` | 68 | 4 |
| `haematology-clinic` | 67 | 10 |

</details>

**These groupings are editorial, not clinical guidance.** They are keyword rules
in plain JSON — read them, disagree with them, send a PR. That is the point of
keeping them as data rather than burying them in code.

---

## Files

| File | What it is |
| --- | --- |
| `data/tests.json` | The library. Every test, every field. (1.2 MB) |
| `data/index.json` | Names, aliases, department, categories only — for search boxes. (141 KB) |
| `data/categories.json` | 44 clinical categories with member test ids |
| `data/clinic-profiles.json` | 28 clinic profiles with member + core test ids |
| `data/departments.json` | 14 performing departments |
| `data/specimens.json` | Specimen-type roll-up |
| `data/by-department/*.json` | Per-department slices (14 files) |
| `data/by-clinic/*.json` | Per-clinic slices (28 files) |
| `schema/test.schema.json` | JSON Schema (draft 2020-12) for a test record |
| `taxonomy/*.json` | The category and clinic rules — edit these to reclassify |
| `data/providers.json` | Per-provider collection guidance, incl. order of draw |
| `*.go` | Go package: `Interpret`, `Draw`, `Search`, `OrderSet` |
| `docs/EMR-INTEGRATION.md` | Building a lab module on this: schema, seeding, safety |

---

## Using it from Go

A Go package ships alongside the data, with the dataset embedded — no runtime
file or network dependency.

```bash
go get github.com/adechisomeje/lab-tests
```

It provides the three things that are genuinely awkward to reimplement:
reference-interval resolution, tube consolidation, and alias-aware search.
Everything else is a slice filter and needs no library.

### Reference intervals are opt-in, deliberately

`Interpret` returns `ErrNoRangeSource` until you explicitly choose where
intervals come from. Applying one laboratory's intervals to another's analysers
and population is a patient-safety error, so the API will not do it by default.

```go
cat, _ := labtests.Load()                                  // catalogue only
cat, _ := labtests.Load(labtests.WithProviderRanges("mft-nhs"))
cat, _ := labtests.Load(labtests.WithCustomRanges(myLabRanges))  // production
```

`WithCustomRanges` never falls back to provider data: a test absent from your
map returns `ErrNoIntervals` rather than quietly using someone else's numbers.

### Interpreting a result

Resolution handles mixed age units (`days`/`weeks`/`months`/`years`), picks the
narrowest applicable band, and honours bound operators — `≤50` and `<50` differ
at exactly 50.

```go
r, err := cat.Interpret("alanine-aminotransferase", 62, labtests.Patient{
    Sex: labtests.SexMale,
    Age: labtests.Years(34),
})
// r.Flag == labtests.FlagHigh   (male adult limit 50 IU/L)
// r.Units, r.Stratum, r.Attribution, r.Warnings
```

Same value, three patients:

| Patient | Applied band | Flag |
| --- | --- | --- |
| Male, 34y | ≤ 50 IU/L | `high` |
| Female, 34y | ≤ 35 IU/L | `high` |
| Male, 10 days | ≤ 90 IU/L | `normal` |

It refuses rather than guesses. Unknown sex against a sex-specific band, or
unknown age against a banded interval, returns `ErrNoApplicableStratum`. If an
interval was linked to its test by fuzzy name matching, `r.Warnings` says so.

### Building a draw plan

```go
plan, _ := cat.Draw([]string{"ammonia", "lactate", "ferritin"})
for _, tube := range plan.Tubes {
    fmt.Println(tube.Position, tube.Type, tube.CapColour, len(tube.Tests))
}
// 1 serum-gel        Gold / yellow (SST)
// 2 fluoride-oxalate Grey
// 3 edta             Purple / lavender
```

**Order of draw is provider-specific and published sequences genuinely
disagree.** MFT documents serum → lithium heparin → fluoride → **EDTA last**;
the CLSI H3-A6 consensus order places citrate first and fluoride/oxalate last —
the reverse for those two tubes. Neither is universally correct.

So `Draw` reports whose rule it applied, quotes the source statement in
`plan.OrderSource`, and warns via `plan.Warnings` when the rule conflicts with
CLSI or does not cover a tube in the plan. Tubes the provider does not document
are placed last and flagged, never silently positioned. **Follow your own
laboratory's SOP.**

Tests with no published tube requirement are returned in `plan.Unresolved`
rather than dropped.

### Search and order sets

```go
cat.Search("mullerian", 5)                          // finds Anti-Müllerian Hormone
cat.OrderSet("aesthetic-beauty-clinic", true)       // 38 curated core tests
cat.ByCategory("thyroid")
cat.SlowestTurnaround(ids)                          // when to expect the report
```

Run `go run ./examples/quickstart` for a working end-to-end demo.

### Building an EMR laboratory module

**[docs/EMR-INTEGRATION.md](docs/EMR-INTEGRATION.md)** covers the full
integration: the database schema to mirror the catalogue into, seeding and
version pinning, wiring your own reference ranges as the override layer, and
the four workflow touchpoints (order entry, collection, result entry, display).
It is explicit about what the dataset does *not* give you — no LOINC codes, no
critical-value rules — so you can scope around the gaps.

`go run ./examples/emr` is a compile-checked version of every code snippet in
that guide.

---

## Running it as an API

A zero-dependency Node server is included:

```bash
npm run api
```

```
GET /tests?q=ferritin&limit=10
GET /tests?clinic=aesthetic-beauty-clinic&core=true
GET /tests?category=thyroid&specimen=serum
GET /tests/alanine-aminotransferase
GET /categories · /categories/:id
GET /clinics    · /clinics/:id?core=true
GET /departments · /specimens
```

Everything is loaded into memory at boot and served read-only, so it deploys
anywhere Node runs. Search is accent-insensitive (`mullerian` finds
*Anti-Müllerian Hormone*).

---

## Coverage, honestly

This is one provider's catalogue, deeply parsed — not "every lab test in the
world". It is a strong, real seed, and the schema is source-agnostic so more
providers can be added.

| | Coverage |
| --- | --- |
| Specimen type | 308 / 508 (61%) |
| Tube & cap colour | 249 / 508 (49%) |
| Turnaround time | 311 / 508 (61%) |
| Reference intervals | 86 / 508 (17%) |
| Clinical indications | 69 / 508 (14%) |
| Any detail sheet | 212 / 508 (42%) |

Depth varies because the source varies: 212 tests have a full PDF spec sheet,
and Biochemistry analytes get stratified reference intervals from the trust's
reference-range document. The rest carry name, aliases, department and
categorisation only.

Every record has `completeness.score` (0–1) so you can filter:

```js
const detailed = tests.filter(t => t.completeness.score >= 0.5);
```

### Where the data links are heuristic

Reference intervals come from a separate document, so records are linked by
name. Each link records **how** it was made in `reference_intervals.match_method`:

| Method | Count | Trust |
| --- | --- | --- |
| `exact` | 92 | Names match after normalisation |
| `abbreviation` | 8 | Matched via parenthetical abbreviation |
| `squashed` | 2 | Matched ignoring separators (`NT-proBNP` → `NTproBNP`) |
| `fuzzy:<score>` | 15 | Token overlap — **all 25 non-exact links were manually reviewed** |

Matching is deliberately conservative: it would rather leave a test unlinked
than link it wrongly. `Glucose` is left unlinked because the source has six
glucose variants and guessing would be worse than nothing.

---

## Rebuilding from source

```bash
make refresh     # fetch from mft.nhs.uk, rebuild, validate
make build       # rebuild from cached sources in raw/
make validate    # schema + referential integrity
```

Requires Python 3.10+, `pymupdf`, and optionally `jsonschema` and `certifi`.

```
scripts/
  fetch_az.py             download the A-Z page
  parse_az_list.py        A-Z tables      -> raw/az-rows.json
  fetch_pdfs.py           download 212 spec sheets (rate-limited, resumable)
  parse_pdfs.py           spec sheets     -> raw/pdf-fields.json
  parse_biochem_ranges.py 45-page table   -> raw/biochem-ranges.json
  match.py                fuzzy test-name matching between documents
  build.py                merge + categorise -> data/
  validate.py             schema + integrity checks (exits non-zero on error)
```

Scraping is polite by default: 4 workers, a delay between requests, and every
step is cached and resumable, so a rerun re-downloads nothing.

---

## Contributing

The highest-value contributions:

1. **Another provider.** The schema supports multiple sources — `meta.sources`
   is a list and every record names its own `source.provider`.
2. **Better taxonomy rules.** Edit `taxonomy/*.json`, run `make build`, and the
   diff shows exactly which tests moved.
3. **Coding systems.** LOINC / SNOMED CT codes per test would make this
   interoperable with real clinical systems. Not present today.

Run `make validate` before opening a PR — it exits non-zero on any schema or
referential error.

---

## Licence

Code MIT · taxonomy CC-BY-4.0 · underlying test data from Manchester University
NHS Foundation Trust. Full provenance and attribution requirements in
[DATA-LICENSE.md](DATA-LICENSE.md).
