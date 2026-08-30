import numpy as np
import pytest

from scripts.sfcw import reconstruct_ascan
from scripts.sfcw_math import two_interface_response


def test_zero_padding_preserves_peak_amplitude_and_first_tone():
    frequencies = np.arange(30e6, 131e6, 1e6)
    # Put the target exactly on an unpadded delay bin so interpolation cannot
    # masquerade as an amplitude-normalisation result.
    delay = 37.0 / (len(frequencies) * 1e6)
    response = two_interface_response(frequencies, [delay], [0.37])
    peaks = [
        np.max(np.abs(reconstruct_ascan(response, zero_pad_factor=factor)))
        for factor in (1, 2, 8, 16)
    ]
    assert peaks == pytest.approx([0.37] * 4, rel=1e-12, abs=1e-12)

    first_only = np.zeros(len(frequencies), dtype=complex)
    first_only[0] = 1.0
    reconstructed = reconstruct_ascan(first_only, zero_pad_factor=8)
    assert np.allclose(reconstructed, 1.0 / len(frequencies))


@pytest.mark.parametrize("factor", [0, -1, 1.5])
def test_invalid_zero_padding_factor_is_rejected(factor):
    with pytest.raises(ValueError, match="positive integer"):
        reconstruct_ascan(np.ones(8), zero_pad_factor=factor)
