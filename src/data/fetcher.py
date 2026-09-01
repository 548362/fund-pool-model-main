from __future__ import annotations
import os
import re
import time
import traceback
import threading
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import datetime, timedelta
from io import StringIO
from typing import Iterable, Optional

import pandas as pd
import requests

from .._config import Config
from ..common.utils import log, retry, norm_code
from .repository import Repository





HEADERS_BASE = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
}
CODE_RE = re.compile(r"^\d{6}$")
_PAT_PAGES = re.compile(r"pages\s*:\s*(\d+)", re.I)
_JS_LOCK = threading.Lock()


class Fetcher:
    """
        基金数据抓取器：封装东方财富基金净值接口的爬取、解析、清洗全流程
    """
    def __init__(self, config: Config, repo: Repository):
        """
        构造方法：初始化抓取器，绑定配置对象和数据库仓储对象
        :param config: 全局配置对象
        :param repo: Repository 仓储实例，抓完数据可直接调用入库
        """
        self.config = config
        self.repo = repo
        self.failures: list[str] = []


    def _fix_code(self, code: str) -> str:
        """
                【私有工具方法】清洗并标准化基金代码
                功能：去除非数字字符，不足6位左侧补0，格式校验，非法代码返回空字符串
                :param code: 原始基金代码（可能带字母、空格、前缀）
                :return: 标准化6位数字代码；格式非法返回空串
        """
        s = re.sub(r"\D", "", str(code)).zfill(6)
        return s if CODE_RE.match(s) else ""



    def _extract_table_html(self, text: str) -> str:
        """
                【私有工具方法】从接口返回的原始文本中，提取 <table> 标签包裹的HTML表格片段
                接口返回内容混杂了分页信息、JS代码，仅提取表格部分可提升 pandas 解析准确率
                :param text: 接口返回的原始HTML文本
                :return: 提取到的表格HTML字符串；未找到返回空串
        """

        m1 = re.search(r"<table[^>]*>", text, re.I | re.S)

        m2 = re.search(r"</table>", text, re.I | re.S)
        if not (m1 and m2):
            return ""
        return text[m1.start():m2.end()]




    def _fetch_f10_pages(self, code6: str, max_pages: int = 999) -> pd.DataFrame:
        """
                【核心抓取方法】调用东方财富F10接口，分页抓取单只基金的全部历史净值
                :param code6: 标准化后的6位基金代码
                :param max_pages: 最大抓取页数限制，防止接口异常导致死循环，默认999页
                :return: 标准化净值表，包含 date、nav、acc_nav 和 daily_return
        """

        url = "http://fundf10.eastmoney.com/F10DataApi.aspx"
        headers = {**HEADERS_BASE, "Referer": f"http://fundf10.eastmoney.com/jjjz_{code6}.html"}
        params = {"type": "lsjz", "code": code6, "page": 1, "per": 20}
        r = requests.get(url, params=params, headers=headers, timeout=15)
        r.raise_for_status()
        text = r.text
        m = _PAT_PAGES.search(text)
        pages = min(int(m.group(1)) if m else 1, max_pages)

        frames = []
        for p in range(1, pages + 1):
            params["page"] = p
            rp = requests.get(url, params=params, headers=headers, timeout=15)
            rp.raise_for_status()
            html = self._extract_table_html(rp.text)
            tables = pd.read_html(StringIO(html)) if html else pd.read_html(StringIO(rp.text))
            if not tables:
                break
            dfp = tables[0]


            ren = {}
            for c in dfp.columns:
                if "日期" in c: ren[c] = "date"
                elif "单位" in c: ren[c] = "nav"
                elif "累计" in c: ren[c] = "acc_nav"
                elif "增长率" in c: ren[c] = "daily_return"
            dfp = dfp.rename(columns=ren)

            keep = [c for c in ["date", "nav", "acc_nav", "daily_return"] if c in dfp.columns]
            if "date" not in keep or "nav" not in keep:
                continue


            dfp["date"] = pd.to_datetime(dfp["date"], errors="coerce")
            dfp["nav"] = pd.to_numeric(dfp["nav"], errors="coerce")
            if "acc_nav" in dfp.columns:
                dfp["acc_nav"] = pd.to_numeric(dfp["acc_nav"], errors="coerce")
            else:
                dfp["acc_nav"] = pd.NA
            if "daily_return" in dfp.columns:
                dfp["daily_return"] = pd.to_numeric(
                    dfp["daily_return"].astype(str).str.replace("%", "", regex=False), errors="coerce"
                ) / 100.0
            else:
                dfp["daily_return"] = pd.NA
            dfp = dfp.dropna(subset=["date", "nav"])
            if dfp.empty:
                continue

            frames.append(dfp[["date", "nav", "acc_nav", "daily_return"]])
            time.sleep(0.08)

        if not frames:
            return pd.DataFrame(columns=["date", "nav", "acc_nav", "daily_return"])


        df = pd.concat(frames, ignore_index=True)

        return df.drop_duplicates(subset=["date"]).sort_values("date")



    def _fetch_js(self, code6: str) -> pd.DataFrame:
        """
            【私有方法】通过AKShare接口获取单只基金净值数据，替代手写网页爬虫
            :param code6: 清洗完成的6位标准基金代码
            :return: 标准化df，列：date, nav, acc_nav
        """
        import akshare as ak



        with _JS_LOCK:
            dfu = ak.fund_open_fund_info_em(symbol=code6, indicator="单位净值走势")
            try:
                dfa = ak.fund_open_fund_info_em(symbol=code6, indicator="累计净值走势")
            except Exception:
                dfa = None

        try:
            if dfa is None:
                raise ValueError("cumulative NAV unavailable")

            growth_cols = ["净值日期", "单位净值"]
            if "日增长率" in dfu.columns:
                growth_cols.append("日增长率")
            df = pd.merge(dfu[growth_cols], dfa[["净值日期", "累计净值"]], on="净值日期", how="left")
        except Exception:

            df = dfu.rename(columns={"净值日期": "净值日期", "单位净值": "单位净值", "日增长率": "日增长率"})

        df = df.rename(columns={"净值日期": "date", "单位净值": "nav", "累计净值": "acc_nav", "日增长率": "daily_return"})
        if "acc_nav" not in df.columns:
            df["acc_nav"] = pd.NA
        if "daily_return" not in df.columns:
            df["daily_return"] = pd.NA
        df["date"] = pd.to_datetime(df["date"], errors="coerce")
        df["nav"] = pd.to_numeric(df["nav"], errors="coerce")
        df["acc_nav"] = pd.to_numeric(df["acc_nav"], errors="coerce")
        df["daily_return"] = pd.to_numeric(df["daily_return"], errors="coerce") / 100.0
        df = df.dropna(subset=["date", "nav"]).drop_duplicates(subset=["date"]).sort_values("date")
        return df[["date", "nav", "acc_nav", "daily_return"]]

    def fetch_one_fund_nav(self, code: str, since: str | None = None) -> pd.DataFrame:
        """
            【对外调用入口方法】获取一只基金完整净值，双数据源降级
            :param code: 原始输入基金代码（可能不干净）
            :param since: 可选，起始日期字符串，只抓取这个日期之后的数据，None代表取全部历史
                :return: DataFrame，列 fund_code, date, nav, acc_nav, daily_return
        """

        code6 = self._fix_code(code)
        if not code6:
            raise ValueError(f"Invalid fund code: {code}")
        try:

            raw = self._fetch_f10_pages(code6, max_pages=40)
            src = "f10"
        except Exception as e:

            log(f"[WARN] F10 failed for {code6}, fallback to JS: {e}")
            raw = self._fetch_js(code6)
            src = "js"

        df = raw.copy()
        if df.empty:
            return pd.DataFrame(columns=["fund_code", "date", "nav", "acc_nav", "daily_return"])
        if since:
            sd = pd.to_datetime(since)
            df = df[df["date"] >= sd]


        df.insert(0, "fund_code", code6)
        df["date"] = pd.to_datetime(df["date"]).dt.strftime("%Y-%m-%d")
        log(f"[FETCH] {code6} rows={len(df)} src={src}")

        time.sleep(0.1)

        if "daily_return" not in df.columns:
            df["daily_return"] = pd.NA
        return df[["fund_code", "date", "nav", "acc_nav", "daily_return"]].where(pd.notna(df), None)

    def fetch_and_save_batch(self, codes: Iterable[str], since: str | dict[str, str] | None = None, max_workers: int | None = None) -> int:
        """
                批量抓取多只基金净值并直接入库，使用多线程并发提升抓取速度
                :param codes: 基金代码可迭代对象，比如["005827","161725"]
                :param since: 起始日期，只抓取该日期之后的数据；None代表抓取全部历史
                :param max_workers: 线程池最大并发数，为None时读取配置文件的并行数
                :return: int，本次总共写入数据库的行数
        """

        codes = list(dict.fromkeys(codes))
        if not codes:
            return 0

        workers = max(1, int(max_workers or self.config.parallel_workers))
        self.failures = []

        since_label = "per-fund" if isinstance(since, dict) else (since or "-")
        log(f"[FETCH] Batch: {len(codes)} funds, {workers} workers, since={since_label}")


        write_rows = 0

        def task(code: str) -> int:
            """
                        【线程内部子任务】单个基金抓取+入库，给线程池调用
                        :param code: 单只原始基金代码
                        :return: 该基金成功入库多少行；失败返回0
            """
            try:
                code6 = self._fix_code(code)
                code_since = since.get(code6) if isinstance(since, dict) else since
                df = self.fetch_one_fund_nav(code, since=code_since)

                return self.repo.upsert_nav(df) if df is not None and not df.empty else 0
            except Exception as e:

                log(f"[ERR] {code} failed: {e}")
                self.failures.append(str(code))
                return 0


        with ThreadPoolExecutor(max_workers=workers, thread_name_prefix="fund-dl") as ex:

            futures = {ex.submit(task, c): c for c in codes}
            done = 0


            for fut in as_completed(futures):

                write_rows += int(fut.result() or 0)
                done += 1

                if done % 10 == 0 or done == len(codes):
                    log(f"[FETCH] {done}/{len(codes)} done, {write_rows} rows written")


        log(f"[FETCH] Complete: {write_rows} rows written")

        return write_rows

    def fetch_incremental(self, codes: Iterable[str], fallback_since: str, lookback_days: int = 5) -> int:
        """
                增量更新净值：只抓取数据库最新日期往前回溯lookback_days之后的数据，不用全量重抓全部历史
                业务：日常定时跑增量同步，减少接口请求量，提升速度
                :param codes: 需要更新的一批基金代码
                :param fallback_since: 兜底起始日期：数据库为空没有任何历史数据时，就从这个日期开始全量抓取
                :param lookback_days: 回溯天数，为了规避周末节假日、停牌数据缺失，多往前扒几天做覆盖，默认回溯5天
                :return: 返回增量更新总共写入数据库的行数
        """
        codes = list(dict.fromkeys(codes))
        latest_by_code = self.repo.get_latest_nav_dates(codes)
        since_by_code = {}
        for code in codes:
            code6 = self._fix_code(code)
            latest = latest_by_code.get(code6)
            since_by_code[code6] = (
                (datetime.strptime(latest, "%Y-%m-%d") - timedelta(days=lookback_days)).strftime("%Y-%m-%d")
                if latest else fallback_since
            )
        log(
            f"[FETCH] Incremental: funds={len(codes)}, "
            f"missing_history={len(codes) - len(latest_by_code)}, lookback={lookback_days}d"
        )
        return self.fetch_and_save_batch(codes, since=since_by_code)
