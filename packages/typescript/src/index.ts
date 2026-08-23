export { load, Catalogue } from './catalogue.js';
export type { LoadOptions, RangeSource, Match } from './catalogue.js';
export { LabTestsError, isLabTestsError } from './errors.js';
export type { ErrorCode } from './errors.js';
export { fold } from './fold.js';
export { classify, appliesTo, selectStratum, years, months, weeks, days } from './interpret.js';
export type { Age, Patient, Interpretation } from './interpret.js';
export type { DrawPlan, DrawTube } from './draw.js';
export type * from './types.js';
