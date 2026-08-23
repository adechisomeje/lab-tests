"""Phlebotomy draw planning."""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any


@dataclass
class DrawTube:
    type: str
    cap_colour: str
    position: int
    tests: list[dict[str, Any]] = field(default_factory=list)
    #: Sum of published minimum volumes. A conservative upper bound.
    total_volume_ml: float = 0.0
    volume_known: bool = False
    #: False when the provider does not document where this tube belongs.
    sequence_known: bool = False


@dataclass
class DrawPlan:
    provider: str
    tubes: list[DrawTube] = field(default_factory=list)
    #: Ordered tests with no published tube requirement -- reported, not dropped.
    unresolved: list[dict[str, Any]] = field(default_factory=list)
    order_source: str | None = None
    #: Must be surfaced to the collecting clinician.
    warnings: list[str] = field(default_factory=list)


def build_draw_plan(provider: dict[str, Any], tests: list[dict[str, Any]]) -> DrawPlan:
    plan = DrawPlan(provider=provider.get("name", provider.get("id", "")))
    grouped: dict[str, DrawTube] = {}

    for t in tests:
        tube = (t.get("specimen") or {}).get("tube")
        if not tube:
            plan.unresolved.append(t)
            continue
        entry = grouped.get(tube["type"])
        if entry is None:
            entry = DrawTube(type=tube["type"], cap_colour=tube.get("cap_colour", ""), position=0)
            grouped[tube["type"]] = entry
        entry.tests.append(t)
        vol = (t.get("specimen") or {}).get("volume")
        if vol:
            entry.total_volume_ml += vol["value"]
            entry.volume_known = True

    ood = provider.get("order_of_draw") or {}
    sequence: list[str] = ood.get("sequence") or []
    rank = {tt: i for i, tt in enumerate(sequence)}

    tubes = list(grouped.values())
    for tube in tubes:
        tube.sequence_known = tube.type in rank
    # Tubes the provider documents come first, in its order; the rest are
    # appended alphabetically rather than guessed into a position.
    tubes.sort(key=lambda t: (t.type not in rank, rank.get(t.type, 0), t.type))
    for i, tube in enumerate(tubes):
        tube.position = i + 1
    plan.tubes = tubes
    plan.order_source = ood.get("source_quote")

    if not ood:
        plan.warnings.append(
            "this provider publishes no order of draw; tube sequence is not authoritative"
        )
    else:
        for tube in tubes:
            if not tube.sequence_known:
                plan.warnings.append(
                    f"provider does not specify where the {tube.type} tube "
                    f"({tube.cap_colour}) belongs in the order of draw; it has been "
                    "placed last -- confirm against your SOP"
                )
        if ood.get("conflicts_with_clsi") and len(tubes) > 1 and ood.get("conflict_note"):
            plan.warnings.append(ood["conflict_note"])

    if plan.unresolved:
        plan.warnings.append(
            f"{len(plan.unresolved)} ordered test(s) publish no tube requirement; "
            "check each test's container guidance"
        )
    return plan
