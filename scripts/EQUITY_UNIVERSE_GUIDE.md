# 方案 B 权益基金池构建指南

方案 B 的目标是建立一个可审计、可复现、适合多因子选基回测的权益基金池。它与运行时的 `UniversePool` 不同：

- `scripts/build_equity_universe.py` 负责从基金名录筛选并记录排除原因；
- `scripts/fetch_universe_nav.py` 负责为候选基金补抓历史净值；
- `src/data/pool.py` 只负责运行时读取最终 CSV、清洗代码和限制数量。

整个流程不会修改 `src/backtest/engine.py`、`src/backtest/rolling.py` 或原始 v1 基金池。

## 1. 当前实际文件位置

本仓库当前方案 B 文件位于：

```text
data/universe_v2_pool_seltype_main/
├── universe_fund_candidates.csv       # prepare 阶段候选基金
├── universe_fund_v2_equity.csv       # finalize 阶段最终基金代码池
├── fund_pool_audit.csv                # 全量审计结果
├── fund_pool_review.csv               # 需要人工关注的异常项
├── fund_pool_summary.csv              # 排除原因统计
└── fund_pool_final_metadata.csv       # 最终保留基金的展示字段
```

早期文档中出现过 `data/universe_v2`，那是旧目录名。运行当前项目时应使用上面的 `universe_v2_pool_seltype_main` 路径；新脚本的默认输出路径也已经是该目录。

## 2. 筛选规则

### 2.1 类型筛选

代码允许的类型包括：

- `股票型`；
- `混合型-偏股`；
- `偏股混合型`；
- `混合型-事件驱动`。

名称或类型中出现以下关键词会被排除：

```text
债券、货币、FOF、基金中基金、QDII、海外、ETF、指数、联接、持有期、定期开放、短债、中短债
```

这一步不是按照近期收益率挑基金，而是先限定研究对象，避免把债券、FOF、海外产品和权益基金混在同一套因子逻辑中。

### 2.2 份额识别和去重

基金名称后缀识别为 `A`、`B`、`C` 或 `original`：

- 名称包含“后端”视为 B 份额；
- 末尾带 A/B/C 的按对应份额识别；
- 没有后缀的视为 original。

同一标准化底层名称只保留一个份额，优先级为：

```text
A > original > C > B
```

B 份额通常存在暂停申购或不可新建仓问题，因此会被排除；其余重复份额标记为 `DUPLICATE_SHARE`。这些规则只用于建立研究池，不会删除数据库里的历史净值。

### 2.3 候选抽样

候选池通过固定 `seed` 对代码做稳定哈希排序，再保留前 `candidate-limit` 只。这样不会因为当前收益高低而选择候选基金，也能在以后重复运行时得到相同候选顺序。

### 2.4 历史数据质量

finalize 阶段从 SQLite 的 `fund_nav_daily` 查询候选基金，计算：

- `data_start`：该基金在筛选区间内第一条净值日期；
- `data_end`：最后一条净值日期；
- `data_coverage`：该基金有效净值日期数 / 全部参考交易日数；
- `nav_days`：有效净值记录数；
- `zero_return_ratio`：日收益绝对值接近 0 的比例。

当前正式筛选参数为：

```text
min-history = 252
min-coverage = 0.95
zero-return-threshold = 0.995
```

注意：`zero-return-threshold=0.995` 是异常检查阈值，不是删除所有出现零收益的基金。只有零收益比例达到阈值才标记为 `SUSPICIOUS_ZERO_RETURN`。

## 3. 阶段一：生成候选池

如果使用 AKShare 全市场基金名录：

```powershell
.venv\Scripts\python.exe scripts\build_equity_universe.py `
  --stage prepare `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --candidate-limit 100 `
  --limit 50 `
  --enrich-basic `
  --out-dir data\universe_v2_pool_seltype_main
```

如果已经有本地基金名录，可以显式传入：

```powershell
.venv\Scripts\python.exe scripts\build_equity_universe.py `
  --catalog path\to\fund_catalog.csv `
  --stage prepare `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --candidate-limit 100 `
  --limit 50 `
  --out-dir data\universe_v2_pool_seltype_main
```

prepare 阶段输出：

- `universe_fund_candidates.csv`：需要补抓净值的候选代码；
- `fund_pool_audit.csv`：全量基金的类型、份额、状态和排除原因；
- `fund_pool_summary.csv`：每个排除原因的数量；
- `fund_pool_review.csv`：元数据缺失、份额未知等需要关注的记录。

常见 `exclude_reason`：

| 值 | 含义 |
|---|---|
| `TYPE_NOT_ALLOWED` | 基金类型不属于股票型或偏股混合型 |
| `SPECIAL_PRODUCT` | 名称包含债券、FOF、QDII、ETF 联接等特殊产品关键词 |
| `B_SHARE` | 后端收费 B 份额 |
| `DUPLICATE_SHARE` | 同一底层基金的重复份额 |
| `CANDIDATE_LIMIT` | 超出候选数量上限 |
| `INCEPTION_AFTER_BACKTEST_START` | 成立日晚于回测起始日 |

## 4. 阶段二：补抓候选基金历史净值

```powershell
.venv\Scripts\python.exe scripts\fetch_universe_nav.py `
  --universe data\universe_v2_pool_seltype_main\universe_fund_candidates.csv `
  --db db\fund_db.sqlite `
  --since 2022-01-01 `
  --workers 4
```

该脚本只做数据补抓和入库，不计算因子、不打分、不生成组合。抓取器优先使用东方财富 F10 分页接口，失败时回退到 AKShare；写入使用 `fund_code + date` 联合主键的 UPSERT，因此重复运行不会简单重复插入。

## 5. 阶段三：根据本地净值最终筛选

```powershell
.venv\Scripts\python.exe scripts\build_equity_universe.py `
  --stage finalize `
  --catalog data\universe_v2_pool_seltype_main\fund_pool_audit.csv `
  --db db\fund_db.sqlite `
  --start 2022-01-01 `
  --end 2026-08-19 `
  --min-history 252 `
  --min-coverage 0.95 `
  --zero-return-threshold 0.995 `
  --limit 50 `
  --out-dir data\universe_v2_pool_seltype_main
```

finalize 阶段会重新写出：

- `universe_fund_v2_equity.csv`：后续回测只需要的 `fund_code` 列；
- `fund_pool_final_metadata.csv`：最终保留基金的展示字段；
- 更新后的 `fund_pool_audit.csv`、`fund_pool_review.csv` 和 `fund_pool_summary.csv`。

最终展示表字段为：

```text
fund_code
fund_name
fund_type
base_fund_code
share_class
fund_company
inception_date
data_start
data_end
data_coverage
nav_days
zero_return_ratio
```

审计表可以包含更多管理字段，例如 `metadata_warning`、`status`、`exclude_reason` 和 `metadata_as_of`。这些字段用于追溯，不建议为了美观删除审计表中的字段；展示时使用 `fund_pool_final_metadata.csv`。

## 6. 使用最终基金池

### 滚动回测

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

### 日常分析

如果要让日常流程使用方案 B，也必须显式设置：

```powershell
$env:FUND_UNIVERSE_CSV = "data/universe_v2_pool_seltype_main/universe_fund_v2_equity.csv"
$env:FUND_UNIVERSE_LIMIT = "50"
$env:FUND_TOP_N_FUNDS = "10"
$env:FUND_WEIGHT_SCHEME = "weight_equal"
$env:FUND_OUTPUT_DIR = "output/daily_v2"
.venv\Scripts\python.exe run_daily_fund.py
```

## 7. 人工维护基金池时的建议

不建议直接凭印象删除或新增基金后，把结果与自动筛选结果混在一起。若要做人工研究池：

1. 复制 `universe_fund_v2_equity.csv`；
2. 只保留一列 `fund_code`，保存为新的 CSV；
3. 使用 `FUND_UNIVERSE_CSV` 指向新文件；
4. 使用新的 `FUND_OUTPUT_DIR` 保存结果；
5. 在报告中记录新增、删除、原因和运行日期。

这样可以保留正式方案 B 作为基准，也能清楚区分人工池带来的影响。
