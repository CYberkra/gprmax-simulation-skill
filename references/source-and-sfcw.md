# Source and SFCW reconstruction: route by excitation

For the current Liu2021 workflow, read [liu2021-joint-chain.md](liu2021-joint-chain.md).
That reference replaces generic source deconvolution as the default in the D80
project. This file covers other source/transform choices and common conventions.

## Choose the correct input path

- Built-in unit impulse plus Liu2021 CW convolution: use the bundled corrected
  module. Keep its discrete normalization; do not add source division or dt
  factors without declaring and validating a changed convention.
- Ricker, sinc, measured or arbitrary pulse: inspect the complex source spectrum.
  Direct frequency sampling measures the pulse-shaped response. A transfer
  estimate needs a justified source reference and conditioning; it is not
  automatically a valid impulse input to the Liu2021 module.
- Direct per-tone FDTD: audit the actual waveform, settling time, phase reference,
  tone frequencies and run evidence. Do not relabel synthesized CW outputs as
  separately executed per-tone simulations.

Record source/time origin, tone grid, estimator, conditioning, filter/window,
background method, inverse transform and amplitude convention. Use exact DTFT
or a validated interpolation for off-FFT-grid tones; nearest FFT bins are not
an exact physical-frequency evaluation.

## Source recovery when required

Inspect support and spectral nulls before dividing by a source reference.
Declare regularization, excluded tones and conditioning; apply identical
operations to compared data. Source recovery from a band-limited pulse is a
separately validated branch, not a reason to overwrite frozen impulse outputs.

Keep waveform delay, electrical phase reference and range zero distinct.
Remove a known delay only once. Account for the source injection and units
before claiming an absolute physical transfer function.

## Background and complex information

Keep phase through demodulation, conditioning, background subtraction and inverse
reconstruction. Matched background subtraction is a controlled simulation
diagnostic, not proof of field cancellation performance. It requires compatible
receiver definitions, grids and normalization.

For SVD, specify the multi-trace matrix, domain, rank selection and target-loss
validation. Preserve the unfiltered data and evaluate a changed background
method as a changed processing chain, with reference/negative controls.

## Two different inverse products

For uniformly spaced measured tones, a complex baseband IFFT followed by abs
produces the Liu2021 project envelope. The lower frequency shifts carrier phase,
not this envelope; record f_start and delta_f. Do not require Hermitian completion
or a second Hilbert operation on this complex product.

When explicitly requesting a real passband time series, place tones at their
physical frequencies, construct the appropriate negative-frequency counterpart,
handle DC/Nyquist correctly and declare scaling. A real time-domain A-scan may
then use its Hilbert analytic magnitude. These are different products, not
mandatory consecutive stages.

For nonuniform tones use a documented inverse method rather than ordinary IFFT.
Zero padding changes sampling, not physical bandwidth or resolution. Include
IFFT normalization when comparing absolute amplitudes at different FFT lengths.

## Time and range

Record the periodic unambiguous time window 1/delta_f, observed propagation
window, geometric coordinate datum and velocity/range mapping. A dispersive,
bistatic, finite-target peak is not automatically the one-dimensional geometric
interface time. Separate geometry travel-time predictions from envelope maxima
and numerical/processing bias.
