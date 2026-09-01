from __future__ import annotations
from pathlib import Path
from html import escape
import pandas as pd




def _metrics_from_returns(r: pd.Series) -> dict:
    """
    根据日收益率序列，计算回测四大核心指标：年化收益、年化波动率、夏普比率、最大回撤
    :param r: pd.Series 日收益率序列
    :return: dict 字典，存放四个指标；输入为空返回空字典
    """

    if r is None or r.empty:
        return {}


    r = r.dropna()


    ann = r.mean() * 252



    vol = r.std(ddof=0) * (252 ** 0.5)


    sharpe = ann / vol if vol and vol > 0 else float("nan")


    wealth = (1 + r).cumprod()



    dd = wealth / wealth.cummax() - 1


    mdd = dd.min() if len(dd) else float("nan")


    return {"ann_return": ann, "ann_vol": vol, "sharpe": sharpe, "mdd": mdd}


def generate_report(date_str: str, df_scores: pd.DataFrame, df_port: pd.DataFrame,
                    port_nav: pd.Series | None, out_dir: Path,
                    warnings: list[str] | None = None):
    """
    生成HTML格式的策略日报报告
    :param date_str: 报告运行日期字符串
    :param df_scores: 基金打分表DataFrame
    :param df_port: 组合权重DataFrame
    :param port_nav: 策略回测净值Series
    :param out_dir: 报告输出文件夹路径
    """

    out_dir.mkdir(parents=True, exist_ok=True)


    html = [f"<h2>Daily Report - {date_str}</h2>"]

    if warnings:
        html.append("<h3>Data and Risk Warnings</h3>")
        html.append("<ul>" + "".join(f"<li>{escape(str(item))}</li>" for item in warnings) + "</ul>")


    if df_scores is not None and not df_scores.empty:
        html.append("<h3>Top Scores</h3>")

        html.append(df_scores.head(10).to_html(index=False))


    if df_port is not None and not df_port.empty:
        html.append("<h3>Portfolio Weights</h3>")
        html.append(df_port.to_html(index=False))


    if port_nav is not None and not port_nav.empty:

        ret = port_nav.pct_change().dropna()

        m = _metrics_from_returns(ret)
        html.append("<h3>Backtest Snapshot</h3>")

        html.append(pd.DataFrame([m]).to_html(index=False))



    (out_dir / "report.html").write_text("\n".join(html), encoding="utf-8")
