# Numerical model validity

Use this reference for mesh, precision, source/receiver, boundary, antenna, or
hardware-feasibility decisions.

## Mesh and domain

Audit cell counts across every feature that controls the requested observable:
target thickness, gaps, interface roughness, source/receiver separation,
conductors/feeds, and the shortest material wavelength relevant to the claimed
band. State nominal dimensions and realised mesh dimensions. Refine deliberately
and compare against a defined observable when numerical convergence matters.

Choose domain extents and PML clearance so that boundary interactions cannot
reach the receiver in the analysed time window. Record the time window, rather
than assuming a plot range proves the model was long enough.

## Source, receiver, and representation level

Record source type, position, orientation/polarization, waveform, receiver
component, and whether Tx/Rx are colocated. Check the actual discretised source
and receiver location after model generation.

Distinguish an ideal field source, an electromagnetic antenna model, and a
calibrated hardware/system model. Relative field quantities cannot be relabelled
as received voltage, dBm, receiver SNR, or hardware probability of detection
without a stated and validated field-to-system calibration.

For port or antenna models, inspect feed connectivity, return path, loading,
conductor/material overlap, and Yee-cell alignment. A visually plausible antenna
does not establish an electrically valid feed.

## Precision and execution feasibility

Record requested precision separately from output evidence. Confirm output dtype
from the receiver dataset; a filename, command line, or script flag is not
proof. Assess available device memory against the actual model and selected
precision before running. If the selected build cannot meet the requested
setting, stop and report the constraint rather than quietly changing it.

## Minimal numerical evidence

Use inexpensive, focused checks before a large sweep: material assignment,
geometry alignment, source/receiver placement, intended output dataset, and one
small smoke case if it is permitted. Keep expensive simulations out of automated
unit tests. For a formal numerical claim, retain the test definition, comparison
observable, and evidence rather than only a final plot.

## Generic numerical gates

Use general-purpose defaults, never project-specific values:

- mesh the highest tone: cells per wavelength ≥ 10 at the top of the band using
  the shortest material wavelength (for dispersive media take the phase
  velocity near band centre); anisotropic grids (dx≠dy≠dz) are allowed but the
  observable-controlling direction must be stated;
- time step from the CFL condition; for Debye-type media check τ/dt > 4;
- PML layers from 10 upward; domain and PML clearance must keep boundary
  interactions out of the analysed time window;
- precision: fp32 floor is about -90 dB relative to the direct wave; a demand
  beyond roughly 110 dB dynamic range requires fp64. Verify dtype from the
  output dataset, never from a filename or command flag.

## Environment probe

Probe the local environment (GPU model, VRAM, CUDA, system memory, free disk on
the output volume, Python version, gprMax presence/version) so the model plan
can be matched to real resources. The probe is informational only: it never
decides whether to run locally or on a server — that decision belongs to the
user. Do not collect CPU model, usernames, directory listings, file contents,
process lists, or network connections.
