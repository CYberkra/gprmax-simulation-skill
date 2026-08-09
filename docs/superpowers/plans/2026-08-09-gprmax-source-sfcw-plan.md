# gprMax Source and SFCW Processing Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Implement a signable broadband-pulse-to-SFCW processing chain with source support auditing, exact-tone complex extraction, delay de-embedding, regularized deconvolution, explicit window/range contracts, and strict reference/normalization policies.

**Architecture:** Keep source validation and SFCW processing as separate modules. `scripts/audit_source.py` validates the excitation; `scripts/audit_sfcw.py` performs exact-tone math and policy checks. Quantitative functions operate on complex NumPy arrays and never overwrite raw data.

**Tech Stack:** Python 3.11+, NumPy, h5py, pytest.

## Global Constraints

- Broadband pulse plus exact frequency extraction is labeled `sfcw_equivalent`, not direct per-tone SFCW simulation.
- Formal extraction evaluates the complex response at exact physical tones; nearest FFT bin is diagnostic-only.
- Artificial source delay is removed exactly once.
- Per-tone/per-trace amplitude normalization is forbidden in the quantitative chain.
- Zero-padding may refine discrete sampling but may not be used to claim improved physical resolution.
- Perfect target-minus-reference subtraction is truth-only unless the contract explicitly proves a field-available engineering reference.
- Generic core does not force Hann or any project-specific tone grid.

---

## File map

- Create: `scripts/audit_source.py`
- Create: `scripts/audit_sfcw.py`
- Create: `scripts/sfcw_math.py`
- Modify: `scripts/cli.py`
- Test: `tests/unit/test_source_gate.py`
- Test: `tests/synthetic/test_exact_tone.py`
- Test: `tests/synthetic/test_source_delay.py`
- Test: `tests/synthetic/test_deconvolution.py`
- Test: `tests/synthetic/test_two_interface.py`
- Test: `tests/synthetic/test_zero_padding.py`
- Test: `tests/unit/test_sfcw_policy.py`

### Task 1: Source spectrum, support, DC, peak, and tail audit

**Files:**
- Create: `scripts/audit_source.py`
- Test: `tests/unit/test_source_gate.py`

**Interfaces:**
- Produces: `source_spectrum(signal, dt, frequencies_hz) -> np.ndarray`, `source_peak_time(signal, dt) -> float`, `tail_energy_fraction(signal, peak_index) -> float`, `audit_source(ctx) -> GateResult`.

- [ ] **Step 1: Write source audit tests**

```python
import numpy as np
from pathlib import Path
from scripts.audit_source import source_peak_time, tail_energy_fraction


def test_source_peak_time_is_sample_accurate():
    x = np.array([0.0, 1.0, 0.25])
    assert source_peak_time(x, 2e-9) == 2e-9


def test_tail_energy_fraction_excludes_peak_sample():
    x = np.array([0.0, 2.0, 1.0])
    value = tail_energy_fraction(x, 1)
    assert np.isclose(value, 1.0 / 5.0)
```

Add a fixture whose requested tone lies at an intentionally constructed spectral null; `audit_source` must return `BLOCK_SOURCE_SPECTRAL_SUPPORT`. Add a source with declared `dc_forbidden=true` and non-negligible mean; expect `BLOCK_SOURCE_DC`.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_source_gate.py -v`

Expected: FAIL because the source module does not exist.

- [ ] **Step 3: Implement source math and threshold policy**

Use direct complex evaluation for requested frequencies rather than relying on FFT-bin alignment:

```python
def source_spectrum(signal: np.ndarray, dt: float, frequencies_hz: np.ndarray) -> np.ndarray:
    x = np.asarray(signal, dtype=np.complex128)
    t = np.arange(x.size, dtype=np.float64) * dt
    return np.exp(-2j * np.pi * np.outer(frequencies_hz, t)) @ x
```

`audit_source` reads the source array and actual `dt`, computes normalized support relative to the strongest requested tone, and compares to a contract-declared minimum support ratio. If the contract omits a support threshold for a formal SFCW-equivalent claim, return `PASS_WITH_LIMITATION` rather than inventing a physics threshold. Tail and DC tolerances follow the same explicit-contract rule.

- [ ] **Step 4: Run source tests**

Run: `pytest tests/unit/test_source_gate.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_source.py tests/unit/test_source_gate.py
git commit -m "feat: audit source spectral support and timing"
```

### Task 2: Exact-tone complex extraction

**Files:**
- Create: `scripts/sfcw_math.py`
- Test: `tests/synthetic/test_exact_tone.py`

**Interfaces:**
- Produces: `exact_tone_dtft(signal, dt, tones_hz) -> np.ndarray`, `nearest_fft_bins(signal, dt, tones_hz) -> np.ndarray` diagnostic helper.

- [ ] **Step 1: Write a non-bin-centered synthetic tone test**

```python
import numpy as np
from scripts.sfcw_math import exact_tone_dtft, nearest_fft_bins


def test_exact_tone_beats_nearest_fft_for_off_bin_tone():
    dt = 1e-9
    n = 257
    t = np.arange(n) * dt
    f = 73.25e6
    x = np.exp(2j * np.pi * f * t)
    exact = exact_tone_dtft(x, dt, np.array([f]))[0]
    nearest = nearest_fft_bins(x, dt, np.array([f]))[0]
    assert abs(exact) > abs(nearest)
    assert abs(np.angle(exact)) < 1e-10
```

- [ ] **Step 2: Run the test and verify failure**

Run: `pytest tests/synthetic/test_exact_tone.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement exact-tone evaluation and diagnostic FFT helper**

```python
def exact_tone_dtft(signal: np.ndarray, dt: float, tones_hz: np.ndarray) -> np.ndarray:
    x = np.asarray(signal, dtype=np.complex128)
    tones = np.asarray(tones_hz, dtype=np.float64)
    t = np.arange(x.size, dtype=np.float64) * dt
    return np.exp(-2j * np.pi * np.outer(tones, t)) @ x
```

`nearest_fft_bins` may use `np.fft.fft` and nearest frequency index but its docstring must explicitly label it diagnostic-only.

- [ ] **Step 4: Run exact-tone tests**

Run: `pytest tests/synthetic/test_exact_tone.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/sfcw_math.py tests/synthetic/test_exact_tone.py
git commit -m "feat: add exact tone complex extraction"
```

### Task 3: Source-delay de-embedding and group-delay regression

**Files:**
- Modify: `scripts/sfcw_math.py`
- Test: `tests/synthetic/test_source_delay.py`

**Interfaces:**
- Produces: `remove_known_delay(response, tones_hz, delay_s)`, `group_delay(response, tones_hz)`.

- [ ] **Step 1: Write a known-delay recovery test**

```python
import numpy as np
from scripts.sfcw_math import group_delay, remove_known_delay


def test_known_source_delay_is_removed_once():
    tones = np.linspace(50e6, 150e6, 201)
    delay = 250e-9
    h = np.exp(-2j * np.pi * tones * delay)
    corrected = remove_known_delay(h, tones, delay)
    gd = group_delay(corrected, tones)
    assert abs(np.median(gd)) < 1e-12
```

Add a second test that applies the correction twice and confirms group delay becomes approximately `-delay`, proving double correction is detectable.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/synthetic/test_source_delay.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement delay and unwrapped phase derivative**

```python
def remove_known_delay(response, tones_hz, delay_s):
    return np.asarray(response, np.complex128) * np.exp(2j * np.pi * np.asarray(tones_hz) * delay_s)


def group_delay(response, tones_hz):
    phase = np.unwrap(np.angle(response))
    omega = 2 * np.pi * np.asarray(tones_hz, dtype=float)
    return -np.gradient(phase, omega)
```

- [ ] **Step 4: Run delay tests**

Run: `pytest tests/synthetic/test_source_delay.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/sfcw_math.py tests/synthetic/test_source_delay.py
git commit -m "feat: deembed source delay and audit group delay"
```

### Task 4: Regularized source deconvolution

**Files:**
- Modify: `scripts/sfcw_math.py`
- Test: `tests/synthetic/test_deconvolution.py`

**Interfaces:**
- Produces: `regularized_deconvolution(received, source, regularization) -> np.ndarray`, `deconvolution_condition_fraction(source, regularization) -> float`.

- [ ] **Step 1: Write recovery and spectral-notch tests**

```python
import numpy as np
from scripts.sfcw_math import regularized_deconvolution


def test_regularized_deconvolution_recovers_known_transfer_function():
    source = np.array([1+0j, 2+0j, 3+0j])
    truth = np.array([0.5+0.2j, 0.1-0.3j, -0.4+0.1j])
    received = source * truth
    recovered = regularized_deconvolution(received, source, 1e-12)
    assert np.allclose(recovered, truth, atol=1e-9)


def test_source_notch_remains_finite():
    source = np.array([1+0j, 1e-15+0j])
    received = np.array([1+0j, 1+0j])
    recovered = regularized_deconvolution(received, source, 1e-6)
    assert np.isfinite(recovered).all()
```

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/synthetic/test_deconvolution.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement the documented regularized formula**

```python
def regularized_deconvolution(received, source, regularization):
    y = np.asarray(received, np.complex128)
    s = np.asarray(source, np.complex128)
    lam = float(regularization)
    if lam < 0:
        raise ValueError("regularization must be non-negative")
    return y * np.conj(s) / (np.abs(s) ** 2 + lam)
```

The audit layer must block formal processing if the contract does not record how regularization was chosen, or if the fraction of tones dominated by the regularizer exceeds a contract-declared maximum.

- [ ] **Step 4: Run deconvolution tests**

Run: `pytest tests/synthetic/test_deconvolution.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/sfcw_math.py tests/synthetic/test_deconvolution.py
git commit -m "feat: add regularized source deconvolution"
```

### Task 5: Tone-grid, window, zero-padding, and range-contract policies

**Files:**
- Create: `scripts/audit_sfcw.py`
- Test: `tests/unit/test_sfcw_policy.py`
- Test: `tests/synthetic/test_zero_padding.py`

**Interfaces:**
- Produces: `unambiguous_range(velocity_mps, delta_f_hz)`, `bandwidth_resolution_scale(velocity_mps, bandwidth_hz)`, `apply_window(response, kind, beta=None)`, `audit_sfcw(ctx) -> GateResult`.

- [ ] **Step 1: Write policy tests**

```python
from scripts.audit_sfcw import unambiguous_range, bandwidth_resolution_scale


def test_unambiguous_range_formula():
    assert unambiguous_range(2.0e8, 1.0e6) == 100.0


def test_bandwidth_resolution_scale_formula():
    assert bandwidth_resolution_scale(2.0e8, 100.0e6) == 1.0
```

Add tests that block nonuniform tones when the selected IFFT path requires uniform spacing, block `quantitative_normalization="per_tone"`, and return `BLOCK_FALSE_RESOLUTION_CLAIM` when a fixture claims improved physical resolution solely because `nfft` increased.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/unit/test_sfcw_policy.py tests/synthetic/test_zero_padding.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement policy and window behavior**

```python
def unambiguous_range(velocity_mps: float, delta_f_hz: float) -> float:
    return velocity_mps / (2.0 * delta_f_hz)


def bandwidth_resolution_scale(velocity_mps: float, bandwidth_hz: float) -> float:
    return velocity_mps / (2.0 * bandwidth_hz)


def apply_window(response, kind, beta=None):
    n = len(response)
    if kind == "rectangular":
        w = np.ones(n)
    elif kind == "hann":
        w = np.hanning(n)
    elif kind == "kaiser":
        if beta is None:
            raise ValueError("kaiser beta is required")
        w = np.kaiser(n, beta)
    else:
        raise ValueError(f"unsupported window: {kind}")
    return np.asarray(response) * w
```

`audit_sfcw` validates exact tone list, uniformity if required, requested maximum path against unambiguous range, predeclared window, no quantitative per-tone/per-trace normalization, source-delay de-embedding evidence, and the source/reference classifications. If a declared artificial `source_delay` remains in the processed complex response beyond the contract-declared group-delay tolerance, return `BLOCK_SOURCE_DELAY_NOT_DEEMBEDDED`. If a reference classified as `solver_truth` is requested as `engineering_input` without an explicit field-available reference contract, return `BLOCK_TRUTH_REFERENCE_ENGINEERING_INPUT`. It reports bandwidth resolution only as a sanity scale, never as final separability evidence.

- [ ] **Step 4: Run policy tests**

Run: `pytest tests/unit/test_sfcw_policy.py tests/synthetic/test_zero_padding.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/audit_sfcw.py tests/unit/test_sfcw_policy.py tests/synthetic/test_zero_padding.py
git commit -m "feat: enforce sfcw tone window and range policies"
```

### Task 6: Complex two-interface regression and polarity constraint

**Files:**
- Modify: `scripts/sfcw_math.py`
- Test: `tests/synthetic/test_two_interface.py`

**Interfaces:**
- Produces: `two_interface_response(tones_hz, a1, a2, tau1_s, tau2_s, opposite_polarity=True)`, `estimate_two_interface_delay_grid(...)` test-only/simple reference fitter.

- [ ] **Step 1: Write a regression that fails for magnitude-only ambiguity**

```python
import numpy as np
from scripts.sfcw_math import two_interface_response


def test_two_interface_model_preserves_opposite_polarity_and_carrier_phase():
    tones = np.linspace(80e6, 180e6, 101)
    h = two_interface_response(tones, 1.0, 0.6, 100e-9, 106e-9, opposite_polarity=True)
    expected = (
        1.0 * np.exp(-2j*np.pi*tones*100e-9)
        - 0.6 * np.exp(-2j*np.pi*tones*106e-9)
    )
    assert np.allclose(h, expected)
```

Add a test showing a real-only reduction changes the complex residual and therefore cannot satisfy the precision inversion acceptance path.

- [ ] **Step 2: Run tests and verify failure**

Run: `pytest tests/synthetic/test_two_interface.py -v`

Expected: FAIL.

- [ ] **Step 3: Implement physically constrained response helper**

Implement the formula exactly as the expected test. The reference fitter may grid-search a bounded second-interface delay while retaining full complex residual; it exists only to validate the gate and does not claim to be the production scientific inversion algorithm.

- [ ] **Step 4: Run two-interface tests**

Run: `pytest tests/synthetic/test_two_interface.py -v`

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/sfcw_math.py tests/synthetic/test_two_interface.py
git commit -m "test: lock complex two interface physics"
```

### Task 7: SFCW CLI stage and acquisition-semantics gate

**Files:**
- Modify: `scripts/cli.py`
- Modify: `scripts/audit_sfcw.py`
- Test: `tests/unit/test_sfcw_policy.py`

**Interfaces:**
- Adds CLI `validate-source` and SFCW acquisition semantic check.

- [ ] **Step 1: Add a failing moving-during-sweep policy test**

Create a contract with `measurement_mode=sfcw_equivalent`, antenna positions changing per tone, and `motion_during_sweep=false`; expect `BLOCK_SFCW_POSITION_SEMANTICS`.

- [ ] **Step 2: Run the targeted test**

Run: `pytest tests/unit/test_sfcw_policy.py -v`

Expected: FAIL until semantics check is implemented.

- [ ] **Step 3: Implement stage registration and CLI command**

`validate-source` must run `audit_source` before `audit_sfcw`, write `gates/validate-source.json`, and return exit `2` on either blocking result. For normal stationary sweeps, require all tones at a position before position increment; allow moving-during-sweep only when explicitly enabled in the contract.

- [ ] **Step 4: Run all Plan 3 tests**

Run:

```bash
pytest tests/unit/test_source_gate.py tests/unit/test_sfcw_policy.py tests/synthetic/test_exact_tone.py tests/synthetic/test_source_delay.py tests/synthetic/test_deconvolution.py tests/synthetic/test_two_interface.py tests/synthetic/test_zero_padding.py -q
```

Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add scripts/cli.py scripts/audit_sfcw.py tests/unit/test_sfcw_policy.py
git commit -m "feat: add fail closed sfcw validation stage"
```

## Plan 3 completion gate

Run the complete Plan 3 suite and intentionally feed: an off-bin tone, an unremoved known delay, a source notch, per-tone normalization, and a target/reference classified as truth-only but requested as engineering input. The exact-tone path must pass the valid synthetic cases; the policy defects must produce specific `BLOCK_*` results.
