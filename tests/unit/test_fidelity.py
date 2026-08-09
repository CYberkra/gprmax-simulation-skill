import pytest

from scripts.core import GateResult, GateState
from scripts.fidelity import FidelityLevel, can_promote, minimum_fidelity


def _result(state: GateState) -> GateResult:
    return GateResult("grid", state, f"{state.value}_GRID", "grid audit")


@pytest.mark.parametrize(
    ("objective", "claim_scope", "expected"),
    [
        ("antenna", "engineering", FidelityLevel.F4),
        ("system", "engineering", FidelityLevel.F5),
        ("detection", "engineering", FidelityLevel.F5),
        ("resolution", "physical", FidelityLevel.F4),
        ("thickness", "physical", FidelityLevel.F4),
        ("propagation", "numerical", FidelityLevel.F1),
    ],
)
def test_claim_scope_maps_to_minimum_fidelity(objective, claim_scope, expected):
    assert minimum_fidelity(objective, claim_scope) is expected


@pytest.mark.parametrize("state", [GateState.BLOCK, GateState.STALE])
def test_blocked_or_stale_gate_prevents_promotion(state):
    decision = can_promote(FidelityLevel.F1, FidelityLevel.F2, [_result(state)])

    assert decision.allowed is False
    assert decision.code == "BLOCK_PROMOTION_GATE"


def test_same_level_and_single_step_are_allowed_after_clean_gates():
    clean = [_result(GateState.PASS)]

    same = can_promote(FidelityLevel.F1, FidelityLevel.F1, clean)
    next_level = can_promote(FidelityLevel.F1, FidelityLevel.F2, clean)

    assert (same.allowed, same.code) == (True, "ALLOW_FIDELITY_PROMOTION")
    assert (next_level.allowed, next_level.code) == (
        True,
        "ALLOW_FIDELITY_PROMOTION",
    )


@pytest.mark.parametrize("reason", [None, "", "   "])
def test_skip_requires_non_empty_reason(reason):
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F3,
        [],
        skip_reason=reason,
    )

    assert decision.allowed is False
    assert decision.code == "BLOCK_FIDELITY_SKIP_UNJUSTIFIED"


def test_justified_skip_is_allowed_after_clean_gates():
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F3,
        [_result(GateState.NOT_APPLICABLE)],
        skip_reason="F2 geometry is equivalent by declared symmetry",
    )

    assert decision.allowed is True
    assert decision.code == "ALLOW_FIDELITY_PROMOTION"


def test_signoff_below_declared_claim_minimum_is_blocked():
    decision = can_promote(
        FidelityLevel.F3,
        FidelityLevel.F4,
        [_result(GateState.PASS)],
        objective="system",
        claim_scope="engineering",
        signoff=True,
    )

    assert decision.allowed is False
    assert decision.code == "BLOCK_CLAIM_MINIMUM_FIDELITY"


def test_signoff_at_declared_claim_minimum_is_allowed():
    decision = can_promote(
        FidelityLevel.F4,
        FidelityLevel.F4,
        [_result(GateState.PASS)],
        objective="resolution",
        claim_scope="physical",
        signoff=True,
    )

    assert decision.allowed is True
    assert decision.code == "ALLOW_FIDELITY_PROMOTION"


@pytest.mark.parametrize(
    ("objective", "claim_scope"),
    [
        (None, "physical"),
        ("", "physical"),
        ("   ", "physical"),
        ("resolution", None),
        ("resolution", ""),
        ("resolution", "\t"),
    ],
)
def test_signoff_requires_non_blank_claim_context(objective, claim_scope):
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F1,
        [_result(GateState.PASS)],
        objective=objective,
        claim_scope=claim_scope,
        signoff=True,
    )

    assert decision.allowed is False
    assert decision.code == "BLOCK_CLAIM_CONTEXT_MISSING"


def test_limited_gate_requires_explicit_conditional_acceptance():
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F2,
        [_result(GateState.PASS_WITH_LIMITATION)],
    )

    assert decision.allowed is False
    assert decision.code == "BLOCK_CONDITIONAL_EVIDENCE_NOT_ALLOWED"


def test_limited_gate_never_reports_unqualified_promotion():
    decision = can_promote(
        FidelityLevel.F1,
        FidelityLevel.F2,
        [_result(GateState.PASS_WITH_LIMITATION)],
        allow_conditional=True,
    )

    assert decision.allowed is True
    assert decision.code == "ALLOW_FIDELITY_PROMOTION_WITH_LIMITATION"


def test_limited_gate_blocks_signoff():
    decision = can_promote(
        FidelityLevel.F3,
        FidelityLevel.F4,
        [_result(GateState.PASS_WITH_LIMITATION)],
        objective="resolution",
        claim_scope="physical",
        signoff=True,
        allow_conditional=True,
    )

    assert decision.allowed is False
    assert decision.code == "BLOCK_SIGNOFF_CONDITIONAL_GATE"


def test_demotion_is_rejected():
    decision = can_promote(FidelityLevel.F3, FidelityLevel.F2, [])

    assert decision.allowed is False
    assert decision.code == "BLOCK_FIDELITY_DEMOTION"
