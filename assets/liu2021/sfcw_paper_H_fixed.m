function [Rx, reldrift] = sfcw_paper_H_fixed(h, dt, F, k, steady_cyc, shift_ns)
% LIU2021 joint simulation demodulator, corrected project study44 algorithm.
% Source SHA256 and scope: references/d80-project-profile.md in this skill.
% Calculation body unchanged; this header corrects the original usage example.
% Caller must audit original dtype, finite data, timing and window validity.
% h and F must be real finite column vectors; dt and frequencies positive.
% Example:
%   [Rx, drift] = sfcw_paper_H_fixed(h, dt, F, .25, 3, 100);
%   prof = ifft(Rx, NFFT); tns = (0:NFFT-1).'/(NFFT*DF)*1e9;
%   envelope = abs(prof); % complex baseband magnitude, not real Ez
% No detection, interface attribution or hardware calibration is performed.

N = numel(h);
t3 = (0:3*N-1).' * dt;
L  = 2^nextpow2(4*N);
Hf = fft(h, L);
L2 = 2^nextpow2(6*N);
Rx = zeros(numel(F), 1);
reldrift = zeros(numel(F), 1);
mshift = round(shift_ns*1e-9/dt);
for i = 1:numel(F)
    f = F(i);
    cw = eq9_cw_ampramp(t3, f, k);
    y  = ifft(fft(cw, L) .* Hf, L);
    y  = y(1:3*N);
    Im = ideal_lp(y .* sin(2*pi*f*t3), f, dt, L2);   % cutoff = carrier f (correction 2)
    Qm = ideal_lp(y .* cos(2*pi*f*t3), f, dt, L2);
    M = max(1, round(steady_cyc / (f*dt)));
    i0 = 2*N - floor(M/2);
    iA = i0:(i0 + M - 1);
    iB = iA - mshift;
    Rx(i) = mean(Im(iA)) + 1j*mean(Qm(iA));
    RxB   = mean(Im(iB)) + 1j*mean(Qm(iB));
    reldrift(i) = abs(Rx(i) - RxB) / max(abs(Rx(i)), eps);
end
end

function cw = eq9_cw_ampramp(t, f, k)
% Paper Eq.(9): k f t sin(2 pi f t) for k f t < 1; sin(2 pi f t) otherwise.
% Carrier stays f; the AMPLITUDE ramps linearly (correction 1).
cw = zeros(size(t));
slow = (k*f*t) < 1;
cw(slow)  = (k*f*t(slow)) .* sin(2*pi*f*t(slow));
cw(~slow) = sin(2*pi*f*t(~slow));
end

function x = ideal_lp(x, fc, dt, L2)
X = fft(x, L2);
fr = (0:L2-1).' / (L2*dt);
d = min(fr, 1/dt - fr);
X(d > fc) = 0;
xp = real(ifft(X, L2));
x = xp(1:numel(x));
end
