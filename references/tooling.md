# 选择实际可用的工具

## 论文合成：随 skill 提供的 MATLAB 路径

在 MATLAB 中，把 skill 的 scripts 加到路径即可运行不产生输出文件的自检：

```matlab
addpath(fullfile(skill_root, 'scripts'));
validate_liu2021_chain;
```

正式处理先按输出审计参考核验原始数据和配对，再调用：

```matlab
addpath(fullfile(skill_root, 'assets', 'liu2021'));
[rx_target, drift_target] = sfcw_paper_H_fixed(h_target, dt, F, k, cycles, shift_ns);
[rx_background, drift_background] = sfcw_paper_H_fixed(h_background, dt, F, k, cycles, shift_ns);
profile = ifft(rx_target - rx_background, nfft);
time_ns = (0:nfft-1).' / (nfft * df_hz) * 1e9;
envelope = abs(profile);
```

这些变量来自研究配置，不依赖全局 MATLAB 工作区。IFFT 前要求 F 均匀递增，df_hz 与实际步长相同，nfft 不小于频点数；输出由研究脚本记录到该研究指定的新分析目录。模块仅接受实数 double 接收向量并检查参数/取样窗口；它不能从数组本身证明激发是单位冲激，输入文件审计仍不可省。

SVD 不包含在此示例中。没有匹配背景时不要虚造 h_background；选择已声明的无背景或多道处理分支，并记录其验证范围。

## 完整 Git 仓库的旧 Python CLI / GUI

只有含 pyproject.toml、scripts/cli.py、schemas 等代码的完整仓库才具备这条路径。单独安装本 skill 的文档和 MATLAB 文件，不等于安装了 Python CLI。

先检查 pyproject.toml 与实际 Python 版本；当前仓库要求 Python ≥3.11。可用时通过 `python -m scripts.cli --help` 核对命令，再使用对应子命令的 `--help`。不要要求不存在的可执行文件或虚构参数。

旧 impulse_lti 与 broadband_deconvolution 流程是不同实现；其存在不等于已接入本 skill 的修正 MATLAB 流程。旧数值门控和 F0–F5 机制仍按其程序执行，不能将它们的通过状态直接用作论文链验收。

完整仓库的 guided-setup、study-layout、study-materials 参考用于对应旧工具，不是论文分析的强制前置步骤。旧 docs/superpowers 计划用于追溯原设计，不覆盖当前入口。若用户要求把论文链接入 CLI，作为独立实现任务并做跨实现验证。

## 环境问题

自检应报告数值断言结果和进程退出状态。MATLAB 在计算通过后退出报错时，分开记录并检查环境；不要将退出故障改写成数值失败，也不要仅凭退出码忽略失败断言。依赖安装用隔离环境，不为复现旧工具改动项目的物理模型。
