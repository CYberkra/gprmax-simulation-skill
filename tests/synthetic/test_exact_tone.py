import numpy as np
import pytest

from scripts.sfcw import complex_samples_broadband, dft_at
from scripts.sfcw_math import exact_dtft


def test_exact_dtft_matches_closed_form_off_fft_bins():
    dt = 0.37e-9
    n = 937
    impulse_index = 123
    signal = np.zeros(n)
    signal[impulse_index] = 0.75
    frequencies = np.array([31.25e6, 97.3e6, 164.125e6])
    expected = 0.75 * np.exp(-1j * 2 * np.pi * frequencies * impulse_index * dt)
    assert np.allclose(exact_dtft(signal, dt, frequencies), expected, atol=1e-12)
    assert dft_at(signal, dt, frequencies[1]) == pytest.approx(expected[1])


def test_broadband_deconvolution_uses_exact_tones_for_source_and_receiver():
    dt = 0.37e-9
    n = 1024
    source = np.zeros(n)
    receiver = np.zeros(n)
    source_index, propagation_samples = 17, 211
    source[source_index] = 1.0
    receiver[source_index + propagation_samples] = 0.4
    frequencies = np.array([33.7e6, 81.125e6, 149.91e6])
    result = complex_samples_broadband(
        receiver,
        dt,
        source,
        frequencies,
        dt,
        regularisation=0.0,
    )
    expected = 0.4 * np.exp(
        -1j * 2 * np.pi * frequencies * propagation_samples * dt
    )
    assert np.allclose(result, expected, atol=1e-11)
