# Data provenance and licensing

## Where this data comes from

Every record in `data/` is derived from material published openly by
**Manchester University NHS Foundation Trust (MFT), Division of Laboratory Medicine**:

| Source | What it provides |
| --- | --- |
| [A-Z list of laboratory tests](https://mft.nhs.uk/the-trust/other-departments/laboratory-medicine/a-z-list-of-laboratory-tests/) | Test names, synonyms, performing department |
| Per-test PDF spec sheets (212 documents linked from the A-Z list) | Specimen type, container, volume, transport, method, turnaround, indications |
| [Biochemistry reference ranges](https://mft.nhs.uk/app/uploads/2026/06/Biochemistry-reference-ranges-240626.pdf) (BC-CL-G-50) | Age- and sex-stratified reference intervals, sample types, turnaround |

Each record carries its own `source` block with the exact URL it came from and
the date it was retrieved, so any value can be traced back and re-checked.

## Licence

- **Code** (everything in `scripts/`, `api/`) — MIT, see [LICENSE](LICENSE).
- **Taxonomy** (`taxonomy/`, `schema/`) — original work of this project,
  CC-BY-4.0. The clinical categories and clinic profiles are editorial
  judgements made here, not published by MFT.
- **Underlying test data** — sourced from NHS material. UK public sector
  information of this kind is typically covered by the
  [Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/),
  which permits reuse with attribution, but MFT has not published an explicit
  licence statement on these pages. If you are redistributing commercially,
  confirm terms with MFT directly.

Attribute as: *"Laboratory test data derived from Manchester University NHS
Foundation Trust, Division of Laboratory Medicine."*

## Not medical advice

This dataset is informational. Specimen requirements, reference intervals and
turnaround times are **specific to one provider, one method and one
population**. A reference interval from MFT's analysers is not transferable to
another laboratory. Always confirm against your own laboratory's current user
handbook before any clinical use.

The `categories` and `clinic_profiles` groupings are heuristic aids for
building software. They are not clinical guidelines, care pathways, or
recommendations about which tests to order.
