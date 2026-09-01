from __future__ import annotations
import numpy as np
import pandas as pd
from math import sqrt
from .._config import Config


TRADING_DAYS = 252


_REQUIRED = ["fund_code", "ann_return", "ann_vol", "down_vol", "sharpe", "ir", "mdd"]


def _mdd_from_returns(r: pd.Series) -> float | int:
    """
    【内部私有函数】根据日收益率序列，计算最大回撤 MDD（Maximum DrawDown）
    :param r: pd.Series 单只基金的日收益率序列 ret
    :return: float 最大回撤，负数；空输入返回np.nan
    """

    if r is None or r.empty:
        return np.nan



    wealth = (1.0 + r.fillna(0)).cumprod()


    peak = wealth.cummax()



    dd = wealth / peak - 1.0


    return float(dd.min()) if len(dd) else np.nan


def compute_factors(
    df_ret: pd.DataFrame,
    bench: pd.Series | None = None,
    window: int = 126,
    min_observations: int | None = None,
):
    """
    计算基金风险收益指标：年化收益、年化波动率、下行波动率、夏普比率、信息比率IR、最大回撤MDD
    :param df_ret: 长表DataFrame，字段 fund_code, date, ret  【基金日收益率数据表】
    :param bench: 基准收益率序列(可选)，用于算IR信息比率；不传则为None
    :param window: 滚动窗口，默认126个交易日（半年），取最近window条数据做指标计算
    :return: 指标结果DataFrame，每一行对应一只基金，字段由 _REQUIRED 常量规定
    """

    if df_ret is None or df_ret.empty:
        return pd.DataFrame(columns=_REQUIRED)


    df = df_ret.copy()

    df["date"] = pd.to_datetime(df["date"])


    if bench is not None:
        b = bench.copy()
        b.index = pd.to_datetime(b.index)

        df = df.merge(b.rename("bench_ret"), left_on="date", right_index=True, how="left")
    else:

        df["bench_ret"] = np.nan


    df["excess"] = df["ret"] - df["bench_ret"]

    rows = []
    required_observations = int(min_observations if min_observations is not None else window)
    if required_observations < 2 or required_observations > window:
        raise ValueError("min_observations must be between 2 and window")


    for code, g in df.groupby("fund_code", sort=False):
        g = g.sort_values("date")


        if len(g) < required_observations:
            continue


        ww = g.tail(window)
        r = ww["ret"].astype(float)
        ex = ww["excess"].astype(float)

        mu = r.mean()
        sd = r.std(ddof=0)
        down = r[r < 0].std(ddof=0)


        sharpe = (mu / sd * np.sqrt(TRADING_DAYS)) if (sd and sd > 0) else np.nan

        ex_sd = ex.std(ddof=0)

        ir = (ex.mean() / ex_sd * np.sqrt(TRADING_DAYS)) if (ex_sd and ex_sd > 0) else np.nan


        rows.append({
            "fund_code": code,

            "ann_return": float(mu * TRADING_DAYS) if np.isfinite(mu) else np.nan,

            "ann_vol": float(sd * np.sqrt(TRADING_DAYS)) if np.isfinite(sd) else np.nan,

            "down_vol": float(down * np.sqrt(TRADING_DAYS)) if np.isfinite(down) else np.nan,
            "sharpe": float(sharpe) if np.isfinite(sharpe) else np.nan,
            "ir": float(ir) if np.isfinite(ir) else np.nan,

            "mdd": float(_mdd_from_returns(r)),
        })


    if not rows:
        return pd.DataFrame(columns=_REQUIRED)


    return pd.DataFrame(rows, columns=_REQUIRED)




def adapt_factor_columns(df: pd.DataFrame) -> pd.DataFrame:
    """
    指标列名适配转换函数
    作用：兼容不同数据源输出的指标列名，把长名字统一改成项目内部标准短名字
    例如："annual_return" → "ann_return"，保证后续代码统一读取字段
    :param df: 输入指标DataFrame，可能是别的接口输出，列名是长命名
    :return: 返回列名标准化之后的DataFrame
    """

    if df is None or df.empty:
        return df


    mapping = {
        "annual_return": "ann_return",
        "annual_vol": "ann_vol",
        "downside_vol": "down_vol",
        "max_drawdown": "mdd",
        "information_ratio": "ir",
    }


    out = df.copy()


    for old, new in mapping.items():

        if old in out.columns and new not in out.columns:

            out = out.rename(columns={old: new})


    return out
