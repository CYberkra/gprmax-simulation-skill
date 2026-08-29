# Gates, fidelity, and claim states

Use this reference to interpret gate reports and to know what a fidelity level
licenses. It fixes the vocabulary shared between the documentation layer, the
gate engine, and the claim ledger, so that an agent reading a report can
predict its shape and semantics.

## Gate states (`GateState`)

Every blocking/evidence gate returns exactly one state:

| State | Meaning |
|---|---|
| `PASS` | Gate satisfied; evidence intact. |
| `PASS_WITH_LIMITATION` | Gate satisfied with recorded limitations; promotion requires explicit conditional acceptance and cannot reach verified sign-off. |
| `BLOCK` | Gate failed; expensive execution or promotion stops (fail-closed). |
| `STALE` | Previously valid result invalidated by an upstream change; must be revalidated before reuse. |
| `NOT_APPLICABLE` | Gate does not apply to this contract. |

Blocking failure always follows the repair loop, never "probably fine":

```text
FAIL → STOP → root cause → repair → regression test → rerun affected gates → resume
```

## Claim states (`ClaimState`)

| State | Meaning |
|---|---|
| `UNVERIFIED` | Not yet supported by evidence |
| `CONDITIONAL` | Supported with recorded limitations |
| `VERIFIED` | Supported by a fully passing gate chain and minimum fidelity |
| `REJECTED` | Contradicted by evidence |
| `STALE` | Previously valid, invalidated by an upstream change |

## Dependency invalidation

Evidence forms a chain: `environment → numerics → source → geometry_materials →
antenna_system → simulation → processing → metrics → claims`. A change upstream
invalidates every dependent downstream result, marking them `STALE` until
revalidated. Never reuse a stale result as if it were current.

## Fidelity levels (F0-F5)

Promotion is the ordered climb through fidelity that a claim licenses. Each
level is the *minimum* physical modelling needed for a class of claims.

| Level | Meaning | Typical evidence |
|---|---|---|
| `F0` | Analytical sanity; no numerical simulation | hand/analytic check |
| `F1` | Minimal numerical physics | one small smoke case |
| `F2` | Reduced-dimensional propagation | 2-D / scalar approximation |
| `F3` | Simplified three-dimensional physics | coarse 3-D, ideal sources |
| `F4` | High-fidelity three-dimensional physical model | fine mesh, physical targets |
| `F5` | Calibrated hardware and system closure | validated field-to-system link |

## Minimum fidelity for claims

A claim may only be signed off at or above its minimum fidelity; a requested
fidelity below the minimum blocks sign-off (`BLOCK_CLAIM_MINIMUM_FIDELITY`).
Default minimum is `F1`. Known minimums:

| Claim (objective, scope) | Minimum |
|---|---|
| `(antenna, engineering)` | `F4` |
| `(system, engineering)` | `F5` |
| `(detection, engineering)` | `F5` |
| `(resolution, physical)` | `F4` |
| `(thickness, physical)` | `F4` |

## Promotion rules

- Any `BLOCK` or `STALE` gate result blocks promotion.
- Promotion cannot move to a lower level (demotion is blocked).
- Skipping more than one level requires a non-empty justification.
- A `PASS_WITH_LIMITATION` result requires explicit conditional acceptance
  (`--allow-conditional`) and can never be promoted to verified sign-off.
- Claim sign-off requires an explicit objective and claim scope, the requested
  fidelity at or above the claim minimum, and no conditional gate results.