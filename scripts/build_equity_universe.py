#!/usr/bin/env python3
"""Build an auditable equity-fund universe from a fund catalogue and local NAV data.

The script deliberately keeps metadata separate from the runtime universe CSV. The
existing backtest only needs ``fund_code``; this script produces that file plus an
audit table explaining every retained or excluded candidate.
"""

from __future__ import annotations

import argparse
import hashlib
import re
import sqlite3
from pathlib import Path
from typing import Iterable

import pandas as pd


ALLOWED_FUND_TYPES = ("股票型", "混合型-偏股", "偏股混合型", "混合型-事件驱动")
EXCLUDED_NAME_KEYWORDS = (
    "债券", "货币", "FOF", "基金中基金", "QDII", "海外", "ETF", "指数",
    "联接", "持有期", "定期开放", "短债", "中短债",
)
REASON_PRIORITY = {
    "NO_CODE": 1,
    "TYPE_NOT_ALLOWED": 2,
    "SPECIAL_PRODUCT": 3,
    "B_SHARE": 4,
    "DUPLICATE_SHARE": 5,
    "NO_NAV": 6,
    "HISTORY_TOO_SHORT": 7,
    "LOW_COVERAGE": 8,
    "SUSPICIOUS_ZERO_RETURN": 9,
    "UNKNOWN_SHARE_CLASS": 10,
}


def _pick_column(df: pd.DataFrame, names: Iterable[str]) -> str | None:
    normalized = {str(c).strip().lower(): c for c in df.columns}
    for name in names:
        if name.lower() in normalized:
            return normalized[name.lower()]
    for col in df.columns:
        text = str(col).lower()
        if any(name.lower() in text for name in names):
            return col
    return None


def normalize_catalog(raw: pd.DataFrame) -> pd.DataFrame:
    """Map common AKShare/English column names into a stable schema."""
    code_col = _pick_column(raw, ("fund_code", "基金代码", "代码", "code", "symbol"))
    name_col = _pick_column(raw, ("fund_name", "基金简称", "基金名称", "名称", "name"))
    type_col = _pick_column(raw, ("fund_type", "基金类型", "类型", "type"))
    company_col = _pick_column(raw, ("fund_company", "基金公司", "管理人", "company"))
    inception_col = _pick_column(raw, ("inception_date", "成立日期", "成立日", "date"))
    if code_col is None:
        raise ValueError("catalog does not contain a fund-code column")

    out = pd.DataFrame()
    out["fund_code"] = raw[code_col].astype(str).str.extract(r"(\d{6})", expand=False)
    out["fund_name"] = raw[name_col].astype(str) if name_col else ""
    out["fund_type"] = raw[type_col].astype(str) if type_col else ""
    out["fund_company"] = raw[company_col].astype(str) if company_col else ""
    out["inception_date"] = raw[inception_col].astype(str) if inception_col else ""
    out = out.dropna(subset=["fund_code"]).drop_duplicates("fund_code").reset_index(drop=True)
    return out


def fetch_catalog() -> pd.DataFrame:
    try:
        import akshare as ak
    except ImportError as exc:
        raise RuntimeError("AKShare is required when --catalog is not supplied") from exc
    if not hasattr(ak, "fund_name_em"):
        raise RuntimeError("installed AKShare has no fund_name_em interface")
    return normalize_catalog(ak.fund_name_em())


def classify_share(name: str) -> str:
    text = str(name).strip().upper()
    if "后端" in text:
        return "B"
    match = re.search(r"(?:\(|（)?\s*([ABC])\s*(?:\)|）)?$", text)
    return match.group(1) if match else "original"


def base_name(name: str) -> str:
    text = str(name).upper()
    text = re.sub(r"[（(]\s*后端\s*[）)]", "", text)
    text = re.sub(r"\s*[（(]?\s*[ABC]\s*[）)]?\s*$", "", text)
    text = re.sub(r"\s+", "", text)
    return text


def reason_for_type(row: pd.Series) -> str:
    type_text = str(row["fund_type"])
    name_text = str(row["fund_name"])
    is_equity = (
        ("股票型" in type_text and "指数" not in type_text)
        or any(k in type_text for k in ALLOWED_FUND_TYPES[1:])
    )
    if not is_equity:
        return "TYPE_NOT_ALLOWED"
    if any(k.upper() in name_text.upper() for k in EXCLUDED_NAME_KEYWORDS):
        return "SPECIAL_PRODUCT"
    return ""


def stable_order(code: str, seed: int) -> str:
    return hashlib.sha256(f"{seed}:{code}".encode("ascii")).hexdigest()


def enrich_basic_fields(catalog: pd.DataFrame, indices: pd.Index, enabled: bool) -> pd.DataFrame:
    """Best-effort enrichment for the small sampled set, not the whole market."""
    if not enabled or len(indices) == 0:
        return catalog
    try:
        import akshare as ak
    except ImportError:
        catalog.loc[indices, "metadata_warning"] = "AKSHARE_UNAVAILABLE"
        return catalog
    if not hasattr(ak, "fund_individual_basic_info_xq"):
        catalog.loc[indices, "metadata_warning"] = "BASIC_INFO_API_UNAVAILABLE"
        return catalog
    for idx in indices:
        code = catalog.at[idx, "fund_code"]
        try:
            raw = ak.fund_individual_basic_info_xq(symbol=code)
            info = dict(zip(raw["item"].astype(str), raw["value"].astype(str)))
            if info.get("基金名称"):
                catalog.at[idx, "fund_name"] = info["基金名称"]
            if info.get("基金类型"):
                catalog.at[idx, "fund_type"] = info["基金类型"]
            if info.get("基金公司"):
                catalog.at[idx, "fund_company"] = info["基金公司"]
            if info.get("成立时间"):
                catalog.at[idx, "inception_date"] = info["成立时间"]
        except Exception as exc:
            catalog.at[idx, "metadata_warning"] = f"BASIC_INFO_FAILED:{type(exc).__name__}"
    return catalog


def nav_quality(db_path: Path, codes: list[str], start: str, end: str,
                min_history: int, min_coverage: float,
                zero_return_threshold: float) -> pd.DataFrame:
    columns = ["fund_code", "data_start", "data_end", "data_coverage", "nav_days",
               "zero_return_ratio", "quality_reason"]
    if not codes or not db_path.exists():
        return pd.DataFrame(columns=columns)
    placeholders = ",".join("?" for _ in codes)
    with sqlite3.connect(db_path) as conn:
        nav = pd.read_sql_query(
            f"SELECT fund_code, date, nav FROM fund_nav_daily "
            f"WHERE fund_code IN ({placeholders}) AND date >= ? AND date <= ?",
            conn, params=[*codes, start, end],
        )
    if nav.empty:
        return pd.DataFrame({"fund_code": codes, "quality_reason": "NO_NAV"})
    nav["date"] = pd.to_datetime(nav["date"], errors="coerce")
    nav["nav"] = pd.to_numeric(nav["nav"], errors="coerce")
    nav = nav.dropna(subset=["fund_code", "date", "nav"]).drop_duplicates(["fund_code", "date"])
    reference_days = nav["date"].drop_duplicates()
    rows: list[dict] = []
    for code in codes:
        part = nav[nav["fund_code"].astype(str) == str(code)].sort_values("date")
        if part.empty:
            rows.append({"fund_code": code, "quality_reason": "NO_NAV"})
            continue
        returns = part["nav"].pct_change().dropna()
        zero_ratio = float((returns.abs() < 1e-12).mean()) if len(returns) else 1.0
        coverage = len(part["date"].unique()) / max(len(reference_days), 1)
        reason = ""
        if len(part) < min_history:
            reason = "HISTORY_TOO_SHORT"
        elif coverage < min_coverage:
            reason = "LOW_COVERAGE"
        elif zero_ratio >= zero_return_threshold:
            reason = "SUSPICIOUS_ZERO_RETURN"
        rows.append({
            "fund_code": code,
            "data_start": part["date"].min().date().isoformat(),
            "data_end": part["date"].max().date().isoformat(),
            "data_coverage": round(coverage, 6),
            "nav_days": int(len(part)),
            "zero_return_ratio": round(zero_ratio, 6),
            "quality_reason": reason,
        })
    return pd.DataFrame(rows, columns=columns)


def build(args: argparse.Namespace) -> tuple[pd.DataFrame, pd.DataFrame]:
    catalog = normalize_catalog(pd.read_csv(args.catalog, dtype=str)) if args.catalog else fetch_catalog()
    catalog["share_class"] = catalog["fund_name"].map(classify_share)
    catalog["base_fund_name"] = catalog["fund_name"].map(base_name)
    catalog["base_fund_code"] = ""
    catalog["status"] = "candidate"
    catalog["exclude_reason"] = catalog.apply(reason_for_type, axis=1)
    catalog["metadata_warning"] = ""

    catalog.loc[catalog["share_class"].eq("B") & catalog["exclude_reason"].eq(""), "exclude_reason"] = "B_SHARE"

    catalog["share_rank"] = catalog["share_class"].map({"A": 0, "original": 1, "C": 2, "B": 3}).fillna(9)
    for _, group in catalog[catalog["exclude_reason"].eq("")].groupby("base_fund_name"):
        if len(group) <= 1:
            catalog.loc[group.index, "base_fund_code"] = group.iloc[0]["fund_code"]
            continue
        keep_idx = group.sort_values(["share_rank", "fund_code"]).index[0]
        canonical_code = catalog.loc[keep_idx, "fund_code"]
        catalog.loc[group.index, "base_fund_code"] = canonical_code
        catalog.loc[group.index.difference([keep_idx]), "exclude_reason"] = "DUPLICATE_SHARE"

    eligible = catalog[catalog["exclude_reason"].eq("")].copy()
    eligible["sample_order"] = eligible["fund_code"].map(lambda code: stable_order(code, args.seed))
    eligible = eligible.sort_values("sample_order")
    candidate_limit = max(args.candidate_limit, args.limit)
    candidate_indices = eligible.head(candidate_limit).index
    overflow = eligible.index.difference(candidate_indices)
    catalog.loc[overflow, "exclude_reason"] = "CANDIDATE_LIMIT"
    catalog = enrich_basic_fields(catalog, candidate_indices, args.enrich_basic)
    catalog["inception_date"] = pd.to_datetime(catalog["inception_date"], errors="coerce").dt.date.astype("string")
    too_new = (
        catalog.index.isin(candidate_indices)
        & catalog["inception_date"].notna()
        & (pd.to_datetime(catalog["inception_date"]) > pd.Timestamp(args.start))
        & catalog["exclude_reason"].eq("")
    )
    catalog.loc[too_new, "exclude_reason"] = "INCEPTION_AFTER_BACKTEST_START"
    catalog.loc[
        catalog.index.isin(candidate_indices)
        & catalog["inception_date"].isna()
        & catalog["exclude_reason"].eq(""),
        "metadata_warning",
    ] = catalog.loc[
        catalog.index.isin(candidate_indices)
        & catalog["inception_date"].isna()
        & catalog["exclude_reason"].eq(""),
        "metadata_warning",
    ].fillna("INCEPTION_UNKNOWN")

    if args.stage == "finalize":
        candidate_codes = catalog.loc[candidate_indices, "fund_code"].tolist()
        quality = nav_quality(
            Path(args.db), candidate_codes, args.start, args.end, args.min_history,
            args.min_coverage, args.zero_return_threshold,
        )
        catalog = catalog.merge(quality, on="fund_code", how="left")
        selected = catalog["fund_code"].isin(candidate_codes) & catalog["exclude_reason"].eq("")
        catalog.loc[selected, "exclude_reason"] = catalog.loc[selected, "quality_reason"].fillna("NO_NAV")
    else:
        for col in ("data_start", "data_end", "data_coverage", "nav_days", "zero_return_ratio", "quality_reason"):
            catalog[col] = pd.NA

    catalog["status"] = catalog["exclude_reason"].eq("").map(
        {True: "candidate" if args.stage == "prepare" else "retained", False: "excluded"}
    )
    catalog["metadata_as_of"] = pd.Timestamp.now().date().isoformat()

    target_status = "candidate" if args.stage == "prepare" else "retained"
    keep = catalog[catalog["status"].eq(target_status)].copy()
    keep["sample_order"] = keep["fund_code"].map(lambda code: stable_order(code, args.seed))
    keep = keep.sort_values("sample_order").head(candidate_limit if args.stage == "prepare" else args.limit)
    if args.stage == "finalize" and len(keep) < len(catalog[catalog["status"].eq("retained")]):
        overflow = catalog.index[catalog["status"].eq("retained") & ~catalog.index.isin(keep.index)]
        catalog.loc[overflow, "status"] = "excluded"
        catalog.loc[overflow, "exclude_reason"] = "UNIVERSE_LIMIT"
    return catalog, keep


def main() -> None:
    parser = argparse.ArgumentParser(description="Build an auditable scheme-B equity fund pool")
    parser.add_argument("--catalog", help="CSV catalogue; omit to call AKShare fund_name_em")
    parser.add_argument("--stage", choices=("prepare", "finalize"), default="prepare")
    parser.add_argument("--db", default="db/fund_db.sqlite")
    parser.add_argument("--start", default="2022-01-01")
    parser.add_argument("--end", default=pd.Timestamp.now().date().isoformat())
    parser.add_argument("--min-history", type=int, default=252)
    parser.add_argument("--min-coverage", type=float, default=0.95)
    parser.add_argument("--zero-return-threshold", type=float, default=0.995)
    parser.add_argument("--limit", type=int, default=50)
    parser.add_argument("--candidate-limit", type=int, default=100,
                        help="NAV prefetch candidates retained by the prepare stage")
    parser.add_argument("--seed", type=int, default=20260821,
                        help="fixed seed for reproducible candidate sampling")
    parser.add_argument("--enrich-basic", action="store_true",
                        help="fetch company and inception date for sampled candidates")
    parser.add_argument("--out-dir", default="data/universe_v2_pool_seltype_main")
    args = parser.parse_args()

    out_dir = Path(args.out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    audit, keep = build(args)
    audit_columns = ["fund_code", "fund_name", "fund_type", "base_fund_code", "share_class",
                     "fund_company", "inception_date", "data_start", "data_end",
                     "data_coverage", "nav_days", "zero_return_ratio", "metadata_warning",
                     "status", "exclude_reason",
                     "metadata_as_of"]
    audit.reindex(columns=audit_columns).to_csv(out_dir / "fund_pool_audit.csv", index=False, encoding="utf-8-sig")
    pool_name = "universe_fund_candidates.csv" if args.stage == "prepare" else "universe_fund_v2_equity.csv"
    keep[["fund_code"]].to_csv(out_dir / pool_name, index=False, encoding="utf-8-sig")
    if args.stage == "finalize":
        display_columns = [
            "fund_code", "fund_name", "fund_type", "base_fund_code", "share_class",
            "fund_company", "inception_date", "data_start", "data_end", "data_coverage",
            "nav_days", "zero_return_ratio",
        ]
        keep.reindex(columns=display_columns).sort_values("fund_code").to_csv(
            out_dir / "fund_pool_final_metadata.csv", index=False, encoding="utf-8-sig"
        )
    review_reasons = {"UNKNOWN_SHARE_CLASS", "METADATA_MISSING", "NAME_COLLISION"}
    review_mask = audit["exclude_reason"].isin(review_reasons) | audit["metadata_warning"].fillna("").ne("")
    audit[review_mask].reindex(columns=audit_columns).to_csv(
        out_dir / "fund_pool_review.csv", index=False, encoding="utf-8-sig"
    )
    summary = audit["exclude_reason"].replace("", "RETAINED").value_counts().rename_axis("reason").reset_index(name="count")
    summary.to_csv(out_dir / "fund_pool_summary.csv", index=False, encoding="utf-8-sig")
    print(f"stage={args.stage} catalogue={len(audit)} output={len(keep)}")
    print(summary.to_string(index=False))


if __name__ == "__main__":
    main()
