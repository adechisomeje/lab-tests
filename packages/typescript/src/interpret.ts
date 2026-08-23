import { LabTestsError } from './errors.js';
import type { AgeUnit, Flag, Sex, Stratum } from './types.js';

/** A patient age. Omit it entirely when unknown. */
export interface Age {
  value: number;
  unit: AgeUnit;
}

export const years = (v: number): Age => ({ value: v, unit: 'years' });
export const months = (v: number): Age => ({ value: v, unit: 'months' });
export const weeks = (v: number): Age => ({ value: v, unit: 'weeks' });
export const days = (v: number): Age => ({ value: v, unit: 'days' });

export interface Patient {
  sex?: Sex;
  /** Omit when the patient's age is unknown. */
  age?: Age;
}

export interface Interpretation {
  testId: string;
  value: number;
  units?: string;
  flag: Flag;
  /** The age/sex band that was applied. */
  stratum: Stratum;
  /** Where the interval came from, for display and audit. */
  attribution: string;
  /** Anything a clinical user must know before trusting this result. */
  warnings: string[];
}

const DAYS_PER_YEAR = 365.25;
const DAYS_PER_MONTH = 30.4375;
const DAYS_PER_WEEK = 7;

function ageInDays(age: Age | undefined): number | undefined {
  if (!age) return undefined;
  switch (age.unit) {
    case 'years':
      return age.value * DAYS_PER_YEAR;
    case 'months':
      return age.value * DAYS_PER_MONTH;
    case 'weeks':
      return age.value * DAYS_PER_WEEK;
    case 'days':
      return age.value;
    default:
      return undefined;
  }
}

/**
 * Days per unit for a stratum's declared age unit. Returns undefined when the
 * unit is absent or ambiguous -- the source contains a few entries such as
 * "days to years" -- in which case the band must be refused, not applied.
 */
function stratumUnitDays(unit: string | undefined): number | undefined {
  switch ((unit ?? '').trim().toLowerCase()) {
    case 'year':
    case 'years':
    case 'yr':
    case 'yrs':
    case 'y':
      return DAYS_PER_YEAR;
    case 'month':
    case 'months':
    case 'mth':
    case 'mths':
      return DAYS_PER_MONTH;
    case 'week':
    case 'weeks':
    case 'wk':
    case 'wks':
      return DAYS_PER_WEEK;
    case 'day':
    case 'days':
    case 'd':
      return 1;
    default:
      return undefined;
  }
}

/** The source writes both "<14" (exclusive) and "28" (inclusive). */
function exclusiveUpper(s: Stratum): boolean {
  const raw = s.raw?.['age_max'];
  return typeof raw === 'string' && raw.trim().startsWith('<');
}

/**
 * Whether a stratum covers this patient, and how specific the match is.
 * Higher specificity wins when several bands apply.
 */
export function appliesTo(
  s: Stratum,
  p: Patient,
): { ok: boolean; specificity: number } {
  let specificity = 0;

  const sex = s.sex ?? '';
  if (sex !== '' && sex !== 'all') {
    if (!p.sex || p.sex !== sex) return { ok: false, specificity: 0 };
    specificity += 2;
  }

  const hasBand = s.age_min != null || s.age_max != null;
  if (!hasBand) return { ok: true, specificity };

  const unitDays = stratumUnitDays(s.age_unit);
  if (unitDays === undefined) {
    // Bounds we cannot interpret must never be treated as universally valid.
    return { ok: false, specificity: 0 };
  }

  const patientDays = ageInDays(p.age);
  if (patientDays === undefined) return { ok: false, specificity: 0 };

  if (s.age_min != null && patientDays < s.age_min * unitDays) {
    return { ok: false, specificity: 0 };
  }
  if (s.age_max != null) {
    const hi = s.age_max * unitDays;
    if (exclusiveUpper(s) ? patientDays >= hi : patientDays > hi) {
      return { ok: false, specificity: 0 };
    }
  }

  specificity += 1;
  if (s.age_min != null && s.age_max != null) {
    const span = (s.age_max - s.age_min) * unitDays;
    if (span > 0) specificity += 1 / (1 + span); // prefer the narrowest band
  }
  return { ok: true, specificity };
}

/**
 * Compare a value with a stratum's bounds, honouring the bound operators:
 * "<= 50" and "< 50" differ at exactly 50.
 */
export function classify(s: Stratum, v: number): Flag {
  if (s.high != null) {
    if (s.high_op === 'lt' ? v >= s.high : v > s.high) return 'high';
  }
  if (s.low != null) {
    if (s.low_op === 'gt' ? v <= s.low : v < s.low) return 'low';
  }
  return 'normal';
}

/** Select the most specific applicable stratum. */
export function selectStratum(strata: Stratum[], p: Patient): Stratum {
  let best: Stratum | undefined;
  let bestScore = -Infinity;
  for (const s of strata) {
    const { ok, specificity } = appliesTo(s, p);
    if (ok && specificity > bestScore) {
      best = s;
      bestScore = specificity;
    }
  }
  if (!best) {
    throw new LabTestsError(
      'no_applicable_stratum',
      'no reference interval applies to this patient',
    );
  }
  return best;
}
