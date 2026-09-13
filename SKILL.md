---
name: gprmax-simulation
description: Plan, run, and audit gprMax studies; synthesize SFCW responses with the corrected Liu2021 impulse-response workflow; evaluate interface ablations and target-size limits.
metadata:
  short-description: gprMax 与 Liu2021 冲激响应联合仿真
---

# gprMax 联合仿真

默认沿用用户已确定的模型、材料和处理方案。D80 项目采用修正后的 Liu2021 冲激响应流程；其他项目先识别激发与目标，不能直接套用 D80 参数。

## 选择本次路径

只读取当前任务需要的参考；已有信息足够时直接推进，不重复访谈。

| 任务 | 读取 | 完成条件 |
|---|---|---|
| 设计或修改模型 | [模型契约](references/simulation-contract.md)、[数值有效性](references/numerical-model-validity.md) | 因素、不变量、实际网格几何及验证计划明确 |
| 运行、续跑、取回或审计输出 | [执行与输出审计](references/preflight-and-audit.md) | 输入、运行、原始输出及哈希对应；缺失和失败单列 |
| 论文联合仿真 | [Liu2021 处理链](references/liu2021-joint-chain.md) | 复频谱、轮廓、参数与数值检查可追溯 |
| 普通脉冲或其他频域方法 | [其他源与重建路径](references/source-and-sfcw.md) | 源、变换、背景与幅度约定明确 |
| 双峰、消融或最小目标 | [判据与归因](references/interpretation-and-claims.md) | 指标与物理解释分开，负控和搜索范围明确 |

当前 D80 任务另读 [项目配置](references/d80-project-profile.md)；选择 MATLAB 或仓库 CLI 时读 [工具入口](references/tooling.md)。需要解释状态字段时读 [证据状态](references/gates-and-claims.md)。

## 论文流程的关键约定

单位冲激正演 → 输出审计 → 逐频连续波线性卷积 → 正交解调与稳态提取 → 复频谱背景处理 → 复 IFFT 取模。

使用随附 [MATLAB 模块](assets/liu2021/sfcw_paper_H_fixed.m)，不重新手写：Eq.9 改变幅度而非载频，低通截止为 f 而非 Δf。复轮廓直接取模；不先取模再相减，也不额外做 Hilbert。源恢复、窗函数、增益或 SVD 属于显式处理变更。

[实现自检](scripts/validate_liu2021_chain.m) 无需正演。旧区域选峰 v2 有单反射旁瓣误判，不能独立认证最小目标；算法细节与反例见判据参考。

## 执行底线

- 读项目 AGENTS.md 与实际输入，记录变化；保留冻结包，新物理模型另建研究包。
- 准备/只读分析不启动新正演；已有执行授权无需重复确认。兼容、完整的旧输出优先复用。
- -gpu 不证明 FP64；审计原始 dtype、有限值、dt、样本数及来源之后再处理。
- 分开报告运行完整性、数值一致性、分离指标和界面归因；不可分辨是有效实验结果，不是运行失败。
- 只读审查不修改研究包。交付保留复数定义与单位，展示图用易懂名称；内部符号可放技术附录。
