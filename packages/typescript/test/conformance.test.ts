import { test } from 'node:test';
import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';

import {
  load,
  fold,
  classify,
  isLabTestsError,
  type ErrorCode,
  type Patient,
  type RangeSource,
  type Stratum,
} from '../dist/index.js';

const HERE = dirname(fileURLToPath(import.meta.url));
const REPO = join(HERE, '..', '..', '..');
const vectors = JSON.parse(
  readFileSync(join(REPO, 'conformance', 'vectors.json'), 'utf8'),
);

/** Run fn and return the neutral error code it raised, or '' on success. */
function codeOf(fn: () => unknown): string {
  try {
    fn();
    return '';
  } catch (e) {
    return isLabTestsError(e) ? e.code : `other:${String(e)}`;
  }
}

function rangeSource(spec: string, custom?: Record<string, Stratum[]>): RangeSource {
  if (spec === 'custom') return { kind: 'custom', ranges: custom ?? {} };
  if (spec?.startsWith('provider:')) {
    return { kind: 'provider', provider: spec.slice('provider:'.length) };
  }
  return { kind: 'none' };
}

test('dataset version matches the vectors', () => {
  assert.equal(load().meta.version, vectors.dataset_version);
});

test('fold', () => {
  for (const tc of vectors.fold) {
    assert.equal(fold(tc.in), tc.out, `fold(${JSON.stringify(tc.in)})`);
  }
});

test('classify', () => {
  for (const tc of vectors.classify) {
    const s: Stratum = {
      low: tc.low ?? null,
      high: tc.high ?? null,
      low_op: tc.low_op ?? '',
      high_op: tc.high_op ?? '',
    };
    assert.equal(classify(s, tc.value), tc.expect, tc.name);
  }
});

test('interpret', () => {
  for (const tc of vectors.interpret) {
    const cat = load({ referenceRanges: rangeSource(tc.ranges, tc.custom_ranges) });
    const patient: Patient = {
      sex: tc.patient?.sex ?? '',
      ...(tc.patient?.age
        ? { age: { value: tc.patient.age.value, unit: tc.patient.age.unit } }
        : {}),
    };

    if (tc.expect_error) {
      const got = codeOf(() => cat.interpret(tc.test_id, tc.value, patient));
      assert.equal(got, tc.expect_error as ErrorCode, tc.name);
      continue;
    }

    const r = cat.interpret(tc.test_id, tc.value, patient);
    const e = tc.expect;
    if (e.flag) assert.equal(r.flag, e.flag, `${tc.name}: flag`);
    if (e.stratum_high != null) {
      assert.equal(r.stratum.high, e.stratum_high, `${tc.name}: stratum high`);
    }
    if (e.stratum_low != null) {
      assert.equal(r.stratum.low, e.stratum_low, `${tc.name}: stratum low`);
    }
    if (e.units) assert.equal(r.units, e.units, `${tc.name}: units`);
    if (e.warns) assert.ok(r.warnings.length > 0, `${tc.name}: expected a warning`);
  }
});

test('draw', () => {
  const cat = load();
  for (const tc of vectors.draw) {
    if (tc.expect_error) {
      assert.equal(codeOf(() => cat.drawFor(tc.provider, tc.test_ids)), tc.expect_error, tc.name);
      continue;
    }
    const plan = cat.drawFor(tc.provider, tc.test_ids);
    assert.deepEqual(
      plan.tubes.map((t) => t.type),
      tc.expect_tube_order,
      `${tc.name}: tube order`,
    );
    plan.tubes.forEach((t, i) => assert.equal(t.position, i + 1, `${tc.name}: position`));
    if (tc.expect_min_warnings != null) {
      assert.ok(
        plan.warnings.length >= tc.expect_min_warnings,
        `${tc.name}: warnings ${plan.warnings.length} < ${tc.expect_min_warnings}`,
      );
    }
    assert.equal(plan.unresolved.length, tc.expect_unresolved ?? 0, `${tc.name}: unresolved`);
  }
});

test('search', () => {
  const cat = load();
  for (const tc of vectors.search) {
    const got = cat.search(tc.query, 10);
    if (tc.expect_empty) {
      assert.equal(got.length, 0, `search(${tc.query})`);
      continue;
    }
    assert.ok(
      got.some((m) => m.test.id === tc.expect_contains),
      `search(${tc.query}) should contain ${tc.expect_contains}`,
    );
    if (tc.expect_first) {
      assert.equal(got[0]?.test.id, tc.expect_first, `search(${tc.query}) first`);
    }
  }
});

test('order_set', () => {
  const cat = load();
  for (const tc of vectors.order_set) {
    if (tc.expect_error) {
      assert.equal(codeOf(() => cat.orderSet(tc.profile, tc.core_only)), tc.expect_error);
      continue;
    }
    assert.equal(cat.orderSet(tc.profile, tc.core_only).length, tc.expect_count, tc.profile);
  }
});
