import { readFileSync, existsSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import { LabTestsError } from './errors.js';
import { fold } from './fold.js';
import { buildDrawPlan, type DrawPlan } from './draw.js';
import {
  classify,
  selectStratum,
  type Interpretation,
  type Patient,
} from './interpret.js';
import type {
  Category,
  ClinicProfile,
  DayRange,
  Meta,
  Provider,
  ResultTemplate,
  Stratum,
  Test,
} from './types.js';

/** Where reference intervals come from. There is no default: see `load`. */
export type RangeSource =
  | { kind: 'none' }
  | { kind: 'provider'; provider: string }
  | { kind: 'custom'; ranges: Record<string, Stratum[]> };

export interface LoadOptions {
  /** Directory holding the dataset JSON. Defaults to the bundled copy. */
  dataDir?: string;
  /**
   * Reference-interval source. Omit for a catalogue-only load, in which case
   * `interpret` throws `no_range_source`.
   */
  referenceRanges?: RangeSource;
}

export interface Match {
  test: Test;
  score: number;
}

interface Dataset {
  meta: Meta;
  tests: Test[];
  profiles: Map<string, ClinicProfile>;
  categories: Map<string, Category>;
  providers: Map<string, Provider>;
  templates: Map<string, ResultTemplate>;
}

function resolveDataDir(explicit?: string): string {
  if (explicit) return explicit;
  const here = dirname(fileURLToPath(import.meta.url));
  // Published layout (dist/ next to data/), then the repo layout.
  for (const candidate of [
    join(here, '..', 'data'),
    join(here, '..', '..', 'data'),
    join(here, '..', '..', '..', 'data'),
  ]) {
    if (existsSync(join(candidate, 'tests.json'))) return candidate;
  }
  throw new Error(
    'lab-tests: could not locate the dataset; pass { dataDir } to load()',
  );
}

const readJson = <T>(dir: string, file: string): T =>
  JSON.parse(readFileSync(join(dir, file), 'utf8')) as T;

/**
 * Load the catalogue.
 *
 * Reference-interval interpretation is opt-in. Intervals in this dataset belong
 * to one provider's analysers and population; applying them to a different
 * laboratory is a patient-safety error. `interpret` therefore throws
 * `no_range_source` until you choose explicitly:
 *
 * ```ts
 * load()                                                        // catalogue only
 * load({ referenceRanges: { kind: 'provider', provider: 'mft-nhs' } })
 * load({ referenceRanges: { kind: 'custom', ranges: myLabRanges } })
 * ```
 */
export function load(opts: LoadOptions = {}): Catalogue {
  const dir = resolveDataDir(opts.dataDir);
  const testDoc = readJson<{ meta: Meta; tests: Test[] }>(dir, 'tests.json');
  const profDoc = readJson<{ profiles: ClinicProfile[] }>(dir, 'clinic-profiles.json');
  const catDoc = readJson<{ categories: Category[] }>(dir, 'categories.json');
  const provDoc = readJson<{ providers: Provider[] }>(dir, 'providers.json');
  const tplDoc = readJson<{ templates: ResultTemplate[] }>(dir, 'result-templates.json');

  const data: Dataset = {
    meta: testDoc.meta,
    tests: testDoc.tests,
    profiles: new Map(profDoc.profiles.map((p) => [p.id, p])),
    categories: new Map(catDoc.categories.map((c) => [c.id, c])),
    providers: new Map(provDoc.providers.map((p) => [p.id, p])),
    templates: new Map(tplDoc.templates.map((t) => [t.id, t])),
  };

  const ranges = opts.referenceRanges ?? { kind: 'none' as const };
  if (ranges.kind === 'provider' && !data.providers.has(ranges.provider)) {
    throw new LabTestsError('unknown_provider', `unknown provider: ${ranges.provider}`);
  }
  return new Catalogue(data, ranges);
}

/** An immutable, in-memory view of the dataset. */
export class Catalogue {
  readonly #data: Dataset;
  readonly #ranges: RangeSource;
  readonly #byId: Map<string, Test>;
  readonly #haystack: Map<string, string>;

  constructor(data: Dataset, ranges: RangeSource) {
    this.#data = data;
    this.#ranges = ranges;
    this.#byId = new Map(data.tests.map((t) => [t.id, t]));
    this.#haystack = new Map(
      data.tests.map((t) => [t.id, fold([t.name, ...(t.aliases ?? [])].join(' '))]),
    );
  }

  get meta(): Meta {
    return this.#data.meta;
  }

  tests(): Test[] {
    return [...this.#data.tests];
  }

  get(id: string): Test | undefined {
    return this.#byId.get(id);
  }

  provider(id: string): Provider | undefined {
    return this.#data.providers.get(id);
  }

  profile(id: string): ClinicProfile | undefined {
    return this.#data.profiles.get(id);
  }

  profiles(): ClinicProfile[] {
    return [...this.#data.profiles.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
  }

  /**
   * Tests a clinic profile covers. `coreOnly` returns the curated panel, which
   * is what an order set should default to; the full list is browse breadth.
   */
  orderSet(profileId: string, coreOnly = false): Test[] {
    const p = this.#data.profiles.get(profileId);
    if (!p) {
      throw new LabTestsError('unknown_profile', `unknown clinic profile: ${profileId}`);
    }
    const ids = coreOnly ? p.core_test_ids : p.test_ids;
    return ids.map((id) => this.#byId.get(id)).filter((t): t is Test => !!t);
  }

  byCategory(categoryId: string): Test[] {
    const c = this.#data.categories.get(categoryId);
    if (!c) {
      throw new LabTestsError('unknown_category', `unknown category: ${categoryId}`);
    }
    return c.test_ids.map((id) => this.#byId.get(id)).filter((t): t is Test => !!t);
  }

  /**
   * Find tests by name or alias. Case- and accent-insensitive, so "mullerian"
   * finds "Anti-Müllerian Hormone".
   */
  search(query: string, limit = 0): Match[] {
    const q = fold(query);
    if (!q) return [];

    const out: Match[] = [];
    for (const t of this.#data.tests) {
      const name = fold(t.name);
      let score = 0;
      if (name === q) score = 1;
      else if (name.startsWith(q)) score = 0.9;
      else {
        for (const a of t.aliases ?? []) {
          const fa = fold(a);
          if (fa === q) {
            score = 0.85;
            break;
          }
          if (fa.startsWith(q)) score = 0.75;
        }
        if (score === 0 && (this.#haystack.get(t.id) ?? '').includes(q)) {
          score = 0.5 - name.length / 10000;
        }
      }
      if (score > 0) out.push({ test: t, score });
    }
    out.sort((a, b) =>
      b.score !== a.score ? b.score - a.score : a.test.name < b.test.name ? -1 : 1,
    );
    return limit > 0 ? out.slice(0, limit) : out;
  }

  /**
   * The starter template seeding structured result entry for a test.
   *
   * A starting point, not a specification: copy it into your own catalogue,
   * confirm every component and unit against your analyser, and treat your
   * versioned copy as authoritative. Check `test.result_format` first --
   * narrative and document results should not be captured as fields at all.
   */
  resultTemplate(testId: string): ResultTemplate | undefined {
    return this.#byId.get(testId)?.result_template;
  }

  /**
   * A starter template by its own id. Some templates -- such as
   * `urea-and-electrolytes` -- are reusable starting points with no matching
   * test in this catalogue.
   */
  template(templateId: string): ResultTemplate | undefined {
    return this.#data.templates.get(templateId);
  }

  /** Every starter template, ordered by id. */
  templates(): ResultTemplate[] {
    return [...this.#data.templates.values()].sort((a, b) => (a.id < b.id ? -1 : 1));
  }

  /** Expected time to a final result, in days. */
  turnaround(testId: string): DayRange | undefined {
    const t = this.#byId.get(testId);
    if (!t) throw new LabTestsError('unknown_test', `unknown test: ${testId}`);
    return t.turnaround?.final_working_days ?? t.turnaround?.days;
  }

  /** Phlebotomy plan using the configured or sole provider's order of draw. */
  draw(testIds: string[]): DrawPlan {
    let providerId: string | undefined =
      this.#ranges.kind === 'provider' ? this.#ranges.provider : undefined;
    if (!providerId) {
      if (this.#data.providers.size !== 1) {
        throw new LabTestsError(
          'unknown_provider',
          'no provider selected for order of draw',
        );
      }
      providerId = [...this.#data.providers.keys()][0]!;
    }
    return this.drawFor(providerId, testIds);
  }

  /**
   * Phlebotomy plan using a named provider's order of draw.
   *
   * Order of draw is provider-specific and published sequences disagree, so the
   * plan names the provider, quotes the source, and warns where the rule
   * conflicts with CLSI or omits a tube. Follow your own laboratory's SOP.
   */
  drawFor(providerId: string, testIds: string[]): DrawPlan {
    const prov = this.#data.providers.get(providerId);
    if (!prov) {
      throw new LabTestsError('unknown_provider', `unknown provider: ${providerId}`);
    }
    return buildDrawPlan(prov, testIds.map((id) => this.#byId.get(id)), testIds);
  }

  #strataFor(t: Test): { strata: Stratum[]; attribution: string; warnings: string[] } {
    switch (this.#ranges.kind) {
      case 'none':
        throw new LabTestsError(
          'no_range_source',
          'no reference-range source configured; load with referenceRanges',
        );
      case 'custom': {
        const s = this.#ranges.ranges[t.id];
        if (!s?.length) {
          throw new LabTestsError('no_intervals', `no reference intervals for ${t.id}`);
        }
        return { strata: s, attribution: 'local laboratory reference intervals', warnings: [] };
      }
      case 'provider': {
        const ri = t.reference_intervals;
        if (!ri?.strata?.length) {
          throw new LabTestsError('no_intervals', `no reference intervals for ${t.id}`);
        }
        if (t.source.provider && t.source.provider !== this.#ranges.provider) {
          throw new LabTestsError(
            'no_intervals',
            `${t.id} belongs to provider ${t.source.provider}`,
          );
        }
        const warnings: string[] = [];
        if (ri.match_method?.startsWith('fuzzy')) {
          warnings.push(
            `reference interval was linked to this test by fuzzy name matching ` +
              `(${ri.match_method}, source name "${ri.matched_name}"); verify before clinical use`,
          );
        }
        const prov = this.#data.providers.get(this.#ranges.provider);
        return { strata: ri.strata, attribution: prov?.name ?? ri.source ?? '', warnings };
      }
    }
  }

  /**
   * Compare a numeric result with the applicable reference interval and return
   * a low/normal/high flag. Throws `no_range_source` unless a source was chosen
   * at load time.
   */
  interpret(testId: string, value: number, patient: Patient): Interpretation {
    const t = this.#byId.get(testId);
    if (!t) throw new LabTestsError('unknown_test', `unknown test: ${testId}`);

    const { strata, attribution, warnings } = this.#strataFor(t);
    const stratum = selectStratum(strata, patient);

    const out: Interpretation = {
      testId,
      value,
      flag: classify(stratum, value),
      stratum,
      attribution,
      warnings: [...warnings],
    };
    const units = t.reference_intervals?.units || t.analysis?.units;
    if (units) out.units = units;
    if (stratum.low == null && stratum.high == null) {
      out.warnings.push('matched interval has no numeric bounds; flag is not meaningful');
    }
    return out;
  }
}
