package labtests

// Types mirror schema/test.schema.json. Optional numeric fields are pointers so
// "absent" is distinguishable from "zero" -- a reference limit of 0 is a real
// value and must not be confused with a missing one.

type Sex string

const (
	SexAll     Sex = "all"
	SexMale    Sex = "male"
	SexFemale  Sex = "female"
	SexUnknown Sex = ""
)

// AgeUnit is the unit a caller expresses a patient's age in.
type AgeUnit string

const (
	UnitDays   AgeUnit = "days"
	UnitWeeks  AgeUnit = "weeks"
	UnitMonths AgeUnit = "months"
	UnitYears  AgeUnit = "years"
)

// TubeType identifies a collection tube. Cap colours follow UK convention.
type TubeType string

const (
	TubeEDTA            TubeType = "edta"
	TubeSodiumCitrate   TubeType = "sodium-citrate"
	TubeFluorideOxalate TubeType = "fluoride-oxalate"
	TubeLithiumHeparin  TubeType = "lithium-heparin"
	TubeTraceElement    TubeType = "trace-element"
	TubeSerumGel        TubeType = "serum-gel"
	TubePlainSerum      TubeType = "plain-serum"
)

type Test struct {
	ID                 string              `json:"id"`
	Name               string              `json:"name"`
	Aliases            []string            `json:"aliases"`
	Description        string              `json:"description"`
	Department         string              `json:"department"`
	Letter             string              `json:"letter"`
	Categories         []string            `json:"categories"`
	ClinicProfiles     []ClinicMembership  `json:"clinic_profiles"`
	Specimen           Specimen            `json:"specimen"`
	Analysis           Analysis            `json:"analysis"`
	ReferenceIntervals *ReferenceIntervals `json:"reference_intervals"`
	Turnaround         Turnaround          `json:"turnaround"`
	Clinical           Clinical            `json:"clinical"`
	ReferredTo         string              `json:"referred_to"`
	Notes              string              `json:"notes"`
	Source             Source              `json:"source"`
	Completeness       Completeness        `json:"completeness"`
}

type ClinicMembership struct {
	Profile string `json:"profile"`
	// Core marks a curated member of that setting's usual panel. Non-core
	// members were swept in by a broader category rule.
	Core bool `json:"core"`
}

type Specimen struct {
	Types                  []string `json:"types"`
	SpecimenTypeRaw        string   `json:"specimen_type_raw"`
	PreferredSpecimen      string   `json:"preferred_specimen"`
	AcceptedSpecimens      []string `json:"accepted_specimens"`
	Container              string   `json:"container"`
	Tube                   *Tube    `json:"tube"`
	MinimumVolumeRaw       string   `json:"minimum_volume_raw"`
	Volume                 *Volume  `json:"volume"`
	Collection             string   `json:"collection"`
	Transport              string   `json:"transport"`
	SpecialPrecautions     string   `json:"special_precautions"`
	AdditionalRequirements string   `json:"additional_requirements"`
}

type Tube struct {
	Type      TubeType `json:"type"`
	CapColour string   `json:"cap_colour"`
}

type Volume struct {
	Value float64 `json:"value"`
	Unit  string  `json:"unit"` // always "mL"
}

type Analysis struct {
	Analyte                string `json:"analyte"`
	Method                 string `json:"method"`
	Units                  string `json:"units"`
	ReferenceRange         string `json:"reference_range"`
	ClinicalDecisionPoints string `json:"clinical_decision_points"`
	Interferences          string `json:"interferences"`
	Limitations            string `json:"limitations"`
	EQAScheme              string `json:"eqa_scheme"`
	FrequencyOfAnalysis    string `json:"frequency_of_analysis"`
}

type ReferenceIntervals struct {
	Source      string `json:"source"`
	SourceURL   string `json:"source_url"`
	MatchedName string `json:"matched_name"`
	// MatchMethod records how this interval was linked to the test:
	// "exact", "squashed", "abbreviation", or "fuzzy:<score>".
	MatchMethod string    `json:"match_method"`
	Units       string    `json:"units"`
	Notes       string    `json:"notes"`
	Strata      []Stratum `json:"strata"`
}

// Stratum is one age/sex band of a reference interval.
type Stratum struct {
	Sex     Sex      `json:"sex"`
	AgeUnit string   `json:"age_unit"`
	AgeMin  *float64 `json:"age_min"`
	AgeMax  *float64 `json:"age_max"`
	Low     *float64 `json:"low"`
	High    *float64 `json:"high"`
	// LowOp/HighOp qualify the bound: "lt", "lte", "gt", "gte".
	// Empty means the bound is inclusive.
	LowOp  string             `json:"low_op"`
	HighOp string             `json:"high_op"`
	Raw    map[string]*string `json:"raw"`
}

type Turnaround struct {
	Raw                    string    `json:"raw"`
	ProvisionalRaw         string    `json:"provisional_raw"`
	FinalRaw               string    `json:"final_raw"`
	Days                   *DayRange `json:"days"`
	ProvisionalWorkingDays *DayRange `json:"provisional_working_days"`
	FinalWorkingDays       *DayRange `json:"final_working_days"`
}

type DayRange struct {
	Min float64 `json:"min"`
	Max float64 `json:"max"`
}

type Clinical struct {
	Indications     string `json:"indications"`
	Interpretation  string `json:"interpretation"`
	RepeatFrequency string `json:"repeat_frequency"`
	References      string `json:"references"`
}

type Source struct {
	Provider        string `json:"provider"`
	AZURL           string `json:"az_url"`
	DetailURL       string `json:"detail_url"`
	DetailType      string `json:"detail_type"`
	DetailAvailable *bool  `json:"detail_available"`
	LastUpdated     string `json:"last_updated"`
	Retrieved       string `json:"retrieved"`
}

type Completeness struct {
	Score          float64  `json:"score"`
	HasDetailSheet bool     `json:"has_detail_sheet"`
	Present        []string `json:"present"`
}

type ClinicProfile struct {
	ID            string   `json:"id"`
	Name          string   `json:"name"`
	Description   string   `json:"description"`
	Rationale     string   `json:"rationale"`
	TestIDs       []string `json:"test_ids"`
	CoreTestIDs   []string `json:"core_test_ids"`
	TestCount     int      `json:"test_count"`
	CoreTestCount int      `json:"core_test_count"`
}

type Category struct {
	ID          string   `json:"id"`
	Name        string   `json:"name"`
	Description string   `json:"description"`
	TestIDs     []string `json:"test_ids"`
	TestCount   int      `json:"test_count"`
}

type Provider struct {
	ID          string       `json:"id"`
	Name        string       `json:"name"`
	Division    string       `json:"division"`
	Country     string       `json:"country"`
	SourceURL   string       `json:"source_url"`
	OrderOfDraw *OrderOfDraw `json:"order_of_draw"`
	Handling    []string     `json:"handling"`
}

// OrderOfDraw is provider-specific and published sequences genuinely disagree.
// Sequence lists only the tubes this provider documents; Unspecified names the
// tubes it does not cover, which DrawPlan surfaces as warnings rather than
// silently guessing a position.
type OrderOfDraw struct {
	SourceURL         string     `json:"source_url"`
	SourceQuote       string     `json:"source_quote"`
	Sequence          []TubeType `json:"sequence"`
	Unspecified       []TubeType `json:"unspecified"`
	Rationale         string     `json:"rationale"`
	ConflictsWithCLSI bool       `json:"conflicts_with_clsi"`
	ConflictNote      string     `json:"conflict_note"`
}
