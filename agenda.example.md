# Research Agenda（示例模板）

> 真实版本放在 GitHub Secret `AGENDA` 里, 永远不进仓库.
> 写给筛选引擎看的: 它会按"这篇论文会不会推进/挑战下面任何一项研究兴趣"来排序.
> 写得越具体, 排序越准.

## 主要方向

长期期权 (long-dated options, LEAPS, 长期限 VIX 衍生品, 保险/养老金嵌入期权) 的定价、对冲、隐含信息提取.

## 当前关注的核心问题

- 长期波动率曲面的建模 (rough volatility 模型的长端拟合稳定性, SVI 在 1Y+ 的外推, 二维曲面联合校准)
- 长期期权的流动性溢价: 怎么从市场价格里识别出来、对定价模型的影响
- 隐含波动率期限结构与长期股权风险溢价的关系
- 美式 / 百慕大 / autocallable 等带提前行权特征的长期合约的最优停时
- 神经网络在长期定价中的外推稳定性 (短期数据训练能否泛化到长期限)

## 兴趣方向（次要）

- 一般数值方法: PDE 求解, Monte Carlo 方差减少, Fourier 方法 (Heston 半解析)
- variance / volatility swap 的对冲与风险溢价
- 跳跃扩散 (jump-diffusion) 与 regime-switching 模型
- 结构化产品 (autocallable, cliquet) 的定价与希腊字母

## 想合作 / 可能的选题方向

- 实证: 用 OptionMetrics / CBOE LiveVol 数据研究 LEAPS 与短期期权的定价偏差
- 神经网络在长期定价中的外推稳定性 (toy 数据 + 实证联合验证)
- 跨资产长期波动率: 股票 LEAPS vs 长期利率期权的相关性结构
- 嵌入期权: 养老金 GMxB 合约的对冲成本与监管资本

## 不感兴趣

- 实物期权 (real options) — 公司金融方向, 与衍生品定价是同名异方向
- 高管股权激励 (executive stock options) 相关研究
- 纯理论无法落地的极端假设论文 (例: 必须假设连续无套利市场 + 完美对冲且无任何摩擦)

## 期刊优先级 (供模型参考权重)

- **第一档**: Journal of Finance, Journal of Financial Economics, Review of Financial Studies, Mathematical Finance, Finance and Stochastics
- **第二档**: Quantitative Finance, Journal of Derivatives, Review of Derivatives Research, Journal of Computational Finance
- **预印**: arXiv q-fin.PR / MF / CP (注意作者机构和已被接收信号)
