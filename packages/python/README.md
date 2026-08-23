# lab-tests (Python)

Medical laboratory test catalogue: specimen requirements, turnaround times,
age/sex-stratified reference intervals, and clinic-type categorisation.

```bash
pip install lab-tests
```

```python
import lab_tests as lt

cat = lt.load(provider_ranges="mft-nhs")

cat.search("ferritin", 5)
cat.order_set("aesthetic-beauty-clinic", core_only=True)   # 38 curated tests

r = cat.interpret("alanine-aminotransferase", 62,
                  lt.Patient(sex="male", age=lt.years(34)))
r.flag  # 'high'
```

**Reference intervals are opt-in.** `interpret` raises `NoRangeSourceError`
until you name a source: applying one laboratory's intervals to another's
analysers and population is a patient-safety error. In production pass
`custom_ranges=your_lab_ranges`, which never falls back to provider data.

Behaviour is pinned by the shared conformance suite in
[`conformance/vectors.json`](../../conformance/vectors.json), which the Go,
TypeScript and Python implementations all run.

Full documentation: [repository README](../../README.md) ·
[EMR integration guide](../../docs/EMR-INTEGRATION.md)

MIT licensed. Test data derives from Manchester University NHS Foundation
Trust — see [DATA-LICENSE.md](../../DATA-LICENSE.md). Not medical advice.
