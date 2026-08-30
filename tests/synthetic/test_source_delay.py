import numpy as np

from scripts.sfcw import run_chain
from scripts.sfcw_math import deembed_delay


def test_known_source_delay_is_removed_with_negative_phase_convention():
    frequencies = np.arange(30e6, 91e6, 10e6)
    delay = 17.25e-9
    measured = np.exp(-1j * 2 * np.pi * frequencies * delay)
    assert np.allclose(deembed_delay(measured, frequencies, delay), 1.0)


def test_run_chain_applies_declared_source_delay_deembedding():
    dt = 0.25e-9
    frequencies = np.arange(40e6, 91e6, 5e6)
    delay = 20e-9
    samples = 2400
    t = np.arange(samples) * dt
    traces = np.stack(
        [np.sin(2 * np.pi * f * (t - delay)) for f in frequencies]
    )
    result = run_chain(
        "direct_per_tone",
        dt_s=dt,
        frequencies=frequencies,
        per_tone_traces=traces,
        integration_cycles=6,
        source_delay_s=delay,
    )
    assert np.allclose(result["samples"], 1.0, atol=1e-11)
