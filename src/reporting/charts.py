from __future__ import annotations
from pathlib import Path
import pandas as pd
import matplotlib.pyplot as plt


def plot_equity(nav: pd.Series, out_png: Path):
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(9, 4))
    nav.plot()
    plt.title("Portfolio NAV")
    plt.xlabel("Date")
    plt.ylabel("NAV")
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()


def plot_equity_comparison(curves: pd.DataFrame, out_png: Path):
    """Plot strategy gross/net wealth and benchmark wealth on one chart."""
    out_png.parent.mkdir(parents=True, exist_ok=True)
    plt.figure(figsize=(10, 5))
    labels = {
        "gross_equity": "Strategy gross",
        "net_equity": "Strategy net",
        "benchmark_equity": "Equal-weight benchmark",
    }
    for column, label in labels.items():
        if column in curves.columns:
            plt.plot(pd.to_datetime(curves["date"]), curves[column], label=label)
    plt.title("Strategy vs Equal-weight Benchmark")
    plt.xlabel("Date")
    plt.ylabel("Wealth index")
    plt.grid(alpha=0.25)
    plt.legend()
    plt.tight_layout()
    plt.savefig(out_png)
    plt.close()
