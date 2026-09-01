from __future__ import annotations
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict

from ._exceptions import ConfigError

PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _env_str(key: str, default: str) -> str:
    """
        读取环境变量，返回字符串类型
        :param key: 环境变量名字
        :param default: 环境变量不存在/为空时返回的默认值
        :return: 去除首尾空格后的字符串 / 默认值
    """


    v = os.getenv(key)
    return default if v is None or v.strip() == "" else v.strip()


def _env_int(key: str, default: int) -> int:
    """
        读取环境变量，转成整数类型
        :param key:环境变量名
        :param default:默认整数
        :return:int
    """
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    try:
        return int(v)
    except ValueError:
        raise ConfigError(f"ENV {key} must be an integer, got {v!r}")


def _env_float(key: str, default: float) -> float:
    """读取环境变量，转为浮点数"""
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    try:
        return float(v)
    except ValueError:
        raise ConfigError(f"ENV {key} must be a float, got {v!r}")


def _env_bool(key: str, default: bool) -> bool:
    """
        读取环境变量解析布尔值
        识别：1/true/yes/y/on → 返回True；其余全部返回False
    """
    v = os.getenv(key)
    if v is None or v.strip() == "":
        return default
    return v.strip().lower() in {"1", "true", "yes", "y", "on"}



_DEFAULT_FACTOR_WEIGHTS: Dict[str, float] = {
    "ann_return": 0.35, "ann_vol": -0.15, "down_vol": -0.10,

    "mdd": 0.10, "sharpe": 0.35, "ir": 0.15,
}



@dataclass
class Config:
    """
    项目全局配置类，使用 @dataclass 装饰器
    从环境变量读取配置，环境变量不存在则使用默认值
    统一管理文件路径、业务参数、运行参数、表名、因子权重
    """



    data_dir: Path = Path(_env_str("FUND_DATA_DIR", str(PROJECT_ROOT / "data")))

    db_path: Path = Path(_env_str("FUND_DB_PATH", str(PROJECT_ROOT / "db" / "fund_db.sqlite")))

    output_dir: Path = Path(_env_str("FUND_OUTPUT_DIR", str(PROJECT_ROOT / "output")))

    universe_csv: str = ""

    def __post_init__(self):
        """
        dataclass钩子函数：对象实例化完成后自动执行
        在__init__执行完毕之后才运行，可以访问实例自身属性
        """

        if not self.universe_csv:
            self.universe_csv = _env_str(
                "FUND_UNIVERSE_CSV", str(self.data_dir / "universe_v2_pool_seltype_main" / "universe_fund_v2_equity.csv")
            )



    universe_limit: int = _env_int("FUND_UNIVERSE_LIMIT", 50)

    top_n_funds: int = _env_int("FUND_TOP_N_FUNDS", 10)

    window_days: int = _env_int("FUND_WINDOW_DAYS", 252)

    since_date: str = _env_str("FUND_SINCE_DATE", "2022-01-01")

    min_history_days: int = _env_int("FUND_MIN_HISTORY_DAYS", 60)

    pure_sharpe_only: bool = _env_bool("FUND_PURE_SHARPE_ONLY", False)



    parallel_workers: int = _env_int("PARALLEL_WORKERS", 1)

    weight_scheme: str = _env_str("FUND_WEIGHT_SCHEME", "weight_equal")

    max_weight: float = _env_float("FUND_MAX_WEIGHT", 1.0)



    nav_table: str = _env_str("FUND_NAV_TABLE", "fund_nav_daily")

    portfolio_table: str = _env_str("FUND_PORTFOLIO_TABLE", "portfolio_results")


    """
    default_factory: 延迟生成字典，不能直接写{}，dataclass可变对象必须用field(default_factory=...)
    遍历默认权重 _DEFAULT_FACTOR_WEIGHTS
    对每一个因子k，读取环境变量 FW_{k}，没有就使用内置默认v
    例如 FW_sharpe 可以覆盖夏普比率权重
    """
    factor_weights: Dict[str, float] = field(default_factory=lambda: {
        k: _env_float(f"FW_{k}", v) for k, v in _DEFAULT_FACTOR_WEIGHTS.items()
    })

    def validate(self):
        """校验配置：检查目录，不存在就自动创建文件夹"""
        if self.universe_limit < 1:
            raise ConfigError("universe_limit must be positive")
        if self.top_n_funds < 1 or self.top_n_funds > self.universe_limit:
            raise ConfigError("top_n_funds must be between 1 and universe_limit")
        if self.window_days < 2:
            raise ConfigError("window_days must be at least 2")
        if self.min_history_days < 1:
            raise ConfigError("min_history_days must be positive")
        if self.parallel_workers < 1:
            raise ConfigError("parallel_workers must be positive")
        if not 0 < self.max_weight <= 1:
            raise ConfigError("max_weight must be in (0, 1]")

        if not self.db_path.parent.exists():
            self.db_path.parent.mkdir(parents=True, exist_ok=True)

        if not self.output_dir.exists():
            self.output_dir.mkdir(parents=True, exist_ok=True)

    def summary(self) -> str:
        """生成配置摘要字符串，用于打印日志，查看当前运行全部配置"""
        lines = [
            f"Config:",
            f"  db={self.db_path}",
            f"  output={self.output_dir}",
            f"  universe_limit={self.universe_limit}",
            f"  since={self.since_date}",
            f"  window={self.window_days}d",
            f"  top_n={self.top_n_funds}",
            f"  weight={self.weight_scheme}",
            f"  workers={self.parallel_workers}",
        ]

        return "\n".join(lines)
