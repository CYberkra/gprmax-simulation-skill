import numpy as np
import pytest

from scripts.sfcw import (
    complex_samples_impulse_lti,
    envelope,
    reconstruct_ascan,
    run_chain,
)
from scripts.sfcw_math import two_interface_response


def test_independent_complex_two_interface_response_recovers_both_delays():
    frequencies = np.arange(30e6, 266e6, 1e6)
    delays = np.array([801.25e-9, 816.50e-9])
    response = two_interface_response(frequencies, delays, [1.0, -0.65])
    ascan = reconstruct_ascan(response, zero_pad_factor=16)
    env = envelope(ascan)
    delay_bin = 1.0 / (1e6 * len(ascan))
    for expected in delays:
        center = int(round(expected / delay_bin))
        half = int(round(3e-9 / delay_bin))
        local = center - half + int(np.argmax(env[center - half : center + half + 1]))
        assert local * delay_bin == pytest.approx(expected, abs=delay_bin)


def test_impulse_lti_matches_independent_two_interface_transfer_function():
    dt = 0.1e-9
    sample_count = 4096
    frequencies = np.arange(60e6, 161e6, 5e6)
    delay_samples = np.array([300, 600])
    amplitudes = np.array([0.7, -0.25])
    impulse_response = np.zeros(sample_count)
    impulse_response[delay_samples] = amplitudes
    measured = complex_samples_impulse_lti(
        impulse_response,
        dt,
        frequencies,
        ramp_k=0.1,
        integration_cycles=4,
    )
    expected = two_interface_response(
        frequencies, delay_samples * dt, amplitudes
    )
    assert np.allclose(measured, expected, atol=2e-11)


def test_run_chain_rejects_nonuniform_grid_before_ifft():
    with pytest.raises(ValueError, match="uniform"):
        run_chain(
            "direct_per_tone",
            dt_s=0.1e-9,
            frequencies=[30e6, 31e6, 33e6],
            per_tone_traces=np.zeros((3, 100)),
        )
