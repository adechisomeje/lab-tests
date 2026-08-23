/** Types mirroring schema/test.schema.json. */

export type Sex = 'all' | 'male' | 'female' | '';
export type AgeUnit = 'days' | 'weeks' | 'months' | 'years';
export type Flag = 'low' | 'normal' | 'high';
export type BoundOp = 'lt' | 'lte' | 'gt' | 'gte' | '';

export type TubeType =
  | 'edta'
  | 'sodium-citrate'
  | 'fluoride-oxalate'
  | 'lithium-heparin'
  | 'trace-element'
  | 'serum-gel'
  | 'plain-serum';

export interface Tube {
  type: TubeType;
  cap_colour: string;
}

export interface Volume {
  value: number;
  unit: 'mL';
}

export interface Specimen {
  types?: string[];
  specimen_type_raw?: string;
  preferred_specimen?: string;
  accepted_specimens?: string[];
  container?: string;
  tube?: Tube;
  minimum_volume_raw?: string;
  volume?: Volume;
  collection?: string;
  transport?: string;
  special_precautions?: string;
  additional_requirements?: string;
}

export interface Analysis {
  analyte?: string;
  method?: string;
  units?: string;
  reference_range?: string;
  clinical_decision_points?: string;
  interferences?: string;
  limitations?: string;
  eqa_scheme?: string;
  frequency_of_analysis?: string;
}

/** One age/sex band of a reference interval. */
export interface Stratum {
  sex?: Sex;
  age_unit?: string;
  age_min?: number | null;
  age_max?: number | null;
  low?: number | null;
  high?: number | null;
  /** Qualifies the bound. Absent means inclusive. */
  low_op?: BoundOp;
  high_op?: BoundOp;
  raw?: Record<string, string | null>;
}

export interface ReferenceIntervals {
  source?: string;
  source_url?: string;
  matched_name?: string;
  /** How this interval was linked: 'exact' | 'squashed' | 'abbreviation' | `fuzzy:${number}`. */
  match_method?: string;
  units?: string;
  notes?: string;
  strata?: Stratum[];
}

export interface DayRange {
  min: number;
  max: number;
}

export interface Turnaround {
  raw?: string;
  provisional_raw?: string;
  final_raw?: string;
  days?: DayRange;
  provisional_working_days?: DayRange;
  final_working_days?: DayRange;
}

export interface Clinical {
  indications?: string;
  interpretation?: string;
  repeat_frequency?: string;
  references?: string;
}

export interface Source {
  provider: string;
  az_url?: string;
  detail_url?: string;
  detail_type?: 'pdf' | 'page';
  detail_available?: boolean;
  department_url?: string;
  last_updated?: string;
  retrieved: string;
}

export interface Completeness {
  score: number;
  has_detail_sheet?: boolean;
  present?: string[];
}

export interface ClinicMembership {
  profile: string;
  /** True for a curated member of that setting's usual panel. */
  core: boolean;
}

export interface Test {
  id: string;
  name: string;
  aliases?: string[];
  description?: string;
  department: string;
  letter?: string;
  categories?: string[];
  clinic_profiles?: ClinicMembership[];
  specimen?: Specimen;
  analysis?: Analysis;
  reference_intervals?: ReferenceIntervals;
  turnaround?: Turnaround;
  clinical?: Clinical;
  referred_to?: string;
  notes?: string;
  source: Source;
  completeness: Completeness;
}

export interface ClinicProfile {
  id: string;
  name: string;
  description: string;
  rationale: string;
  test_ids: string[];
  core_test_ids: string[];
  test_count: number;
  core_test_count: number;
}

export interface Category {
  id: string;
  name: string;
  description: string;
  test_ids: string[];
  test_count: number;
}

/**
 * Provider-specific order of draw. Published sequences genuinely disagree, so
 * `sequence` lists only what this provider documents and `unspecified` names
 * the tubes it does not cover.
 */
export interface OrderOfDraw {
  source_url?: string;
  source_quote?: string;
  sequence: TubeType[];
  unspecified?: TubeType[];
  rationale?: string;
  conflicts_with_clsi?: boolean;
  conflict_note?: string;
}

export interface Provider {
  id: string;
  name: string;
  division?: string;
  country?: string;
  source_url?: string;
  order_of_draw?: OrderOfDraw;
  handling?: string[];
}

export interface Meta {
  name: string;
  version: string;
  description: string;
  license: string;
  generated: string;
  test_count: number;
  disclaimer: string;
}
