from __future__ import annotations
import numpy as np
import pandas as pd
from typing import Dict, List

from .._config import Config


def _winsor(s: pd.Series, p: float | int = 0.01) -> pd.Series:
    """
    【内部私有函数】Winsorize 缩尾处理（截尾），处理异常极端值、离群点
    将小于p分位数的值强制等于p分位数，大于1‑p分位数强制等于1‑p分位数；默认1%缩尾
    :param s: 输入一维序列Series
    :param p: 缩尾比例，默认0.01代表上下各截掉1%
    :return: 缩尾处理之后新的Series
    """


    if s.notna().sum() < 5:
        return s


    lo, hi = s.quantile(p), s.quantile(1 - p)


    return s.clip(lower=lo, upper=hi)


def _z_mad(s: pd.Series) -> pd.Series:
    """
    【内部私有函数】MAD‑Z标准化（中位数绝对偏差标准化）
    相比普通Z‑score，对异常值鲁棒，金融因子预处理经常用；1.4826为MAD转标准差的系数
    :param s: 原始输入序列
    :return: 标准化之后序列，以中位数做中心
    """

    x = pd.to_numeric(s, errors="coerce")


    med = x.median()


    mad = (x - med).abs().median()


    if not np.isfinite(mad) or mad == 0:

        sd = x.std(ddof=0)

        return (x - x.mean()) / sd if (np.isfinite(sd) and sd != 0) else (x - x.mean())


    return (x - med) / (1.4826 * mad)


from typing import Dict, List
import pandas as pd
import numpy as np

def score_funds(df_fac: pd.DataFrame, factor_weights: Dict[str, float | int] = None, pure_sharpe_only: bool = False) -> pd.DataFrame:
    """
    基金打分函数：多因子加权打分，输出每只基金综合得分与排名
    :param df_fac: 输入因子指标表，就是compute_factors输出结果，每一行一只基金，字段ann_return、ann_vol、sharpe、mdd等
    :param factor_weights: 因子权重字典 key=因子名，value=权重；不传则使用代码内置默认权重
    :param pure_sharpe_only: 是否只使用夏普比率sharpe单一因子打分；True时忽略其他因子
    :return: 返回表 fund_code基金代码、score综合得分、rank排名，附带处理后的因子列
    """

    if factor_weights is None:
        factor_weights = {
            "ann_return": 0.35,
            "ann_vol": -0.15,
            "down_vol": -0.10,
            "mdd": 0.10,
            "sharpe": 0.35,
            "ir": 0.15,
        }


    if df_fac is None or df_fac.empty:
        return pd.DataFrame(columns=["fund_code", "score", "rank"])

    df = df_fac.copy()


    cols = [c for c in factor_weights.keys() if c in df.columns]


    if pure_sharpe_only and "sharpe" in df.columns:
        cols = ["sharpe"]


    if not cols:
        return pd.DataFrame(columns=["fund_code", "score", "rank"])

    use_cols: List[str] = []

    for c in cols:

        s = pd.to_numeric(df[c], errors="coerce")

        if s.notna().sum() <= 1 or s.nunique(dropna=True) <= 1:
            continue

        df[c] = _winsor(s)

        df[c] = _z_mad(df[c])

        use_cols.append(c)


    if not use_cols:
        return pd.DataFrame(columns=["fund_code", "score", "rank"])

    df["score"] = 0.0
    wsum = 0.0

    for c in use_cols:

        w = float(factor_weights.get(c, 0))
        if w == 0:
            continue

        df["score"] += w * df[c]

        wsum += abs(w)


    if wsum > 0:
        df["score"] /= wsum


    df = df.sort_values("score", ascending=False).reset_index(drop=True)

    df["rank"] = np.arange(start=1, stop=len(df) + 1)


    return df[["fund_code", "score", "rank"] + use_cols]
