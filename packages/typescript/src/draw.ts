import { LabTestsError } from './errors.js';
import type { Provider, Test, TubeType } from './types.js';

/** One tube in a draw plan. */
export interface DrawTube {
  type: TubeType;
  capColour: string;
  /** 1-based order in which to draw this tube. */
  position: number;
  tests: Test[];
  /**
   * Sum of the published minimum volumes for this tube. A conservative upper
   * bound: laboratories often run several assays from one draw.
   */
  totalVolumeMl: number;
  volumeKnown: boolean;
  /** False when the provider does not document where this tube belongs. */
  sequenceKnown: boolean;
}

export interface DrawPlan {
  tubes: DrawTube[];
  /** Ordered tests with no published tube requirement -- not dropped. */
  unresolved: Test[];
  provider: string;
  /** The published statement the sequence came from, for audit. */
  orderSource?: string;
  /** Must be surfaced to the collecting clinician. */
  warnings: string[];
}

export function buildDrawPlan(
  provider: Provider,
  tests: Array<Test | undefined>,
  requestedIds: string[],
): DrawPlan {
  const grouped = new Map<TubeType, DrawTube>();
  const unresolved: Test[] = [];

  tests.forEach((t, i) => {
    if (!t) {
      throw new LabTestsError('unknown_test', `unknown test: ${requestedIds[i]}`);
    }
    const tube = t.specimen?.tube;
    if (!tube) {
      unresolved.push(t);
      return;
    }
    let entry = grouped.get(tube.type);
    if (!entry) {
      entry = {
        type: tube.type,
        capColour: tube.cap_colour,
        position: 0,
        tests: [],
        totalVolumeMl: 0,
        volumeKnown: false,
        sequenceKnown: false,
      };
      grouped.set(tube.type, entry);
    }
    entry.tests.push(t);
    const vol = t.specimen?.volume;
    if (vol) {
      entry.totalVolumeMl += vol.value;
      entry.volumeKnown = true;
    }
  });

  const sequence = provider.order_of_draw?.sequence ?? [];
  const rank = new Map<TubeType, number>(sequence.map((t, i) => [t, i]));

  const tubes = [...grouped.values()];
  for (const tube of tubes) tube.sequenceKnown = rank.has(tube.type);
  tubes.sort((a, b) => {
    const ra = rank.get(a.type);
    const rb = rank.get(b.type);
    if ((ra === undefined) !== (rb === undefined)) return ra === undefined ? 1 : -1;
    if (ra !== undefined && rb !== undefined) return ra - rb;
    return a.type < b.type ? -1 : a.type > b.type ? 1 : 0;
  });
  tubes.forEach((t, i) => (t.position = i + 1));

  const warnings: string[] = [];
  const ood = provider.order_of_draw;
  if (!ood) {
    warnings.push(
      'this provider publishes no order of draw; tube sequence is not authoritative',
    );
  } else {
    for (const tube of tubes) {
      if (!tube.sequenceKnown) {
        warnings.push(
          `provider does not specify where the ${tube.type} tube (${tube.capColour}) ` +
            'belongs in the order of draw; it has been placed last -- confirm against your SOP',
        );
      }
    }
    if (ood.conflicts_with_clsi && tubes.length > 1 && ood.conflict_note) {
      warnings.push(ood.conflict_note);
    }
  }
  if (unresolved.length > 0) {
    warnings.push(
      `${unresolved.length} ordered test(s) publish no tube requirement; ` +
        "check each test's container guidance",
    );
  }

  const plan: DrawPlan = { tubes, unresolved, provider: provider.name, warnings };
  if (ood?.source_quote) plan.orderSource = ood.source_quote;
  return plan;
}
