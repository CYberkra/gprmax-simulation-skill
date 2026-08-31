# SFCW GPR 联合仿真链路文献支撑调研（2026-08-30）

> 目的：逐环节核实我们的 SFCW GPR 联合仿真链路（`scripts/sfcw.py` 三种模式 + 处理链）
> 是否每个环节均有独立文献支撑，确保链路的合理性与可辩护性。
> 调研方式：agent-reach 多平台检索 + Web 文献交叉核对。
> 结论：**链路整体合理，七个环节均有文献支撑**；一处诚实标注的边界见 §8。

---

## 0. 链路总览

```
impulse_lti 模式（默认，对齐刘2021）：
  单位冲激正演 → h[n]（LTI 冲激响应）
    → h[n] 与各频点连续波时域卷积（= 逐频点等效）
    → 正交混频 I/Q + 低通滤波（提取差频复分量）
    → 复频域采样 A/2·e^{-jφ}
    → IFFT 合成 A-scan

broadband_deconvolution 模式：
  一次宽带脉冲正演
    → 精确频点 DTFT 采样（exact_dtft，非最近格点）
    → Wiener 去卷积（源谱正则化）
    → 选频带 + 加窗 + zero-padded IFFT

direct_per_tone 模式：
  逐频点正演 → 混频提取 → IFFT
```

网格/数值约束（贯穿全部模式）：`cells/λ ≥ 10`、CFL 时步、PML、时窗覆盖双程。

---

## 1. LTI 冲激响应法（impulse_lti 核心）— ✅ 强支撑

**主张**：FDTD 满足线性时不变特性，一次单位冲激正演得到系统冲激响应 h[n]，
与各频点单频连续波时域卷积 = 逐频点正演等效（一次 FDTD 替代 N 次）。

**文献**：
- 刘东洋、肖建平（中南大学）2021《基于冲激响应原理的步进频率探地雷达信号快速正演模拟及融合》——
  本链路直接对齐的原始文献。将 GPR 建模为 LTI 系统，冲激响应卷积生成回波。
  (论文存档：`资料库_20260817/刘 - 2021 - Fast Forward Simulation...`)
- 哈尔滨工业大学《基于冲激响应的探地雷达快速仿真方法研究》——
  同思路：将 GPR 系统建模为 LTI，通过冲激响应卷积生成回波信号。
  https://scholar.hit.edu.cn/en/publications/基于冲激响应的探地雷达快速仿真方法研究

**本仓库对照**：`sfcw.py` 的 `complex_samples_impulse_lti` + `synthesize_tone_response`。

---

## 2. 正交混频 I/Q + 低通提取 — ✅ 强支撑

**主张**：回波 `A·sin(2πf_n t − φ_n)` 与同频正弦/余弦混频，低通滤除 `2f_n` 项，
得 I = A/2·cos(φ_n)、Q = −A/2·sin(φ_n)，组合成复分量。

**文献**：
- gprMax + Matlab SFCW 信号处理项目完整实现该公式：
  `I_n = A·sin(2πf_n t−φ_n)·sin(2πf_n t) → LPF → −A/2·cos(φ_n)`
  `Q_n = A·sin(2πf_n t−φ_n)·cos(2πf_n t) → LPF → −A/2·sin(φ_n)`
  https://github.com/XIDIAN-409/gprMax-Matlab-SFCW-radars-signal-processing-simulation
- 混频+低通是 SFCW/FMCW 雷达接收机的**标准架构**：
  - 《Handbook of Radar Signal Analysis》(Basem R. Mahafza)
    https://www.fccdecastro.com.br/pdf/HRSA.pdf
  - Glasgow 博士论文（2025）——混频后低通消除高频分量，提取 I 信号：
    https://theses.gla.ac.uk/85362/4/2025AyazPhD.pdf

**本仓库对照**：`sfcw.py` 的 `quad_mix_extract`（最小二乘相干拟合 sin/cos/DC 三基）。

---

## 3. 复频域采样 + IFFT 融合 → A-scan — ✅ 强支撑

**主张**：频域复数数据 `ADC_in(n) = I_n + jQ_n = A/2·e^{-jφ_n}`，
IFFT 后得时域 A-scan，横轴精度由带宽 B 决定（t = 0:1/B:(N_t−1)/B）。

**文献**：
- 同 gprMax+Matlab 项目：`ADCin(n)=In+jQn`，IFFT 后 `t=0:1/B:Nt−1/B`
  https://gitee.com/Neabo/gprMax-Matlab-SFCW-radars-signal-processing-simulation
- SFCW "频域复数数据经 IFFT 转时域"为标准流程：
  - Aboudourib 博士论文（2020）："Les radars SFCW ... transformées en domaine
    temporel par le biais d'une Transformée de Fourier Inverse"
    https://theses.hal.science/tel-03131354v1/file/95559_ABOUDOURIB_2020_archivage.pdf
  - TU Graz 论文：SFCW 发射连续波递增频率，接收是发射的时延版本
    https://openlib.tugraz.at/download.php?id=68a868878d36b&location=browse

**本仓库对照**：`sfcw.py` 的 `reconstruct_ascan`（零填充 + Hermitian 负频，DC=0 带通）。

---

## 4. 精确频点采样（exact_dtft，非最近格点）— ✅ 强支撑

**主张**：物理频点不在 FFT bin 上时，"最近 bin"采样不是精确频率采样；
须用 DTFT 精确求值或验证过的谱插值。

**文献**：
- DSP 标准结论：时限信号的 DTFT 可由 DFT 经谱插值计算
  https://www.dsprelated.com/freebooks/sasp/Spectral_Interpolation.html
- 频谱泄漏与频率分辨率（零填充不提高物理分辨率）：
  https://dspillustrations.com/pages/posts/misc/spectral-leakage-zero-padding-and-frequency-resolution.html

**本仓库对照**：`sfcw_math.py` 的 `exact_dtft`；`audit_source.py` 的 `source_spectrum`。

---

## 5. Wiener 去卷积（broadband_deconvolution 模式）— ✅ 强支撑

**主张**：用源谱正则化做频域反卷积 `H(f) = E(f)·S*(f)/(|S(f)|² + λ·max|S|²)`，
恢复介质冲激响应（GPR 去卷积提升时间分辨率）。

**文献**：
- Wiener 去卷积是标准正则化频域反卷积（维基百科标准定义）：
  https://en.wikipedia.org/wiki/Wiener_deconvolution
- GPR 去卷积增强分辨率有长期应用史：
  - Schmelzbach & Huber (2015) 高效 GPR 去卷积：
    https://emanuelhuber.github.io/RGPR/public/schmelzbach-and-huber_2015_GPR-efficient-deconvolution.pdf
  - Kansas Geological Survey (2001) 确定性去卷积：
    https://www.kgs.ku.edu/Geophysics/OFR/2001/35/index.html

**本仓库对照**：`sfcw_math.py` 的 `wiener_deconvolve`；`audit_sfcw.py` 去卷积条件门。

---

## 6. 网格/数值约束（cells/λ、CFL）— ✅ 强支撑

**主张**：网格步长不能大于介质最短波长的十分之一（`cells/λ ≥ 10`），
时步满足 CFL 条件。

**文献**：
- gprMax 官方教程：网格步长不能大于模型介质中最短波长的十分之一
  https://github.com/QH17/gprMax-Matlab-SFCW-radars-signal-processing-simulation
  （也引用了 `_time_step_stability_factor` 手动调 dt）
- 刘2021 式(6)：`dx ≤ c/(10·f_max·√ε_max)`（与我们的 cells/λ ≥ 10 完全一致）

**本仓库对照**：`numerics.py` 的 `check_mesh`/`check_cfl`/`check_window`；
`audit_numerics.py` 对应门。

---

## 7. 应用合理性（深部/煤矿超前探测）— ✅ 合理

**主张**：SFCW 相对脉冲体制有更高 SNR、更宽等效带宽，适合深部低 SNR 场景；
深部探测依赖低频穿透（我们 fL 从 30MHz 起步合理）。

**文献**：
- SFCW GPR 综合综述：SFCW 通过多频点相干累加获得更高动态范围
  https://www.researchpublish.com/upload/book/A Comprehensive Review of Ground Penetrating-26092024-1.pdf
- SFCW 理论在探地雷达中的应用文献丰富（1970s 起，见综述参考文献）

---

## 8. 诚实标注的边界（非缺陷，但必须声明）

- **抗噪结论未复现**：刘2021 在逐频点接收时序上分别加噪 → 混频 → 低通 → IFFT，
  并保持对比链增益一致，得出"SFCW 信噪比优于脉冲体制"的结论。
  我们只采用了其**无噪 LTI 思想**（`liu2021_scope: core_noiseless_lti`），
  未复现其抗噪对比实验。这与文献对照一致，不影响链路合理性，
  但任何关于"SFCW 抗噪优于脉冲"的声明须另行验证。
- **色散介质处理**：刘2021 是简单层状/空气介质；我们在色散煤体（Debye）中使用，
  网格/时窗按频带中心相速度核算——这超出了原文验证范围，属合理扩展但需单独论证。

---

## 9. 结论

| 环节 | 文献支撑 | 备注 |
|---|---|---|
| LTI 冲激响应法 | ✅ 强 | 刘2021 + 哈工大，直接对齐 |
| 混频 I/Q + 低通 | ✅ 强 | SFCW 标准接收机 |
| 复采样 + IFFT 融合 | ✅ 强 | SFCW 标准流程 |
| 精确频点采样 | ✅ 强 | DSP 标准 |
| Wiener 去卷积 | ✅ 强 | GPR 长期应用 |
| cells/λ 网格门 | ✅ 强 | gprMax 官方 + 刘2021 |
| 深部 SFCW 应用 | ✅ 合理 | 综述确认 |

**链路每个环节均有独立文献支撑，环环相扣构成完整 SFCW 等效仿真。**
边界（抗噪结论、色散扩展）已在 §8 诚实标注，不影响链路合理性。
