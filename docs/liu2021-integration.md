# Liu2021 联合仿真更新范围

本次更新 skill 入口、相关参考和可复用 MATLAB 合成模块。原有 Python CLI、GUI、schemas、templates 和测试保留，未将论文合成算法接入这些程序入口。

论文流程从 [SKILL.md](../SKILL.md) 和 [联合仿真参考](../references/liu2021-joint-chain.md) 进入；实际合成使用 [MATLAB 模块](../assets/liu2021/sfcw_paper_H_fixed.m)。旧 CLI 的 impulse_lti、broadband_deconvolution 等模式不因文档更新而自动成为 Liu2021 修正链。

原先 CLI 的门控/等级机制仍是对应程序的实际行为；新版参考中的证据语义不代表这些程序已经改造。使用旧工具时核验命令和实现，不把其运行成功或等级标签代替物理验证。旧设计文档描述原有实现，论文复刻的处理规范以新版入口及联合仿真参考为准。

附带 validate_liu2021_chain MATLAB 自检不需要 gprMax 正演，只验证合成实现与离散频域计算、线性关系。它不证明直接 CW 正演等效性或两个界面可分辨。当前历史选峰 v2 的单反射旁瓣误判已有记录，本次发布没有宣称实现新的可靠检测器。
