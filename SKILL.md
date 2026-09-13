---
name: gprmax-simulation
description: Build, run, process, and audit reproducible gprMax studies, including the corrected Liu2021 impulse-response and SFCW joint simulation workflow, interface ablations, and target-size searches. Use for gprMax cases, outputs, or simulation-chain claims; not for unrelated presentation styling.
metadata:
  short-description: gprMax 与 Liu2021 冲激响应联合仿真
---

# gprMax 联合仿真

以可追溯的模型、原始输出、复数处理链和有边界的结论交付研究。当前 D80 项目的默认 SFCW 路径采用已修正的 Liu2021 冲激响应联合仿真；不能把旧源反卷积流程、旧区域选峰通过状态和论文合成模块混成一套已验证的方法。

## 先确定本次范围

读项目 AGENTS.md、当前研究输入/说明与用户提供材料。沿用用户已经确定的模型、材料、运行环境和处理选择；仅询问会实质影响任务的缺失信息，不重复做全套访谈或要求确认已授权事项。

区分本轮是设计、只读审查、生成输入、执行、取回、分析还是修改 skill。准备和分析不自动授权新的远程正演。明确的执行授权持续有效，不因分阶段操作重复询问；新物理问题、显著额外算力或不同运行环境按实际任务范围处理。

记录科学问题、参照案例、允许结论，以及 single_variable 或 multi_factor 设计。列出每个变化因素与不变量，不把多个因素同时改变的结果称作单因素因果证据。

## 按任务读取参考

- 新建/修改模型或尺寸矩阵：读 [simulation-contract.md](references/simulation-contract.md) 和 [numerical-model-validity.md](references/numerical-model-validity.md)。
- 当前论文联合仿真：读 [liu2021-joint-chain.md](references/liu2021-joint-chain.md)；D80 项目同时读 [d80-project-profile.md](references/d80-project-profile.md)。
- 用户指定普通脉冲、源恢复或其他 SFCW 路径：读 [source-and-sfcw.md](references/source-and-sfcw.md)，明确与论文路径的差异。
- 准备运行、断点续跑或取回：读 [preflight-and-audit.md](references/preflight-and-audit.md)。
- 判读峰值、消融、检测、厚度或体积下限：读 [interpretation-and-claims.md](references/interpretation-and-claims.md) 和 [gates-and-claims.md](references/gates-and-claims.md)。

参考里的 D80 数值仅是该项目配置。其他模型应从本地输入建立参数，不照搬域大小、材料、频段、GPU 或 80 m 距离。

## 联合仿真的主流程

模型与输入验收 → gprMax 单位冲激正演 → 原始输出审计 → 每频点连续波与冲激响应线性卷积 → sin/cos 正交解调及稳态提取 → 复频谱背景处理 → 复 IFFT 与包络 → 诊断/界面归因 → 限定范围的结论。

复用 [修正 MATLAB 模块](assets/liu2021/sfcw_paper_H_fixed.m)，随新包记录来源和实际文件哈希。模块采用 Eq.9 幅度缓升和截止为载频 f 的低通；不得从 41–43 包复制旧 sin(2*pi*k*f*t) 或 LP=Δf。源恢复、额外窗函数、增益、平滑和 SVD 都是显式处理变更，不能悄悄插入冻结链。

从复频谱得到的复基带轮廓直接取模作为包络。不要强制补共轭频谱或对复轮廓再做 Hilbert。背景差分应在取模之前；原始场、处理结果和仅供展示的归一化图分开保存。

随附 [实现自检](scripts/validate_liu2021_chain.m) 不需要新的 gprMax 仿真；其通过只说明合成实现的数值检查通过，不代表直接 CW 等效验证或两个界面可分辨。已有兼容直接 CW 证据可复用，不要求每个尺寸包新增 CW 正演。

## 建模、执行与取回

报告实际体素厚度、体积和面坐标，检查材料、收发、网格对齐、PML 和时窗。不要悄悄更改原波形、材料、网格或精度。保留冻结研究，新物理模型进入新日期研究包。

使用研究提供的运行器、案例清单和断点续跑机制。运行前检查实际构建与显存；-gpu 不证明 FP64。已有完整且兼容的输出优先复用，存在文件不等于可以跳过审计。

取回按清单对账输入、几何/生成器、材料、运行日志、版本、输出和哈希。原始 HDF5 的接收分量、dtype、dt、样本数和有限值不过关时，不进入定量分析。不要把转换成 double 的数据当作原始 FP64 证据。记录已完成、缺失、失败和未匹配的案例。

## 定量判读与已知限制

合成数值一致、出现两个包络峰、前后界面关联、检测概率和最小目标是不同结论。一个层级通过不自动使其他层级通过。

旧区域选峰 v2 已有单反射旁瓣误判反例。可以复现历史指标或做明确标记的探索，但不能单凭“局部双峰 + 间距 + 3 dB 谷”认证最小可分辨目标。先做单反射负控、已知双反射对照和现有消融复核，再冻结科学验收规则；不在本 skill 中虚构已经验证的新检测器。

消融差值包含几何变化引起的耦合，不称纯界面分量；恒等式闭合和脚本成功运行不充当物理验收。界面峰位应从指定数据/版本产生，不能用写死的峰位和无条件 PASS 冒充重新验证。

尺寸搜索区分目标几何族，分别扫厚度和截面后实际测试联合缩小点。保留失败与未测点，不能把两个单轴最小值相乘。输出“当前模型与所测范围内”的下限；噪声、背景算法、形态、网格或位置改变后重新评价适用性。

SVD 可替换背景处理步骤，但先定义多道矩阵、删秩策略与目标保留验证。当前单道背景差分不能直接证明 SVD 后的检测/分辨能力。

## 收尾

交付输入/生成器、配置与版本、运行和取回证据、原始输出、处理代码、参数、指标和清楚的局限。只读审查不修改研究包。沿用仓库目录约定；已有 manifest 足够表达契约时，不强制另建重复 YAML 或不存在的工具系统。

汇报图优先用“原目标”“后端延长对照”“后端变化相关响应”等易懂中文，保留必要模型条件与单位；内部案例代号和差分符号放到技术附录。完整复数定义仍需在分析文件中可追溯。
