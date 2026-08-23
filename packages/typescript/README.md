# lab-tests (TypeScript)

Medical laboratory test catalogue: specimen requirements, turnaround times,
age/sex-stratified reference intervals, and clinic-type categorisation.

```bash
npm install lab-tests
```

```ts
import { load, years } from 'lab-tests';

const cat = load({ referenceRanges: { kind: 'provider', provider: 'mft-nhs' } });

cat.search('ferritin', 5);
cat.orderSet('aesthetic-beauty-clinic', true);   // 38 curated tests

const r = cat.interpret('alanine-aminotransferase', 62, {
  sex: 'male',
  age: years(34),
});
r.flag; // 'high'
```

**Reference intervals are opt-in.** `interpret` throws `no_range_source` until
you name a source: applying one laboratory's intervals to another's analysers
and population is a patient-safety error. In production pass
`{ kind: 'custom', ranges: yourLabRanges }`, which never falls back to provider
data.

Behaviour is pinned by the shared conformance suite in
[`conformance/vectors.json`](../../conformance/vectors.json), which the Go,
TypeScript and Python implementations all run.

Full documentation: [repository README](../../README.md) ·
[EMR integration guide](../../docs/EMR-INTEGRATION.md)

MIT licensed. Test data derives from Manchester University NHS Foundation
Trust — see [DATA-LICENSE.md](../../DATA-LICENSE.md). Not medical advice.
