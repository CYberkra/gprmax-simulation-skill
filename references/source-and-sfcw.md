# Source and SFCW reconstruction

Use this reference when a time-domain gprMax result is converted to an SFCW-like
response or when comparing reconstructed traces.

## Declare the acquisition and transform chain

State whether the result is an actual per-tone stepped-frequency simulation or a
broadband-to-SFCW-equivalent reconstruction. For the latter, record:

1. the time-domain receiver response and time reference;
2. source-spectrum reference and complex transfer-function estimator;
3. selected tone frequencies, spacing, uniformity, excluded bins, and frequency
   window;
4. deconvolution/conditioning and regularisation or magnitude floor;
5. any matched background operation;
6. inverse-transform method, zero padding, range/time mapping, and envelope.

Keep complex quantities complex until the chosen final time-domain product is
formed. Nearest FFT-bin sampling is not exact-tone extraction for off-grid
physical tones; use a documented DTFT/DFT evaluation, or validate an equivalent
complex interpolation method.

## Impulse-response SFCW synthesis (Liu & Xiao 2021)

The default SFCW-equivalent method follows Liu & Xiao (2021,
*Fast Forward Simulation and Fusion for Stepped Frequency Ground Penetrating
Radar Signal Based on the Impulse-Response Principle*, Adv. Geosci. 11(4),
487-496). Because FDTD is linear time-invariant, one broadband impulse run
fully characterises the system: run a single unit-impulse excitation to obtain
the impulse response `h[n]`, then convolve it in the time domain with each
tone's continuous-wave excitation. This equals per-tone simulation to an
error below -200 dB while running FDTD only once.

Signal model and chain:

- tones `f_n = f_0 + (n-1)Δf`, bandwidth `B = (N-1)Δf`;
- distance `d` is encoded as phase `φ_n = 2πf_n·2d/v` across tones;
- synthesis: `y[n] = x[n] * h[n]` for each single-frequency `x[n]`;
- extraction: quadrature mixing `I_n = Rx·sin(2πf_n t)`, `Q_n = Rx·cos(2πf_n t)`,
  then low-pass to remove the `2f_n` term, giving the complex sample
  `Rx(n) = I_n + jQ_n = (A_n/2)e^{jφ_n}`;
- fusion: inverse transform of the N complex samples to a time-domain A-scan,
  then assemble traces into a B-scan.

Constraints to enforce:

- mesh by the highest tone: `dx ≤ c/(10·f_max·√ε_max)`; CFL
  `dt ≤ 1/[c·√(1/dx² + 1/dy² + 1/dz²)]`;
- time window must cover the two-way travel to the farthest target;
- ramp the transmitted tone onset (linear ramp `Tx(t)= (f_n t)·sin(2πf_n t)` for
  `f_n t < k`, then `sin(2πf_n t)`) to avoid Gibbs-type high-frequency artefacts;
- quadrature mixing must be followed by low-pass filtering, otherwise the `2f_n`
  component corrupts the baseband I/Q.

gprMax support (verified in 3.1.6): the built-in `impulse` waveform type is a
true single-FDTD-step delta (`#waveform: impulse 1 1e9 imp`), so no approximation
is needed for a Hertzian dipole source sampled at whole steps. The numeric
dispersion auto-analysis skips `impulse` (no defined peak frequency); compute
the cell/wavelength check explicitly instead. A user waveform file is only a
secondary approximation and must pass an explicit `fill_value=0` to avoid NaN.

Two equivalent routes exist; declare which one is used: the impulse-response
synthesis above, or a broadband flat-pulse excitation with exact complex
frequency sampling (the latter requires deconvolution and windowing and is what
many frozen project chains use).

## Source support and deconvolution

Inspect source spectral support over all claimed tones. Bins near a spectral null
need an explicit quality gate and regularised treatment; blind division amplifies
noise and numerical error. Apply the same source reference, phase convention,
conditioning, and window to compared traces.

Track simulation time zero, waveform origin, source peak/delay, electrical phase
reference, and reported range-zero datum separately. Remove a known source delay
once, not once in the transfer function and again in plotting.

## Background handling

For a controlled target-response diagnostic, first form identically calibrated
complex transfer functions and then calculate

`H_residual(f) = H_target_present(f) - H_background(f)`.

The resulting residual may expose target causality, but it is not raw field data
and does not by itself certify an engineering receiver cancellation method. Do
not subtract traces with different time grids, source references, precision, or
receiver definitions.

## Inverse reconstruction and envelope

For a uniformly spaced frequency grid compatible with a DFT/IFFT, construct the
appropriate Hermitian negative-frequency counterpart before requesting a real
time-domain trace. DC and Nyquist singleton bins must be real; inspect the IFFT
imaginary residue as a consistency check. For a nonuniform/off-grid tone set,
use and document a suitable complex inverse method rather than silently treating
it as an ordinary IFFT.

For a real A-scan `s(t)`, the Hilbert analytic signal is

`z(t) = s(t) + j H{s(t)}`

and the instantaneous-amplitude envelope is `|z(t)|`. It is nonnegative and
helps localise the strength and separation of oscillatory events; it does not
preserve reflection polarity or replace the original A-scan for phase analysis.

Zero padding refines displayed time/range-bin sampling only. It cannot add
bandwidth, improve physical delay resolution, or create an unmeasured response.

## Range mapping

State the coordinate datum and velocity model used to map delay to distance.
For dispersive media, use a defensible group-delay, frequency-dependent, or
calibrated mapping rather than assuming a single permittivity without support.
The bandwidth-derived delay response and the medium range conversion are separate
parts of the argument.
