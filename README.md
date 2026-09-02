# Fund Pool Model

这是一个面向公募基金研究的 Python 项目，覆盖基金池构建、历史净值抓取、因子计算、基金评分、组合构建、日常分析、点时滚动回测和因子实验。

项目重点是建立可复现、可审计的研究框架，并使用等权基准、交易成本、换手率和分阶段结果检验策略，而不是简单追求样本内最高收益。

## 文档导航

- [docs/PROJECT_WORKFLOW.md](docs/PROJECT_WORKFLOW.md)：全流程、代码模块和推荐执行顺序；
- [scripts/EQUITY_UNIVERSE_GUIDE.md](scripts/EQUITY_UNIVERSE_GUIDE.md)：方案 B 权益基金池构建；
- [src/backtest/BACKTEST_GUIDE.md](src/backtest/BACKTEST_GUIDE.md)：滚动回测和绩效口径；
- [docs/factor_optimization_report.md](docs/factor_optimization_report.md)：最新因子实验报告；
- [tests/README.md](tests/README.md)：测试范围、运行方法和测试边界。

## 1. 项目流程

```text
基金名录 / 基金池 CSV
        -> 方案 B 筛选、份额去重、数据质量检查
        -> 候选基金历史净值写入 db/fund_db.sqlite
        -> 净值转日收益
        -> 六个因子计算和稳健标准化
        -> 综合评分和 Top-N 选基
        -> 等权 / 逆波动 / 混合权重
        -> 日常分析、滚动回测、因子诊断和实验报告
```

日常分析回答“截至最新数据，当前哪些基金得分较高”；滚动回测回答“只使用当时可见数据，历史策略是否跑赢基准”。两者不能混用。

当前默认配置与方案 B 对齐：50 只权益基金、Top-10、等权、单线程抓取。首次运行会自动补齐总回报字段，后续按每只基金的最新日期增量更新。

## 2. 安装

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

没有 `requirements.txt` 时至少安装 `pandas`、`numpy`、`requests`、`akshare`、`python-dateutil`、`pytz` 和 `matplotlib`。SQLite 使用 Python 标准库，无需单独安装服务。

## 3. 当前方案 B 基金池

当前仓库实际使用的最终方案 B 文件是：

```text
data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv
```

它主要保留股票型和偏股混合型基金，排除债券、货币、FOF、QDII、ETF/指数联接、持有期等特殊产品，对 A/B/C 份额去重，并按历史长度、覆盖率和零收益比例筛选。

完整构建步骤见 [scripts/EQUITY_UNIVERSE_GUIDE.md](scripts/EQUITY_UNIVERSE_GUIDE.md)。最终目录包含 `universe_fund_v2_equity.csv`、`fund_pool_final_metadata.csv`、`fund_pool_audit.csv`、`fund_pool_summary.csv` 和 `fund_pool_review.csv`。

## 4. 日常分析

入口：`run_daily_fund.py`，核心实现：`src/pipeline/daily.py`。流程是：加载配置 -> 加载基金池 -> 抓取净值 -> 读取 SQLite -> 计算收益和基准 -> 计算六个因子 -> 标准化评分 -> 风险检查 -> Top-N 和三套权重 -> 写入数据库、CSV 和 HTML 报告。

使用方案 B 的示例：

```powershell
$env:FUND_UNIVERSE_CSV = "data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv"
$env:FUND_UNIVERSE_LIMIT = "50"
$env:FUND_TOP_N_FUNDS = "10"
$env:FUND_WEIGHT_SCHEME = "weight_equal"
$env:FUND_OUTPUT_DIR = "output/daily_v2"
.venv\Scripts\python.exe run_daily_fund.py
```

输出主要包括 `scores_YYYY-MM-DD.csv`、`portfolio_fund_YYYY-MM-DD.csv`、`report.html` 和 `run_manifest_YYYY-MM-DD.json`。研究实验仍建议显式写出全部参数。

## 5. 六个因子和评分

`src/domain/factors.py` 默认使用 252 个实际交易日窗口：

| 因子 | 含义 | 越好方向 |
|---|---|---|
| `ann_return` | 日平均收益率年化 | 越高 |
| `ann_vol` | 年化波动率 | 越低 |
| `down_vol` | 下行波动率 | 越低 |
| `mdd` | 最大回撤，数值为负 | 越接近 0 |
| `sharpe` | 风险调整收益 | 越高 |
| `ir` | 相对基金池等权基准的风险调整超额收益 | 越高 |

`src/domain/scoring.py` 会先缩尾，再用 MAD 稳健标准化，最后按 `factor_weights` 合成 `score` 并生成 `rank`。MDD 使用正权重，因为 MDD 是负数且越接近 0 越好。

## 6. 方案 B 滚动回测

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

滚动回测在每个调仓日只使用当时及以前的数据，新权重从下一交易日生效。严格 252 交易日窗口下，本次有效曲线从 2023-02-01 开始。输出包括 `rolling_equity_curve.csv/png`、`rolling_holdings.csv`、`rolling_trades.csv`、`rolling_metrics.csv`、`rolling_summary.csv`、`rolling_report.html` 和 `run_manifest.json`。

## 7. 因子诊断和评分实验

单因子分组诊断：

```powershell
.venv\Scripts\python.exe run_factor_diagnostics.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --rebalance month `
  --groups 5 `
  --output output/v2_factor_diagnostics
```

四套评分方案比较：

```powershell
.venv\Scripts\python.exe run_score_scheme_experiments.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --output output/v2_factor_optimization
```

四套方案定义在 `src/backtest/score_schemes.py`，固定 Top-10、等权、月度和 10 bps，只改变因子权重。配置敏感性实验由 `run_sensitivity_experiments.py` 运行，比较 Top-5/Top-10、三种权重、月度/季度调仓和 40% 权重上限。

## 8. 当前研究结论

`IR` 高低组下一期平均收益差约 `+0.487%`，`ann_return` 约 `+0.395%`，但两者相关性约 `0.972`。`return_ir` 完整区间净收益约 `20.43%`，等权基准约 `20.91%`，落后约 `0.48` 个百分点；前半段跑输、后半段跑赢，最大回撤约 `-32.12%`，年化换手约 `2.99x`。

因此 `return_ir` 仍是相对较好的候选方案，但四套方案在完整区间均未跑赢基准，不能称为稳定有效策略。完整结果见 [docs/factor_optimization_report.md](docs/factor_optimization_report.md)。

## 9. 代码、目录和测试

主要代码职责：`src/_config.py` 配置，`src/data/fetcher.py` 抓取，`src/data/repository.py` 数据仓储，`src/domain/factors.py` 因子，`src/domain/scoring.py` 评分，`src/domain/optimizer.py` 组合权重，`src/pipeline/daily.py` 日常流程，`src/backtest/rolling.py` 滚动回测，`src/backtest/engine.py` 历史持仓重放，`src/backtest/accounting.py` 换手和成本，`src/backtest/factor_diagnostics.py` 因子诊断。

```powershell
python -m unittest discover -v
```

项目使用基金日净值，不等同于真实成交记录。收益计算优先使用供应商日增长率，其次使用累计净值，最后才回退到单位净值。结果可能受到存活偏差、缺失净值、暂停申购、滑点、申购赎回费、基金池构成和样本区间影响。策略判断必须同时查看基准、CAGR、Sharpe、最大回撤、换手率、交易成本和分阶段表现。
