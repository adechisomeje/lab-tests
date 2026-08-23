/**
 * Accent- and case-insensitive folding for search.
 *
 * Deliberately not `String.prototype.normalize('NFD')` alone: the mapping must
 * match the dataset's ID generation exactly, including "ß" -> "beta" (in this
 * corpus "ß2 Microglobulin" uses ß as a beta glyph, and the generated ID is
 * beta2-microglobulin). The conformance suite pins this behaviour.
 */
const MULTI: ReadonlyArray<readonly [string, string]> = [
  ['ß', 'beta'],
  ['æ', 'ae'],
  ['œ', 'oe'],
  ['þ', 'th'],
  ['ð', 'd'],
  ['–', '-'],
  ['—', '-'],
  ['‐', '-'],
  ['’', "'"],
  ['°', ''],
];

export function fold(input: string): string {
  let s = (input ?? '').toLowerCase().trim();
  for (const [from, to] of MULTI) s = s.split(from).join(to);
  // Strip combining marks: "müllerian" -> "mullerian".
  return s.normalize('NFD').replace(/[\u0300-\u036f]/g, '').normalize('NFC');
}
