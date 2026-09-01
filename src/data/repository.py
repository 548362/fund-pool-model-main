from __future__ import annotations


from pathlib import Path
from typing import Iterable, Sequence
import pandas as pd
import sqlite3

from .._config import Config
from ..common.utils import norm_code, log
from .connection import get_connection, ensure_table, list_tables, table_columns
import pandas as pd
from typing import Iterable



CODE_LIKE = {"fund_code", "code"}



FUND_COLS = ["fund_code", "code", "基金代码", "基金代码(6位)", "证券代码"]



DATE_COLS = ["date", "trade_date", "pricedate", "净值日期", "交易日期", "日期"]



NAV_COLS = ["nav", "单位净值", "净值", "unit_nav", "nav_unit", "单位净值(元)", "复权单位净值"]
ACC_NAV_COLS = ["acc_nav", "累计净值", "累计净值(元)", "adjusted_nav"]



PREFERRED_TABLES = ["fund_nav_daily", "fund_data_raw", "fund_nav_raw", "fund_nav", "fund_price"]




def _infer_sql_type(colname: str, s: pd.Series) -> str:
    """
        【内部私有函数】推断pandas列对应SQLite的数据类型
        :param colname: 数据表的列名字符串
        :param s: pandas的Series，就是DataFrame中的一整列数据
        :return: 返回SQLite字段类型：TEXT / INTEGER / REAL
    """


    if colname in CODE_LIKE:
        return "TEXT"
    if colname in {"nav", "acc_nav", "daily_return"}:
        return "REAL"

    if pd.api.types.is_integer_dtype(s):
        return "INTEGER"

    if pd.api.types.is_float_dtype(s):
        return "REAL"

    if pd.api.types.is_bool_dtype(s):
        return "INTEGER"

    return "TEXT"


def _chunk_iter(it: Iterable, n: int):
    """
    【内部生成器函数】将可迭代对象切分成大小为n的块，分批yield返回
    :param it: 任意可迭代对象（列表、迭代器、数据行等）
    :param n: 每一块最大元素数量，分块大小
    :yield: 每一个分块列表，一块最多n个元素；最后一块不足n也会返回剩余全部
    """

    buf = []

    for x in it:

        buf.append(x)

        if len(buf) >= n:

            yield buf

            buf = []

    if buf:

        yield buf



def _pick_first(cols: list[str], candidates: list[str]):
    """
    【内部工具函数】按优先级找第一个存在的元素
    :param cols: 真实已存在的列名列表（比如df.columns）
    :param candidates: 候选名称列表，顺序代表查找优先级，靠前优先匹配
    :return: 返回第一个在cols中存在的候选；全部都找不到返回None
    """

    for c in candidates:

        if c in cols:

            return c

    return None



def _detect_nav_source(conn: sqlite3.Connection) -> tuple[str, str, str, str]:
    """
    【自动探测净值数据表】
    在数据库里面自动寻找一张符合净值表条件的表
    返回：(表名, 基金代码列名, 日期列名, 净值列名)
    找不到满足条件的表就抛出运行时异常
    """

    from .connection import list_tables, table_columns


    tables = list_tables(conn)



    order = PREFERRED_TABLES + [t for t in tables if t not in PREFERRED_TABLES]


    for t in order:

        if t not in tables:
            continue


        cols = table_columns(conn, t)


        f = _pick_first(cols, FUND_COLS)
        d = _pick_first(cols, DATE_COLS)
        n = _pick_first(cols, NAV_COLS)


        if f and d and n:
            return t, f, d, n


    raise RuntimeError(f"No NAV table found; available: {tables}")

class Repository:
    """
    数据仓储类：封装数据库所有读写操作
    把配置、数据库连接、DataFrame入库逻辑统一封装在这里
    """

    def __init__(self, config: Config):
        """实例初始化，接收配置对象"""
        self.config = config

    def has_return_metadata(self, codes: Iterable[str] | None = None) -> bool:
        """Return whether at least 95% of NAV rows have a total-return field."""
        with self._connect() as conn:
            if self.config.nav_table not in list_tables(conn):
                return False
            cols = set(table_columns(conn, self.config.nav_table))
            fields = [c for c in ("acc_nav", "daily_return") if c in cols]
            if not fields:
                return False
            expr = " + ".join(f'CASE WHEN "{c}" IS NOT NULL THEN 1 ELSE 0 END' for c in fields)
            normalized = sorted({norm_code(code) for code in (codes or []) if norm_code(code)})
            where = ""
            params: list[str] = []
            if normalized:
                where = f" WHERE fund_code IN ({','.join('?' for _ in normalized)})"
                params = normalized
            row = conn.execute(
                f'SELECT COALESCE(SUM(CASE WHEN ({expr}) > 0 THEN 1 ELSE 0 END), 0), COUNT(*) '
                f'FROM "{self.config.nav_table}"{where}',
                params,
            ).fetchone()
            return bool(row and row[1] and row[0] >= row[1] * 0.95)

    def _connect(self):
        """私有方法：获取数据库连接，内部调用之前写好的 get_connection"""
        return get_connection(self.config.db_path)


    def upsert_df(self, table: str, df: pd.DataFrame, pk_cols: Sequence[str]) -> int:
        """
        将 pandas DataFrame 写入sqlite，执行 UPSERT：
        主键冲突 → 更新原有记录；主键不存在 → 新增记录
        :param table: 目标表名
        :param df: 需要写入的DataFrame
        :param pk_cols: 主键字段列表（联合主键）
        :return: int，本次处理行数，空数据返回0
        """

        if df is None or df.empty:
            return 0

        df = df.copy()


        for c in df.columns:
            if c in CODE_LIKE:
                df[c] = df[c].map(norm_code)

        cols = list(df.columns)
        pk = list(pk_cols)
        non_pk = [c for c in cols if c not in pk]


        with self._connect() as con:

            col_defs = {c: _infer_sql_type(c, df[c]) for c in cols}

            ensure_table(con, table, col_defs, pk)


            col_expr = ", ".join(f'"{c}"' for c in cols)

            placeholders = ", ".join(["?"] * len(cols))

            pk_expr = ", ".join(f'"{c}"' for c in pk)


            update_assign = ", ".join(f'"{c}"=excluded."{c}"' for c in non_pk) if non_pk else ""


            if non_pk:


                sql = f'INSERT INTO "{table}" ({col_expr}) VALUES ({placeholders}) ON CONFLICT({pk_expr}) DO UPDATE SET {update_assign}'
            else:

                sql = f'INSERT OR IGNORE INTO "{table}" ({col_expr}) VALUES ({placeholders})'



            fallback_sql = f'REPLACE INTO "{table}" ({col_expr}) VALUES ({placeholders})'


            def _rows():
                """
                内部生成器函数：遍历DataFrame，一行一行产出元组
                executemany 需要元组格式的数据，不能直接传pandas行对象
                yield 逐行输出，不会一次性把全部数据加载进内存
                """
                for i in range(len(df)):


                    yield tuple(df.iloc[i][cols].tolist())

            affected = 0

            try:
                before = con.total_changes

                for chunk in _chunk_iter(_rows(), n=800):

                    con.executemany(sql, chunk)

                affected = con.total_changes - before

            except sqlite3.OperationalError:
                """
                捕获操作异常：老版本SQLite不支持 ON CONFLICT DO UPDATE语法，会抛出这个错误
                触发后自动降级，使用fallback_sql也就是REPLACE INTO方案
                """
                before = con.total_changes
                for chunk in _chunk_iter(_rows(), n=800):

                    con.executemany(fallback_sql, chunk)
                affected = con.total_changes - before


            return int(affected)

    def upsert_nav(self, df_nav: pd.DataFrame) -> int:
        """
        业务方法：基金净值数据入库（增量更新upsert）
        :param df_nav: 基金净值DataFrame，必须包含 fund_code基金代码、date日期、nav单位净值
        :return int: 返回本次入库影响的行数（新增+更新）
        """

        need = {"fund_code", "date", "nav"}



        if not need.issubset(set(df_nav.columns)):

            raise ValueError(f"upsert_nav needs columns {need}, got {set(df_nav.columns)}")


        with self._connect() as con:
            if self.config.nav_table in list_tables(con):
                existing = set(table_columns(con, self.config.nav_table))
                for column in ("acc_nav", "daily_return"):
                    if column not in existing:
                        con.execute(f'ALTER TABLE "{self.config.nav_table}" ADD COLUMN "{column}" REAL')

        cols = ["fund_code", "date", "nav"]
        cols.extend(c for c in ("acc_nav", "daily_return") if c in df_nav.columns)

        return self.upsert_df(self.config.nav_table, df_nav[cols],
                              pk_cols=("fund_code", "date"))

    def upsert_portfolio(self, df_port: pd.DataFrame) -> int:
        """
        业务方法：投资组合持仓数据入库
        :param df_port: 组合持仓DataFrame，至少要有 date、fund_code
        :return int: 返回本次入库影响行数
        """

        if "date" not in df_port.columns or "fund_code" not in df_port.columns:
            raise ValueError("upsert_portfolio needs columns ['date','fund_code']")




        return self.upsert_df(self.config.portfolio_table, df_port, pk_cols=("date", "fund_code"))






    def load_nav(self, codes: list[str], since: str = "2018-01-01") -> pd.DataFrame:
        """
        从数据库读取基金净值，返回净值DataFrame
        :param codes: 基金代码列表，例如 ["000001","000002"]
        :param since: 起始日期，默认2018‑01‑01，只读取这个日期之后的数据
        :return: DataFrame，列：fund_code, date, nav
        """

        if not codes:

            return pd.DataFrame(columns=["fund_code", "date", "nav", "acc_nav", "daily_return"])


        codes = [str(c).strip() for c in codes]



        valid_codes = {norm_code(c) for c in codes}




        codes_intlike = {str(int(c)) for c in valid_codes if c.isdigit()}


        with self._connect() as conn:
            t, fcol, dcol, ncol = _detect_nav_source(conn)
            acol = _pick_first(table_columns(conn, t), ACC_NAV_COLS)
            acc_expr = f', "{acol}" AS acc_nav' if acol else ', NULL AS acc_nav'
            rcol = "daily_return" if "daily_return" in table_columns(conn, t) else None
            return_expr = f', "{rcol}" AS daily_return' if rcol else ', NULL AS daily_return'





            code_bag = list(valid_codes | codes_intlike | set(codes))


            placeholders = ",".join(["?"] * len(code_bag))




            df = pd.read_sql_query(

                f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav{acc_expr}{return_expr} '
                f'FROM "{t}" WHERE "{dcol}" >= ? AND "{fcol}" IN ({placeholders})',
                conn, params=[since] + code_bag,
            )

            if df.empty:
                log("[DB] IN query empty, trying full table scan...")

                df = pd.read_sql_query(
                    f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav{acc_expr}{return_expr} '
                    f'FROM "{t}" WHERE "{dcol}" >= ?',
                    conn, params=[since],
                )


            if df.empty:

                log("[DB] Still empty, shifting since back 365 days...")
                df = pd.read_sql_query(
                    f'SELECT "{fcol}" AS fund_code, "{dcol}" AS date, "{ncol}" AS nav{acc_expr}{return_expr} '
                    f'FROM "{t}" WHERE DATE("{dcol}") >= DATE(?, "-365 day")',
                    conn, params=[since],
                )

        if df.empty:
            log("[DB] No NAV data found.")
            return df



        df["fund_code"] = df["fund_code"].map(norm_code)

        df["date"] = pd.to_datetime(df["date"])
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
        df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce")

        df = (

            df[df["fund_code"].isin(valid_codes)]

            .drop_duplicates(subset=["fund_code", "date"])

            .sort_values(["fund_code", "date"])

            .reset_index(drop=True)
        )


        min_days = self.config.min_history_days

        lens = df.groupby("fund_code")["date"].nunique()

        keep = lens[lens >= min_days].index.tolist()


        if not keep:
            log(f"[DB] All funds have <{min_days} days, relaxing to 1 day.")

            keep = lens[lens >= 1].index.tolist()


        df = df[df["fund_code"].isin(keep)].reset_index(drop=True)


        log(f"[DB] NAV: funds={len(keep)}, rows={len(df)} since={since}")

        return df


    @staticmethod
    def to_returns(df_nav: pd.DataFrame) -> pd.DataFrame:
        """
        【静态方法】由净值数据计算每日收益率
        :param df_nav: 净值数据表，必须包含 fund_code, date, nav
        :return: DataFrame[fund_code, date, ret] ret代表当日收益率
        """

        if df_nav is None or df_nav.empty:
            return pd.DataFrame(columns=["fund_code", "date", "ret"])


        df = df_nav.sort_values(["fund_code", "date"]).copy()

        returns = []
        for _, group in df.groupby("fund_code", sort=False):
            provider = pd.to_numeric(group["daily_return"], errors="coerce")
            provider_coverage = provider.iloc[1:].notna().mean() if len(provider) > 1 else 0.0
            if provider_coverage >= 0.80:
                values = provider
            else:
                accumulated = pd.to_numeric(group["acc_nav"], errors="coerce")
                source = accumulated if accumulated.notna().mean() >= 0.95 else group["nav"]
                values = source.pct_change()
            values.index = group.index
            returns.append(values)
        df["ret"] = pd.concat(returns).sort_index()


        df = df.dropna(subset=["ret"])


        return df[["fund_code", "date", "ret"]].reset_index(drop=True)


    @staticmethod
    def make_equal_benchmark(df_ret: pd.DataFrame) -> pd.Series:
        """
        【静态方法】构建等权基准：每日取全部基金收益率的平均值，模拟等权组合基准
        :param df_ret: to_returns输出的收益率表 fund_code,date,ret
        :return: Series，index=date，值=当日等权基准收益率，name=bench_ret
        """

        if df_ret is None or df_ret.empty:
            return pd.Series(dtype=float, name="bench_ret")


        s = df_ret.groupby("date")["ret"].mean().rename("bench_ret")

        s.index = pd.to_datetime(s.index)
        return s


    def get_latest_nav_date(self) -> str | None:
        """
        实例方法：查询数据库净值表里最新的净值日期
        :return: 最新日期字符串；库文件不存在/无数据返回None
        """

        dbp = self.config.db_path

        if not dbp.exists():
            return None


        with self._connect() as conn:

            cur = conn.execute(f"SELECT MAX(date) FROM {self.config.nav_table}")

            row = cur.fetchone()

            return str(row[0]) if row and row[0] else None

    def get_latest_nav_dates(self, codes: Iterable[str]) -> dict[str, str]:
        """Return the latest stored NAV date for every requested fund."""
        normalized = sorted({norm_code(code) for code in codes if norm_code(code)})
        if not normalized or not self.config.db_path.exists():
            return {}
        placeholders = ",".join("?" for _ in normalized)
        with self._connect() as conn:
            if self.config.nav_table not in list_tables(conn):
                return {}
            rows = conn.execute(
                f'SELECT fund_code, MAX(date) FROM "{self.config.nav_table}" '
                f'WHERE fund_code IN ({placeholders}) GROUP BY fund_code',
                normalized,
            ).fetchall()
        return {norm_code(code): str(latest) for code, latest in rows if latest}
