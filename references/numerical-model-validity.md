# Numerical model validity

Read for mesh, material dispersion, boundary, precision or hardware feasibility
decisions. Project values belong in its contract, not universal hard gates.

## Mesh and dispersion

Compute cells across target thickness, gaps, roughness and the shortest relevant
material wavelength over the claimed band. Use frequency-dependent phase velocity
where appropriate, not a band-centre velocity to certify an entire dispersive band.
About ten cells per shortest wavelength is a useful initial guideline, not a
convergence proof or an automatic reason to discard an existing diagnostic run.

Validate sensitive observables through controlled refinement when claiming a
physical size limit. Record nominal and actual cell geometry, including any
centre shift caused by even/odd cell counts. More IFFT points cannot cure a coarse
FDTD mesh.

Check the CFL limit and the actual solver's material-model restrictions against
its version/documentation. Do not impose an unsupported universal tau/dt > 4.
A stable run alone does not establish small phase error.

Official reference: https://docs.gprmax.com/en/latest/gprmodelling.html

## Boundaries and travel time

Record PML thickness, material continuation, clearance and relevant travel paths.
Check possible boundary contributions against the analysis window and allowed
error; use an appropriate boundary-control case when needed.

An object stopped at the inner PML face has a material termination. It does not
become infinite just because PML starts nearby. A time estimate through the
slowest target path is not necessarily the earliest possible return. Band-limited
reconstruction and noncausal FFT filters can leak out-of-window responses into
the displayed window, so plot cropping is not proof of isolation.

## Source and receiver representation

Record ideal source versus antenna/port model, component, orientation and Yee-grid
position. Ideal Ez measurements are not calibrated voltage, dBm or hardware SNR.
For antenna/port models check feed connectivity, loading and material assignment.

Do not make a finite object obey infinite-interface polarity or one-dimensional
arrival-time assumptions without checking the scattering regime.

## Precision and execution resources

-gpu selects GPU execution; it does not prove FP64. Verify solver build and the
raw receiver dtype before casting. Estimate RAM/VRAM and disk from the actual
domain and build; small targets do not reduce a fixed full-domain FDTD cost.

There is no universal FP32 noise floor in dB relative to a direct wave. Roundoff,
background cancellation, propagation and implementation affect the usable
dynamic range. Follow the project's precision requirement and test numerical
error where the signal is small.

Probe only resources relevant to the authorized task: GPU/VRAM, memory, output
disk, Python/gprMax/build/CUDA as needed. Reuse the user's chosen environment;
do not switch precision, shrink a physical domain or silently choose a different
server to make a run fit.

## Minimal evidence

Use supplied geometry/configuration tests and raw-output schema checks. A small
smoke case is useful when it answers an unresolved implementation question and
is within scope; it is not a mandatory new run for every analysis. Keep expensive
simulations outside unit tests, preserve comparison observables and provenance,
and record exactly what remains unvalidated.
