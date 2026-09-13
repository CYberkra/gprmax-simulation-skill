# Evidence checks and claim states

These are reporting conventions, not an installed gate engine or command-line
interface. Do not invent gate executables, claim-ledger APIs, promotion ladders,
or flags such as --allow-conditional. Use existing project machinery if it exists.

## Report what was checked

Keep independent fields for run/output integrity, processing validation,
metric result, interface attribution, and the final scoped claim.

- PASS: the named check actually ran and satisfied its recorded criterion.
- PASS_WITH_LIMITATION: evidence supports the named limited statement.
- BLOCK: the named action or claim cannot proceed because its required check failed.
- STALE: an upstream change invalidated this evidence for the new use.
- NOT_APPLICABLE: the check is irrelevant to this task.

A scientific NOT_RESOLVED row is a valid experimental result, not a corrupt run.
A successful script exit or unconditional JSON status is not a physical PASS.
Do not stop an authorized exploratory simulation solely because a stronger
physical or hardware claim is unsupported; restrict the claim to the evidence.

## Claims

Use UNVERIFIED, CONDITIONAL, VERIFIED, REJECTED or STALE with a specific claim
and scope. VERIFIED requires demonstrated evidence for that statement, not a
numerical fidelity label or an attractive figure.

- Implementation consistency: analytic/DTFT checks and regression on raw data.
- Numerical model behavior: audited solver/model and the relevant diagnostics.
- Interface association: controlled changes and competing explanations addressed.
- Physical dimension limit: validated estimator, negative controls, search bounds
  and relevant numerical convergence/uncertainty.
- Detection probability: frozen detector, positive/negative populations, noise
  assumptions, sample size and confidence intervals.
- Hardware/system performance: the above plus a validated field-to-system link.

Optional F0–F5 labels may describe model abstraction, but a label does not
automatically license or prohibit a scientific conclusion. Do not demand
unnecessary hardware calibration for a clearly scoped ideal-simulation study.

## Invalidation

Track environment/build, geometry/materials, source/receiver, raw outputs,
processing, background method, metrics and conclusions. Revalidate affected
downstream evidence when an upstream dependency changes. A processing-only change
usually requires reanalysis, not a new FDTD run; changing physical inputs normally
requires a new compatible simulation or an explicitly justified existing one.

Preserve frozen results and register a new analysis version. The latest timestamp
alone does not make an unvalidated picker stronger than earlier evidence.
