import numpy as np
import pytest

import scripts.sfcw as sfcw

DT = 0.1e-9  # 10 GHz sampling grid (numerical)
N = 4096
F_LO, F_HI, DF = 60e6, 160e6, 1e6


def _twin_reflection_impulse(tau1=30e-9, tau2=60e-9, a1=0.1, a2=0.05):
    h = np.zeros(N)
    h[0] = 0.15  # small direct coupling at t=0 (kept weak to avoid sinc bleed)
    h[int(round(tau1 / DT))] = a1
    h[int(round(tau2 / DT))] = a2
    return h


def _peaks_in_window(envelope, center_s, half_s=5e-9, dt=DT):
    center_idx = int(center_s / dt)
    half_idx = int(half_s / dt)
    lo, hi = max(0, center_idx - half_idx), min(len(envelope), center_idx + half_idx)
    window = envelope[lo:hi]
    return lo + int(np.argmax(window)), float(np.max(window))


def _positions(envelope, df_hz=DF):
    """Peak positions (seconds) of the two reflections within the usable
    window (25-200 ns). The reconstructed axis spans 1/df and carries a
    mirror image at the far end; real studies observe a shorter window."""
    bin_time = 1.0 / (df_hz * len(envelope))
    lo = int(25e-9 / bin_time)
    hi = int(200e-9 / bin_time)
    payload = envelope[lo:hi].copy()
    first = lo + int(np.argmax(payload))
    # null the whole first main lobe (+/- 10 ns) before hunting the second
    lobe = int(10e-9 / bin_time) + 1
    payload[max(0, first - lo - lobe) : first - lo + lobe] = 0.0
    second = lo + int(np.argmax(payload))
    return first * bin_time, second * bin_time


def test_tone_grid():
    freqs = sfcw.tone_grid(60e6, 160e6, 1e6)
    assert len(freqs) == 101
    assert freqs[0] == pytest.approx(60e6)
    assert freqs[-1] == pytest.approx(160e6)
    with pytest.raises(ValueError, match="tone step"):
        sfcw.tone_grid(60e6, 160.5e6, 1e6)


def test_make_flatpulse_normalised_with_band_energy():
    pulse = sfcw.make_flatpulse(F_LO, F_HI, DT, N, rolloff_mhz=10.0)
    assert len(pulse) == N
    assert np.max(np.abs(pulse)) == pytest.approx(1.0)
    # strongest spectral mass inside the band (rolloff included)
    spectrum = np.abs(np.fft.rfft(pulse))
    freqs = np.fft.rfftfreq(N, DT)
    band = (freqs >= F_LO - 10e6) & (freqs <= F_HI + 10e6)
    assert spectrum[band].sum() / spectrum.sum() > 0.8


def test_make_sine_tone_has_ramp():
    k = 0.1
    tone = sfcw.make_sine_tone(F_LO, DT, N, ramp_k=k)
    assert len(tone) == N
    t = np.arange(N) * DT
    expected = np.sin(2 * np.pi * F_LO * t)
    coordinate = k * F_LO * t
    expected[coordinate < 1] *= coordinate[coordinate < 1]
    assert np.allclose(tone, expected)
    # Legacy keyword is an alias for Liu's k, not the old phase-duration rule.
    assert np.allclose(
        tone, sfcw.make_sine_tone(F_LO, DT, N, ramp_phase=k)
    )


def test_impulse_lti_recovers_reflections():
    h = _twin_reflection_impulse()
    freqs = sfcw.tone_grid(F_LO, F_HI, DF)
    samples = sfcw.complex_samples_impulse_lti(h, DT, freqs)
    ascan = sfcw.reconstruct_ascan(samples, zero_pad_factor=8)
    env = sfcw.envelope(ascan.real)

    first, second = _positions(env)
    assert abs(first - 30e-9) < 5e-9
    assert abs(second - 60e-9) < 5e-9
    assert np.all(env >= 0)


def test_direct_route_matches_impulse_lti():
    h = _twin_reflection_impulse()
    freqs = sfcw.tone_grid(F_LO, F_HI, DF)
    per_tone = np.stack(
        [
            sfcw.synthesize_tone_response(h, DT, f, ramp_phase=0.1)
            for f in freqs
        ]
    )
    direct = sfcw.complex_samples_direct(per_tone, DT, freqs)
    lti = sfcw.complex_samples_impulse_lti(h, DT, freqs)

    env_direct = sfcw.envelope(sfcw.reconstruct_ascan(direct).real)
    env_lti = sfcw.envelope(sfcw.reconstruct_ascan(lti).real)
    d1, d2 = _positions(env_direct)
    l1, l2 = _positions(env_lti)
    assert abs(d1 - l1) < 2e-9
    assert abs(d2 - l2) < 2e-9


def test_broadband_deconvolution_matches_impulse_lti():
    h = _twin_reflection_impulse()
    source = sfcw.make_flatpulse(F_LO, F_HI, DT, N, rolloff_mhz=10.0)
    receiver = np.convolve(h, source, mode="full")[:N]
    freqs = sfcw.tone_grid(F_LO, F_HI, DF)

    samples = sfcw.complex_samples_broadband(
        receiver, DT, source, freqs, DT, regularisation=1e-6,
        f_lo_hz=F_LO, f_hi_hz=F_HI,
    )
    env_bw = sfcw.envelope(sfcw.reconstruct_ascan(samples).real)

    lti_samples = sfcw.complex_samples_impulse_lti(h, DT, freqs)
    env_lti = sfcw.envelope(sfcw.reconstruct_ascan(lti_samples).real)

    b1, b2 = _positions(env_bw)
    l1, l2 = _positions(env_lti)
    assert abs(b1 - l1) < 3e-9
    assert abs(b2 - l2) < 3e-9


def test_reconstruct_keeps_time_close_to_real():
    samples = np.ones(101, dtype=complex)
    ascan = sfcw.reconstruct_ascan(samples, zero_pad_factor=8)
    # A constant complex baseband spectrum peaks at zero delay.  The first
    # measured tone is retained; no artificial Hermitian mirror is imposed.
    assert np.argmax(np.abs(ascan)) == 0
    assert np.abs(ascan[0]) == pytest.approx(1.0)


def test_run_chain_all_modes_have_shape():
    h = _twin_reflection_impulse()
    freqs = sfcw.tone_grid(F_LO, F_HI, DF)
    per_tone = np.stack(
        [sfcw.synthesize_tone_response(h, DT, f) for f in freqs]
    )
    source = sfcw.make_flatpulse(F_LO, F_HI, DT, N)
    receiver = np.convolve(h, source, mode="full")[:N]

    for mode, kwargs in (
        ("direct_per_tone", {"per_tone_traces": per_tone}),
        ("impulse_lti", {"impulse_response": h}),
        (
            "broadband_deconvolution",
            {"receiver_ez": receiver, "source_waveform": source},
        ),
    ):
        result = sfcw.run_chain(mode, dt_s=DT, frequencies=freqs, **kwargs)
        assert result["mode"] == mode
        assert result["samples"].shape == freqs.shape
        assert result["envelope"].ndim == 1
        assert result["delay_bin_s"] == pytest.approx(
            1.0 / (DF * len(result["ascan"]))
        )
        assert result["unambiguous_delay_s"] == pytest.approx(1.0 / DF)
        assert result["fdtd_dt_s"] == DT
        assert "dt_s" not in result
        parameters = result["processing_parameters"]
        assert parameters["tone_count"] == len(freqs)
        assert parameters["delta_f_hz"] == pytest.approx(DF)
        assert parameters["zero_pad_factor"] == 8
        assert parameters["quantitative_normalization"] == "none"
        assert parameters["noise_model"] == "none"


def test_run_chain_rejects_missing_inputs():
    with pytest.raises(ValueError):
        sfcw.run_chain("impulse_lti", dt_s=DT, frequencies=[F_LO])  # no h
    with pytest.raises(ValueError):
        sfcw.run_chain("nope", dt_s=DT)


def test_run_chain_rejects_mismatched_trace_count():
    with pytest.raises(ValueError):
        sfcw.complex_samples_direct(np.zeros((3, N)), DT, [F_LO, F_HI])


def test_bscan_stack_pads_to_common_length():
    a = np.ones(100)
    b = np.ones(150)
    bscan = sfcw.bscan_from_ascans([a, b])
    assert bscan.shape == (2, 150)
    assert np.allclose(bscan[0, 100:], 0)
