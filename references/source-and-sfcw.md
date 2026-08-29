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
