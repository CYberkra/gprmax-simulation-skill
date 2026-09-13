function validate_liu2021_chain
% Numerical smoke check only: no gprMax run, output files or physical claims.
% MATLAB: addpath('<skill>/scripts'); validate_liu2021_chain
root = fileparts(fileparts(mfilename('fullpath')));
old_path = path;
restore = onCleanup(@() path(old_path)); %#ok<NASGU>
addpath(fullfile(root, 'assets', 'liu2021'));
dt = 8.747965457452526e-11;
N = 20578;
F = [30; 70; 150; 250] * 1e6;
h1 = zeros(N, 1); h1(101) = 1;
h2 = zeros(N, 1); h2(10001) = -.4;
[r1, d1] = sfcw_paper_H_fixed(h1, dt, F, .25, 3, 100);
[r2, d2] = sfcw_paper_H_fixed(h2, dt, F, .25, 3, 100);
[rs, ds] = sfcw_paper_H_fixed(h1+h2, dt, F, .25, 3, 100);
oracle1 = .5 * exp(-1j*2*pi*F*(100*dt));
oracle2 = -.2 * exp(-1j*2*pi*F*(10000*dt));
err = max([abs(r1-oracle1)./abs(oracle1); abs(r2-oracle2)./abs(oracle2)]);
linearity = max(abs(rs-r1-r2))/max(abs(rs));
assert(all(isfinite([r1; r2; rs; d1; d2; ds])), 'Nonfinite chain result');
assert(err < 1e-4, 'DTFT mismatch: check phase, ramp, normalization and steady state');
assert(linearity < 1e-11, 'Chain lost complex linearity');
fprintf('PASS implementation smoke check: DTFT relative error %.3g, linearity %.3g\n', err, linearity);
fprintf('Maximum synthetic-window relative drift %.3g (diagnostic only)\n', max([d1; d2; ds]));
fprintf('Not a direct-CW FDTD test or a resolution/attribution acceptance test.\n');
end
