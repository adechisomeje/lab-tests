# Conformance suite

`vectors.json` is the behavioural contract shared by every implementation of
this library. Go, TypeScript and Python all run it, and any new port must too.

## Why this exists

`interpret()` decides whether a patient's result is flagged abnormal. Hand-porting
that to N languages is N chances to introduce a divergence that nobody notices:
one port treats `<14` as inclusive, another as exclusive, and the two disagree
about a 14-day-old's reference range.

Expected values here are derived from the **published source data**, not from
any one implementation. A port cannot pass merely by agreeing with another
port's bug.

It has already earned its keep: it caught Go folding `ß` to `ss` while the
dataset's ID generator folded it to `beta`, so a search for "beta2 microglobulin"
could not find `beta2-microglobulin`.

## Structure

| Group | Covers |
| --- | --- |
| `fold` | Search normalisation: case, accents, Greek and multi-character glyphs |
| `classify` | Bound operators in isolation — `<= 50` vs `< 50` at exactly 50 |
| `interpret` | Full resolution: band selection, age units, safety refusals |
| `draw` | Tube grouping, provider order of draw, warnings, unresolved tests |
| `search` | Ranking and accent-insensitivity |
| `order_set` | Clinic profile membership, core vs. full |

Cases named `SAFETY:` encode a refusal. They assert the library declines to
answer rather than guessing, and they are the ones to look at first when a port
fails.

Errors are compared as **language-neutral codes**, listed in `error_codes`, so
each port maps them onto its own idiom — Go sentinel errors, a TypeScript
`LabTestsError.code`, a Python exception class.

## Running it

```bash
go test -run TestConformance ./...                 # Go
npm test --workspace lab-tests                      # TypeScript
python3 -m pytest packages/python/tests -q          # Python
```

## Adding a port

1. Implement `fold`, `classify` and stratum selection first — everything else
   builds on them, and the first two groups of vectors will tell you quickly
   whether you have them right.
2. Map the neutral error codes onto your language's idiom.
3. Write a runner that iterates the vectors rather than restating them. A
   hand-copied expectation drifts; a loop cannot.
4. Keep `dataset_version` checked. A port silently running against a different
   dataset than the vectors target will produce confusing failures.

Changing an expected value means changing the contract for every port. Do it
only when the published source data says the current expectation is wrong, and
say so in the commit message.
