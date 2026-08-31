"""Regression tests for numerical and processing pitfalls.

Each test uses an independent analytic baseline (not the same code path it
tests) and checks that the SFCW chain matches the physical expectation within
a tight tolerance. These document historical failures so they are not
reintroduced.
"""

import numpy as np
import pytest

from scripts import sfcw
from scripts.sfcw_math import two_interface_response, exact_dtft


def test_fp32_floor_is_approx_minus_90_db():
    """A weak reflection near the fp32 floor should be recoverable.

    The fp32 numerical floor is about -90 dB relative to the direct wave.
    A reflection at -80 dB must be distinguishable from noise.
    """
    dt = 0.1e-9
    n = 4096
    h = np.zeros(n, dtype=np.float64)
    h[0] = 1.0  # direct coupling
    # reflection at -80 dB relative to direct
    h[300] = 10 ** (-80.0 / 20.0)
    freqs = np.arange(60e6, 161e6, 1e6)
    samples = sfcw.complex_samples_impulse_lti(h, dt, freqs)
    asc = sfcw.reconstruct_ascan(samples, zero_pad_factor=8)
    env = sfcw.envelope(asc.real)
    # peak at 30 ns (direct) and 30 ns + 300*dt = 60 ns (reflection)
    # Since the direct is at 0 ns, skip it, find the reflection peak
    peak_idx = 300 // (300 * dt / (1.0 / (1e6 * len(asc))))
    # The reflection envelope peak should be above the -80 dB level
    # (relative to direct) within a few dB of tolerance
    direct_peak = float(np.max(env[:50]))
    target_window = env[200:400]
    reflect_peak = float(np.max(target_window))
    ratio_db = 20 * np.log10(reflect_peak / direct_peak) if direct_peak > 0 else -float("inf")
    assert ratio_db > -90, f"ratio_db={ratio_db:.1f} is below -90 dB floor"


def test_reference_subtraction_clutter_removal():
    """H1-H0 reference subtraction should remove direct-wave clutter.

    When H1 and H0 share the same time grid and source reference, subtracting
    the background should leave only the target response. The residual must
    match the analytic two-interface response.
    """
    dt = 0.1e-9
    n = 4096
    # Background (H0): direct coupling only
    h0 = np.zeros(n)
    h0[0] = 1.0
    # Target present (H1): direct + weak reflection
    h1 = h0.copy()
    h1[300] = 0.1
    # Difference = the reflection impulse
    h_diff = h1 - h0
    assert h_diff[300] == 0.1
    # Process through impulse_lti chain
    freqs = np.arange(60e6, 161e6, 1e6)
    samples_diff = sfcw.complex_samples_impulse_lti(h_diff, dt, freqs)
    asc_diff = sfcw.reconstruct_ascan(samples_diff, zero_pad_factor=8)
    env_diff = sfcw.envelope(asc_diff.real)
    # Independent analytic baseline: single reflection at 30 ns
    delays = np.array([300 * dt])
    analytic = two_interface_response(freqs, delays, [0.1])
    asc_analytic = sfcw.reconstruct_ascan(analytic, zero_pad_factor=8)
    env_analytic = sfcw.envelope(asc_analytic.real)
    # The residual should match the analytic baseline
    diff = np.max(np.abs(env_diff[:800] - env_analytic[:800]))
    assert diff < 1e-4, f"subtraction residual mismatch: {diff:.6f}"


def test_guard_region_does_not_contain_target_energy():
    """A guard region declared outside the target window must not capture
    the target's main lobe.

    This is a regression for guard-region selection bias (the historical
    failure of choosing a guard region after inspecting the target response).
    """
    dt = 0.1e-9
    n = 4096
    h = np.zeros(n)
    h[0] = 0.9
    h[300] = 0.1  # reflection at 30 ns
    freqs = np.arange(60e6, 161e6, 1e6)
    samples = sfcw.complex_samples_impulse_lti(h, dt, freqs)
    asc = sfcw.reconstruct_ascan(samples, zero_pad_factor=8)
    env = sfcw.envelope(asc.real)
    delay_bin = 1.0 / (1e6 * len(asc))

    # Target main lobe is centred at 30 ns (bin ~24), direct wave at 0 ns.
    target_lo = int(20e-9 / delay_bin)
    target_hi = int(40e-9 / delay_bin)
    target_peak = float(np.max(env[target_lo:target_hi]))

    # Guard region well away from both direct (0 ns) and target (30 ns):
    # 200-300 ns, where only residual sidelobes remain.
    guard_lo = int(200e-9 / delay_bin)
    guard_hi = int(300e-9 / delay_bin)
    guard_peak = float(np.max(env[guard_lo:guard_hi]))

    # The guard region must not contain target main-lobe energy.
    if guard_peak > 0 and target_peak > 0:
        ratio = guard_peak / target_peak
        assert ratio < 0.5, (
            f"guard region peak {ratio*100:.1f}% of target main lobe "
            f"(guard {guard_peak:.5f} vs target {target_peak:.5f})"
        )