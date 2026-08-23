/**
 * Error codes are the language-neutral names used by the conformance suite in
 * conformance/vectors.json, so behaviour can be compared across ports.
 */
export type ErrorCode =
  | 'no_range_source'
  | 'unknown_test'
  | 'no_intervals'
  | 'no_applicable_stratum'
  | 'unknown_profile'
  | 'unknown_provider'
  | 'unknown_category';

export class LabTestsError extends Error {
  constructor(
    readonly code: ErrorCode,
    message: string,
  ) {
    super(message);
    this.name = 'LabTestsError';
  }
}

export const isLabTestsError = (e: unknown): e is LabTestsError =>
  e instanceof LabTestsError;
