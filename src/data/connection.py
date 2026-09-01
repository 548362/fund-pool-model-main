from __future__ import annotations
import sqlite3
from pathlib import Path
from contextlib import contextmanager


@contextmanager
def get_connection(db_path: Path):
    """
    上下文管理器：获取SQLite数据库连接，自动做优化配置，用完自动提交+关闭连接
    使用方式：with get_connection(db_path) as con: ...
    :param db_path: Path对象，数据库文件完整路径
    """

    db_path.parent.mkdir(parents=True, exist_ok=True)


    con = sqlite3.connect(str(db_path))


    con.execute("PRAGMA journal_mode=WAL;")
    con.execute("PRAGMA synchronous=NORMAL;")
    con.execute("PRAGMA temp_store=MEMORY;")

    try:

        yield con
    finally:

        con.commit()
        con.close()



def list_tables(conn: sqlite3.Connection) -> list[str]:
    """
    查询数据库里所有用户表的表名
    :param conn: 数据库连接对象
    :return: 全部表名组成的字符串列表，例如 ["fund_nav", "fund_basic"]
    """

    cur = conn.execute("SELECT name FROM sqlite_master WHERE type='table'")

    return [r[0] for r in cur.fetchall()]


def table_columns(conn: sqlite3.Connection, table: str) -> list[str]:
    """
    获取指定一张表的全部列名
    :param conn: 数据库连接对象
    :param table: 需要查询的表名字符串
    :return: 当前表所有列名组成的列表，例如 ["fund_code","date","nav"]
    """

    cur = conn.execute(f'PRAGMA table_info("{table}")')


    return [r[1] for r in cur.fetchall()]



def ensure_table(conn: sqlite3.Connection, table: str, col_defs: dict[str, str], pk_cols: list[str] = None):
    """
        确保数据表一定存在，不存在就新建表；已经存在则什么都不做
        :param conn: 数据库连接对象
        :param table: 要操作的表名字符串
        :param col_defs: 字典，key=列名，value=字段类型，例 {"fund_code":"TEXT","date":"TEXT","nav":"REAL"}
        :param pk_cols: 主键列名列表，支持联合主键，例 ["fund_code","date"]；空列表代表没有主键
    """

    cols = ', '.join(f'"{k}" {v}' for k, v in col_defs.items())


    if pk_cols:

        pk = ', '.join(f'"{c}"' for c in pk_cols)

        cols += f', PRIMARY KEY ({pk})'


    conn.execute(f'CREATE TABLE IF NOT EXISTS "{table}" ({cols})')
