# 项目总流程与模块导航

这份文档从整体上说明项目各模块的职责、输入输出和推荐使用顺序。详细的回测口径见 [BACKTEST_GUIDE.md](../src/backtest/BACKTEST_GUIDE.md)，基金池构建见 [EQUITY_UNIVERSE_GUIDE.md](../scripts/EQUITY_UNIVERSE_GUIDE.md)，因子实验结果见 [factor_optimization_report.md](factor_optimization_report.md)。

## 1. 系统分层

```text
数据源 / 本地 CSV
        |
        v
Fetcher -> Repository -> db/fund_db.sqlite
        |                 |
        |                 +-- fund_nav_daily
        |                 +-- portfolio_results
        v
UniversePool -> fund_code 基金池
        |
        v
日收益 -> 六个因子 -> 稳健标准化评分 -> Top-N 组合
        |                                  |
        |                                  +-- 等权
        |                                  +-- 逆波动
        |                                  +-- 混合权重
        v
日常分析输出 / 滚动回测 / 因子诊断 / HTML 报告
```

## 2. 两条主流程

### 2.1 日常分析流程

入口：`run_daily_fund.py`，核心实现：`src/pipeline/daily.py`。

```text
读取 Config
  -> 加载基金池
  -> 首次补齐总回报字段 / 后续按基金最新日期增量写入净值
  -> 从 SQLite 读取净值
  -> 计算日收益和等权基准
  -> 计算 ann_return / ann_vol / down_vol / mdd / sharpe / ir
  -> 因子缩尾、MAD 标准化和加权评分
  -> 风险检查
  -> 选 Top-N 并计算三套权重
  -> 写入 portfolio_results 和 CSV
  -> 生成 report.html
```

这条流程回答“截至最新数据，今天哪些基金得分较高”。它不是历史滚动回测，不能直接用来证明过去的策略表现。

### 2.2 历史研究流程

入口：`run_rolling_backtest.py`、`run_factor_diagnostics.py` 和 `run_score_scheme_experiments.py`。

滚动回测在每个调仓日重新计算当时可见的历史因子，目标权重从下一交易日生效。因子诊断计算各因子分组的下一期收益。评分方案实验在同一基金池、Top-N、权重、调仓频率和成本下比较不同 `factor_weights`。

## 3. 推荐执行顺序

### 第一步：准备环境和数据库

```powershell
python -m venv .venv
.venv\Scripts\Activate.ps1
pip install -r requirements.txt
```

如果没有 `requirements.txt`，至少需要 `pandas`、`numpy`、`requests`、`akshare`、`python-dateutil`、`pytz` 和 `matplotlib`。

### 第二步：建立方案 B 基金池

按 [EQUITY_UNIVERSE_GUIDE.md](../scripts/EQUITY_UNIVERSE_GUIDE.md) 依次执行：

1. `build_equity_universe.py --stage prepare` 生成 100 只候选基金和审计表；
2. `fetch_universe_nav.py` 把候选基金历史净值补入 SQLite；
3. `build_equity_universe.py --stage finalize` 按历史长度、覆盖率和异常零收益比例筛选最终 50 只。

当前仓库实际使用的方案 B 文件是：

```text
data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv
```

### 第三步：运行滚动回测

研究时建议显式写出所有参数，避免不同实验之间产生隐式配置差异：

```powershell
.venv\Scripts\python.exe run_rolling_backtest.py `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --rebalance month `
  --cost-bps 10 `
  --top-n 10 `
  --weight-scheme weight_equal `
  --max-weight 1.0
```

通过环境变量指定方案 B 基金池和独立输出目录：

```powershell
$env:FUND_UNIVERSE_CSV = "data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv"
$env:FUND_UNIVERSE_LIMIT = "50"
$env:FUND_OUTPUT_DIR = "output/v2_equity_pool"
```

### 第四步：进行因子诊断

```powershell
.venv\Scripts\python.exe run_factor_diagnostics.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --rebalance month `
  --groups 5 `
  --output output/v2_factor_diagnostics
```

该入口生成因子分组收益文件。相关性文件由评分方案实验入口统一生成。

### 第五步：比较四套评分方案

```powershell
.venv\Scripts\python.exe run_score_scheme_experiments.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --output output/v2_factor_optimization
```

四套方案定义在 `src/backtest/score_schemes.py`，实验固定为 Top-10、等权、月度调仓和 10 bps，只改变评分权重。

### 第六步：做配置敏感性实验

```powershell
.venv\Scripts\python.exe run_sensitivity_experiments.py `
  --universe data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --cost-bps 10 `
  --output output/v2_sensitivity
```

该脚本比较 Top-5/Top-10、等权/混合/逆波动、月度/季度调仓和 40% 权重上限组合。

## 4. 关键代码职责

| 路径 | 职责 |
|---|---|
| `src/_config.py` | 路径、基金池、窗口、Top-N、权重和因子权重配置 |
| `src/data/fetcher.py` | 东方财富 F10 历史净值抓取，AKShare 兜底 |
| `src/data/repository.py` | SQLite 读写、净值转收益、等权基准 |
| `src/data/pool.py` | 运行时加载和清洗基金代码池 |
| `src/domain/factors.py` | 六个收益风险因子计算 |
| `src/domain/scoring.py` | 缩尾、MAD 标准化和加权评分 |
| `src/domain/optimizer.py` | Top-N、等权、逆波动和混合权重 |
| `src/domain/risk.py` | 数据不足、回撤和集中度风险提示 |
| `src/pipeline/daily.py` | 日常端到端分析流程 |
| `src/backtest/rolling.py` | 点时滚动回测 |
| `src/backtest/engine.py` | 重放数据库中已保存权重的历史回测 |
| `src/backtest/accounting.py` | 调仓生效、换手和交易成本核算 |
| `src/backtest/metrics.py` | 总收益、CAGR、波动率、Sharpe、最大回撤 |
| `src/backtest/factor_diagnostics.py` | 因子分组收益和调仓日相关性 |
| `src/backtest/score_schemes.py` | 四套评分实验配置 |

## 5. 输出目录说明

| 目录 | 内容 |
|---|---|
| `output/v2_equity_pool` | 方案 B 基准滚动回测 |
| `output/v2_sensitivity` | Top-N、权重、调仓频率敏感性实验 |
| `output/v2_factor_diagnostics` | 因子分组收益诊断 |
| `output/v2_factor_optimization` | 相关性、四套评分方案和分阶段汇总 |
| `output/v1_original_pool_mdd_fixed` | 原始基金池、修正 MDD 方向后的历史结果 |
| `output/v1_origingal_pool_mdd_nofixed` | 原始基金池、未修正 MDD 方向的历史结果 |
| `output/v1_pool_navline_newdata` | 原始基金池的日线回测输出 |

## 6. 当前研究结论

IR 与年化收益的高低组下一期收益差分别约为 0.487% 和 0.395%，但两者相关性约 0.972。`return_ir` 在完整区间净收益约 20.43%，略低于等权基准的 20.91%；前半段跑输、后半段跑赢，最大回撤约 -32.12%，年化换手约 2.99 倍。四套方案完整区间均未跑赢基准，应将其视为研究假设而非稳定策略。

完整分析见 [factor_optimization_report.md](factor_optimization_report.md)。

## 7. 数据口径和质量门槛

`fund_nav_daily` 同时保存 `nav`、`acc_nav` 和 `daily_return`。收益计算优先使用供应商日增长率，覆盖不足时使用累计净值，再不足才使用单位净值。旧数据库启动后会自动增加缺失列，不删除历史数据。

日常流程会对缺失基金、滞后净值、总回报字段覆盖率、异常单日收益和评分数量输出风险告警；退出码为 0 不代表没有数据风险。

## 8. 测试

```powershell
python -m unittest discover -v
```

当前测试覆盖回测会计、成本、权重上限、绩效指标、评分方向、评分方案和基金池分类。

## 9. 数据和研究边界

本项目使用基金日净值进行研究，不等同于真实成交记录。方案 B 基金池目前按完整样本期质量筛选，仍存在存活偏差；更严格的研究应使用点时动态基金池或独立样本外基金池。结果还可能受到净值缺失、暂停申购、滑点、申购赎回费和样本区间选择影响。任何策略结论都应同时查看基准、回撤、换手率、交易成本和分阶段表现。
