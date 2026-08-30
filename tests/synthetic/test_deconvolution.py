import numpy as np
import pytest

from scripts.sfcw_math import wiener_deconvolve


def test_wiener_zero_loading_is_exact_complex_division():
    source = np.array([1 + 2j, -0.5 + 0.25j, 2 - 1j])
    transfer = np.array([0.2 - 0.1j, -0.4j, 0.8 + 0.3j])
    receiver = source * transfer
    assert np.allclose(wiener_deconvolve(receiver, source, 0.0), transfer)


def test_wiener_rejects_zero_source_and_negative_loading():
    with pytest.raises(ValueError, match="source spectrum is zero"):
        wiener_deconvolve(np.ones(3), np.zeros(3))
    with pytest.raises(ValueError, match="nonnegative"):
        wiener_deconvolve(np.ones(3), np.ones(3), -1.0)
