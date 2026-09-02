# 回测与绩效口径说明

本项目有两种回测模式：`rolling.py` 的点时滚动回测，以及 `engine.py` 的历史持仓重放。研究策略是否具有预测能力时，应优先使用滚动回测。

## 1. 两种入口的区别

### 1.1 点时滚动回测：`src/backtest/rolling.py`

每个调仓日执行以下操作：

1. 读取截至调仓日的历史收益；
2. 计算当日可见的六个因子；
3. 计算评分并选择 Top-N；
4. 生成目标权重；
5. 从下一交易日起应用新权重，直到下一次调仓。

因此它可以检验历史上“当时可见信息”形成的策略，默认支持 `month`、`quarter` 和 `week` 调仓。

### 1.2 历史持仓重放：`src/backtest/engine.py`

该模式从 SQLite 的 `portfolio_results` 表读取已经保存的历史权重，然后重放这些权重对应的净值曲线。它不会重新计算过去每个调仓日的因子和评分，适合检查已持久化的日常组合结果，不适合单独用来验证一个新的历史选基逻辑。

两种模式共同使用：

- `src/backtest/accounting.py`：调仓生效、权重变化、换手和成本；
- `src/backtest/metrics.py`：累计收益、CAGR、年化波动率、Sharpe、最大回撤；
- `src/reporting/charts.py`：策略与基准净值图。

## 2. 推荐滚动回测命令

方案 B、Top-10、等权、月度调仓、10 bps 成本的固定基线：

```powershell
$env:FUND_UNIVERSE_CSV = "data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv"
$env:FUND_UNIVERSE_LIMIT = "50"
$env:FUND_OUTPUT_DIR = "output/v2_equity_pool"

.venv\Scripts\python.exe run_rolling_backtest.py `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --rebalance month `
  --cost-bps 10 `
  --top-n 10 `
  --weight-scheme weight_equal `
  --max-weight 1.0
```

参数说明：

| 参数 | 含义 |
|---|---|
| `--start` / `--end` | 请求回测区间 |
| `--rebalance` | `month`、`quarter` 或 `week` |
| `--cost-bps` | 每 1 单位完整交易名义金额的成本，10 bps = 0.1% |
| `--top-n` | 每次调仓选出的基金数量 |
| `--weight-scheme` | `weight_equal`、`weight_risk_parity` 或 `weight_mixed` |
| `--max-weight` | 单只基金权重上限，`1.0` 表示不设上限，例如 `0.4` 表示 40% |

`Config` 默认是方案 B、Top-10 和等权。为了保证实验可比性，研究命令仍应显式指定 Top-N、权重方式和输出目录。

## 3. 防止前视偏差的执行时点

调仓日只用于生成目标权重，不使用调仓日之后的数据。新权重从下一交易日开始生效。这样可以避免用当天收盘后才知道的数据去解释当天收益。

因子窗口默认 252 个实际交易日。即使命令的 `--start` 是 2022-01-01，实际第一笔可计算因子并执行组合的日期通常会晚于请求起始日；具体日期以本次输出的 `rolling_equity_curve.csv` 为准。

## 4. 换手和交易成本口径

设调仓前权重为 `old_weight`，调仓后目标权重为 `new_weight`：

```text
turnover = 0.5 * sum(abs(new_weight - old_weight))
traded_notional = sum(abs(new_weight - old_weight))
transaction_cost = traded_notional * cost_bps / 10000
```

`turnover` 是常用的单边组合换手率；`traded_notional` 同时包含卖出和买入的完整成交名义金额，因此成本按完整成交金额计算。首次建仓没有前一期持仓，默认不收取成本。最后一个调仓日如果没有后续交易日执行，也不会产生实际执行成本。

`rolling_trades.csv` 中常见字段：

- `date`：目标调仓日期；
- `effective_date`：实际开始执行权重的交易日；
- `turnover`：单边换手率；
- `traded_notional`：完整成交名义金额；
- `cost`：按理论目标权重计算的成本；
- `applied_cost`：实际从净收益中扣除的成本；
- `fund_count`：调仓后实际持仓数量。

## 5. 基准和缺失收益处理

基准是基金池中当日有有效收益数据的基金等权平均收益，不是某个市场指数。策略和基准使用同一段日期进行比较。

当前会计逻辑对持仓基金缺失的当日收益按 0 处理，并在 `rolling_equity_curve.csv` 输出 `return_coverage`。这方便保持曲线连续，但不等同于真实可交易收益，报告中必须检查覆盖率。

## 6. 输出文件

滚动回测输出到 `FUND_OUTPUT_DIR` 指定目录：

- `rolling_equity_curve.csv`：策略毛收益、净收益、基准收益、毛净值、净净值和覆盖率；
- `rolling_equity_curve.png`：策略与等权基准净值曲线；
- `rolling_holdings.csv`：每次调仓入选基金、评分、排名和三套权重；
- `rolling_trades.csv`：调仓、换手、名义金额和成本；
- `rolling_metrics.csv`：`strategy_gross`、`strategy_net`、`equal_weight_benchmark` 的绩效指标；
- `rolling_summary.csv`：总收益差、CAGR 差、年化换手率、累计成本和 `beat_benchmark`；
- `rolling_report.html`：可直接在浏览器查看的指标和净值图。

## 7. 指标定义

`src/backtest/metrics.py` 使用日收益计算：

- 总收益：最终净值 - 1；
- CAGR：按曲线实际起止日期折算的年化复合收益；
- 年化波动率：日收益标准差乘以 `sqrt(252)`；
- Sharpe：年化平均收益除以年化波动率，当前未扣除无风险利率；
- 最大回撤：净值相对历史峰值的最小跌幅。

## 8. 两类研究实验

### 8.1 配置敏感性

```powershell
.venv\Scripts\python.exe run_sensitivity_experiments.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --cost-bps 10 `
  --output output/v2_sensitivity
```

该实验改变 Top-5/Top-10、三种权重方式、月度/季度调仓和 40% 权重上限，用来回答组合构建方式的影响。

### 8.2 评分方案实验

```powershell
.venv\Scripts\python.exe run_score_scheme_experiments.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --output output/v2_factor_optimization
```

该实验固定 Top-10、等权、月度和 10 bps，只比较四套 `factor_weights`。详细结果见 [factor_optimization_report.md](../../docs/factor_optimization_report.md)。

## 9. 常见误读

- 策略总收益高于基准不代表风险调整后更好，必须同时查看 CAGR、Sharpe、回撤和成本；
- 全区间跑赢不代表多时期稳定，至少拆分前半段和后半段；
- 调整基金池和评分权重后，不能直接把新旧结果归因于某一个改动；
- `mdd` 是负数，越接近 0 越好，不能使用错误的负权重；
- 日常 `run_daily_fund.py` 的最新截面结果不能替代点时滚动回测。
