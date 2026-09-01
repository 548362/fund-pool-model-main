from __future__ import annotations
from pathlib import Path
from typing import List, Optional
import pandas as pd
import sqlite3

from .._config import Config
from ..common.utils import log, norm_code
from .connection import get_connection


class UniversePool:
    """
        基金标的池类：生成、维护一份待分析的基金候选池（基金代码列表）
        多源合并：本地csv缓存文件 → SQLite数据库 → AKShare线上接口
        自动做代码清洗、提取6位基金代码、去重，输出干净的基金code列表
    """
    def __init__(self, config: Config):
        """
        :param config: 全局配置对象，读取标的池上限、csv文件路径
        """
        self.config = config

    def _normalize_codes(self, obj) -> pd.DataFrame:
        """
                【私有方法】标准化处理杂乱输入，从任意格式输入中提取干净6位基金代码
                支持输入：None / pd.Series / pd.DataFrame
                :param obj: 可以是Series、DataFrame或者None，里面混杂基金代码
                :return: DataFrame，只有一列 fund_code，全部是标准6位基金代码，已去重
        """
        if obj is None:
            return pd.DataFrame(columns=["fund_code"])
        if isinstance(obj, pd.Series):
            s = obj.astype(str)
        elif isinstance(obj, pd.DataFrame):
            prefer = ["fund_code", "代码", "基金代码", "symbol", "code"]

            col = next((c for c in prefer if c in obj.columns), None)

            if col is None:
                for c in obj.columns:

                    if obj[c].astype(str).str.contains(r"\d{6}", regex=True).any():
                        col = c
                        break

            if col is None:
                col = obj.columns[0]
            s = obj[col].astype(str)
        else:
            return pd.DataFrame(columns=["fund_code"])

        s = s.str.extract(r"(\d{6})", expand=False).dropna().map(lambda x: x.zfill(6))
        return pd.DataFrame({"fund_code": s}).drop_duplicates().reset_index(drop=True)

    def load(self, limit: Optional[int] = None) -> List[str]:
        """
                对外入口：加载基金标的池，多源兜底，输出基金代码list
                数据源优先级：本地CSV缓存 → 本地SQLite数据库 → AKShare线上拉取
                :param limit: 最多返回多少只基金；None读取配置文件universe_limit
                :return: list[str] 标准6位基金代码列表
        """

        eff_limit = limit if limit is not None else self.config.universe_limit

        csv_path = Path(self.config.universe_csv)
        csv_path.parent.mkdir(parents=True, exist_ok=True)



        base = self._read_csv(csv_path)
        base_cnt = len(base)


        if base_cnt < eff_limit:
            db_df = self._read_db()
            if not db_df.empty:

                base = pd.concat([base, db_df], ignore_index=True).drop_duplicates()


        if len(base) < eff_limit:

            ak_df = self._read_akshare(eff_limit * 2)
            if not ak_df.empty:
                base = pd.concat([base, ak_df], ignore_index=True).drop_duplicates()


        base = self._normalize_codes(base)

        codes = base["fund_code"].head(eff_limit).tolist()


        pd.DataFrame({"fund_code": codes}).to_csv(csv_path, index=False, encoding="utf-8-sig")

        log(f"[POOL] candidates={base_cnt} -> returned={len(codes)} (limit={eff_limit})")

        return codes


    def _read_csv(self, path: Path) -> pd.DataFrame:
        """
                【私有方法】读取本地csv标的池缓存文件
                :param path: csv文件路径对象
                :return: 标准化之后的基金代码DataFrame；读取失败返回空df
        """
        try:
            if path.exists():

                raw_df = pd.read_csv(path, dtype=str)

                return self._normalize_codes(raw_df)
        except Exception as e:
            log(f"[WARN] CSV read failed: {e}")
        return pd.DataFrame(columns=["fund_code"])

    def _read_db(self) -> pd.DataFrame:
        """
                【私有方法】从本地SQLite数据库读取已经存过的基金代码
                作用：把之前已经抓取入库过的基金，补充进标的池
                :return: 标准化基金代码DataFrame
        """

        dbp = self.config.db_path
        if not dbp.exists():
            return pd.DataFrame(columns=["fund_code"])
        try:
            with get_connection(dbp) as conn:
                df = pd.read_sql(f"SELECT DISTINCT fund_code FROM {self.config.nav_table}", conn)
            return self._normalize_codes(df)
        except Exception as e:
            log(f"[INFO] DB read failed: {e}")
            return pd.DataFrame(columns=["fund_code"])

    def _read_akshare(self, max_rows: int) -> pd.DataFrame:
        """
                【私有方法】线上从akshare多个接口拉取基金列表，合并得到候选标的
                本地csv、数据库标的不够的时候才会调用
                :param max_rows: 最多返回多少行候选基金
                :return: 清洗后的基金代码DataFrame
        """
        try:
            import akshare as ak
            frames = []

            for fn in ("fund_name_em", "fund_etf_fund_daily_em", "fund_lof_fund_daily_em"):

                if hasattr(ak, fn):
                    try:

                        df = getattr(ak, fn)()

                        if isinstance(df, pd.DataFrame) and not df.empty:
                            frames.append(df)
                    except Exception:

                        pass

            if not frames:
                return pd.DataFrame(columns=["fund_code"])
            return self._normalize_codes(pd.concat(frames, ignore_index=True)).head(max_rows)
        except Exception:
            return pd.DataFrame(columns=["fund_code"])

    def load_from_csv(self, csv_path: Path, limit: int) -> List[str]:
        """
                【对外方法】用户自定义外部csv导入标的池
                可以自己准备一份csv文件，从外部文件读取基金代码，生成标的列表
                :param csv_path: 用户自定义csv文件路径
                :param limit: 最多取多少只基金
                :return: 基金代码字符串列表
        """
        df = pd.read_csv(csv_path)

        col = "fund_code" if "fund_code" in df.columns else df.columns[0]
        codes = df[col].astype(str).map(norm_code).dropna().tolist()
        return codes[:limit]
