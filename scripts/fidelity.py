from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum
from typing import Iterable

from scripts.core import GateResult, GateState


class FidelityLevel(IntEnum):
    """Ordered simulation fidelity, from analytical checks to system closure."""

    F0 = 0  # Analytical sanity; no numerical simulation.
    F1 = 1  # Minimal numerical physics.
    F2 = 2  # Reduced-dimensional propagation.
    F3 = 3  # Simplified three-dimensional physics.
    F4 = 4  # High-fidelity three-dimensional physical model.
    F5 = 5  # Calibrated hardware and system closure.


@dataclass(frozen=True)
class PromotionDecision:
    allowed: bool
    code: str
    summary: str


_MINIMUM = {
    ("antenna", "engineering"): FidelityLevel.F4,
    ("system", "engineering"): FidelityLevel.F5,
    ("detection", "engineering"): FidelityLevel.F5,
    ("resolution", "physical"): FidelityLevel.F4,
    ("thickness", "physical"): FidelityLevel.F4,
}


def minimum_fidelity(objective: str, claim_scope: str) -> FidelityLevel:
    """Return the minimum fidelity needed to support a declared claim."""

    return _MINIMUM.get((objective, claim_scope), FidelityLevel.F1)


def can_promote(
    current: FidelityLevel,
    requested: FidelityLevel,
    results: Iterable[GateResult],
    skip_reason: str | None = None,
    *,
    objective: str | None = None,
    claim_scope: str | None = None,
    signoff: bool = False,
    allow_conditional: bool = False,
) -> PromotionDecision:
    """Evaluate a fidelity transition and, when requested, its claim sign-off."""

    gate_results = tuple(results)
    blocking = [
        result
        for result in gate_results
        if result.state in {GateState.BLOCK, GateState.STALE}
    ]
    if blocking:
        gate_ids = ", ".join(result.gate_id for result in blocking)
        return PromotionDecision(
            False,
            "BLOCK_PROMOTION_GATE",
            f"Promotion blocked by gate results: {gate_ids}.",
        )

    if requested < current:
        return PromotionDecision(
            False,
            "BLOCK_FIDELITY_DEMOTION",
            f"Cannot promote from {current.name} down to {requested.name}.",
        )

    if requested - current > 1 and not (skip_reason and skip_reason.strip()):
        return PromotionDecision(
            False,
            "BLOCK_FIDELITY_SKIP_UNJUSTIFIED",
            "Skipping fidelity levels requires a non-empty justification.",
        )

    limited = any(
        result.state is GateState.PASS_WITH_LIMITATION for result in gate_results
    )
    if limited and not allow_conditional:
        return PromotionDecision(
            False,
            "BLOCK_CONDITIONAL_EVIDENCE_NOT_ALLOWED",
            "Limited gate evidence requires explicit conditional acceptance.",
        )

    if signoff:
        if objective is None or claim_scope is None:
            return PromotionDecision(
                False,
                "BLOCK_CLAIM_CONTEXT_MISSING",
                "Sign-off requires an explicit objective and claim scope.",
            )

        required = minimum_fidelity(objective, claim_scope)
        if requested < required:
            return PromotionDecision(
                False,
                "BLOCK_CLAIM_MINIMUM_FIDELITY",
                (
                    f"The {claim_scope} {objective} claim requires at least "
                    f"{required.name}; requested {requested.name}."
                ),
            )

        if limited:
            return PromotionDecision(
                False,
                "BLOCK_SIGNOFF_CONDITIONAL_GATE",
                "A limited gate result cannot be promoted to verified sign-off.",
            )

    if limited:
        return PromotionDecision(
            True,
            "ALLOW_FIDELITY_PROMOTION_WITH_LIMITATION",
            f"Promotion to {requested.name} is conditional on recorded limitations.",
        )

    return PromotionDecision(
        True,
        "ALLOW_FIDELITY_PROMOTION",
        f"Promotion to {requested.name} is allowed.",
    )
