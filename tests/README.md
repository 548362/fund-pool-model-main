# 测试说明

`tests/` 用于验证基金研究流程中的核心规则。测试使用 Python 标准库 `unittest`，不需要连接网络、SQLite 数据库或调用真实基金净值接口。

## 1. 测试文件

### `test_backtest.py`

验证回测会计和绩效指标：

- 权重上限 `cap_weights()` 是否重新分配超额权重，并保持权重和为 1；
- 换手率、完整交易名义金额和交易成本是否符合项目约定；
- 调仓权重是否从下一交易日开始生效；
- 交易成本是否在实际生效日从净收益中扣除；
- 调仓时未保留的基金是否被视为 0 权重，而不是继续持有；
- 总收益、最终净值和最大回撤的计算是否正确。

对应代码：

```text
src/backtest/accounting.py
src/backtest/metrics.py
```

### `test_scoring.py`

验证评分方向，重点检查最大回撤的业务含义：

- MDD 是负数；
- 越接近 0 的回撤应该得到越高的评分；
- 例如 `-0.10` 应优于 `-0.20`，而 `-0.20` 应优于 `-0.40`。

对应代码：

```text
src/domain/scoring.py
```

### `test_universe_builder.py`

验证方案 B 基金池构建中的分类规则：

- A、B、C 和无后缀基金份额识别；
- 标准化底层基金名称去除份额后缀；
- 股票型和偏股混合型类型允许进入候选池；
- 债券型基金被标记为 `TYPE_NOT_ALLOWED`。

对应代码：

```text
scripts/build_equity_universe.py
```

### `test_score_schemes.py`

验证因子优化实验的评分方案配置：

- 四套内置评分方案名称完整；
- 每套方案的权重配置可以通过校验；
- `return_ir` 只使用 `ann_return` 和 `ir`；
- 修正后的基线方案使用正的 MDD 权重。

对应代码：

```text
src/backtest/score_schemes.py
```

### `test_data_quality.py`

验证总回报收益优先级、严格交易日窗口，以及缺失/滞后净值告警。

## 2. 运行全部测试

在项目根目录执行：

```powershell
python -m unittest discover -v
```

也可以使用当前虚拟环境：

```powershell
.venv\Scripts\python.exe -m unittest discover -v
```

## 3. 运行单个测试文件

```powershell
python -m unittest tests.test_backtest -v
python -m unittest tests.test_scoring -v
python -m unittest tests.test_universe_builder -v
python -m unittest tests.test_score_schemes -v
```

## 4. 当前测试结果

当前测试集共包含 15 个测试用例，覆盖：

- 回测会计和交易成本；
- 调仓生效日期；
- 权重上限；
- 绩效指标；
- MDD 评分方向；
- 基金类型和份额识别；
- 评分方案配置。

## 5. 测试边界

当前测试主要是单元测试，不包含以下内容：

- 真实网络接口稳定性；
- AKShare 或东方财富返回数据的完整性；
- SQLite 中全部历史净值的质量；
- 50 只基金的完整滚动回测结果；
- 真实成交、滑点和申购赎回费。

因此，单元测试全部通过只能说明核心计算规则符合预期，不能单独证明基金策略具有稳定超额收益。完整实验仍需结合 `output/v2_factor_optimization/` 下的因子诊断、基准比较和分阶段回测结果。
