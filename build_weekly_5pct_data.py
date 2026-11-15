# -*- coding: utf-8 -*-
"""5%风险预算周度调仓网页数据生成。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd
import yaml

from build_unleveraged_5pct_data import load_names

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "实盘运行策略" / "5%风险预算周度调仓"
OUT = HERE / "5%风险预算周度调仓" / "data.js"
SLEEVES = ["a", "hk", "gl", "cmd", "bond"]


def scalar(value):
    if isinstance(value, pd.Timestamp):
        return str(value.date())
    if isinstance(value, np.generic):
        value = value.item()
    if pd.isna(value):
        return None
    return value


def records(frame: pd.DataFrame) -> list[dict]:
    return [{key: scalar(value) for key, value in row.items()}
            for row in frame.to_dict(orient="records")]


def json_safe(value):
    if isinstance(value, dict):
        return {key: json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [json_safe(item) for item in value]
    if isinstance(value, (float, np.floating)) and not np.isfinite(value):
        return None
    return value


def build_signals() -> dict:
    signals = {}
    for path in sorted((BASE / "results" / "precompute").glob("*_precompute.json")):
        try:
            pre = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        pre["t1_holdings"] = []
        holdings_path = path.with_name(path.name.replace(
            "_precompute.json", "_precompute_holdings.csv"))
        if pre["meta"]["action"] == "REBALANCE" and holdings_path.exists():
            holdings = pd.read_csv(holdings_path, dtype={"code": str}, encoding="utf-8-sig")
            holdings["code"] = holdings.code.str.strip().str.zfill(6)
            pre["t1_holdings"] = [
                [r.code, r.sleeve, round(float(r.weight), 6), getattr(r, "name", "")]
                for r in holdings.itertuples()
            ]
        signals[pre["meta"]["t_date"]] = pre
    return signals


def main() -> None:
    nav = pd.read_csv(BASE / "output" / "nav_daily.csv", parse_dates=["date"])
    perf = pd.read_csv(BASE / "output" / "performance_compare.csv")
    targets = pd.read_csv(BASE / "output" / "weekly_targets.csv", parse_dates=[
        "date", "signal_date", "scheduled_monday"])
    rebalance_summary = pd.read_csv(BASE / "output" / "rebalance_summary.csv")
    holdings_daily = pd.read_csv(
        BASE / "output" / "etf_holdings_daily.csv", dtype={"code": str}, parse_dates=["date"])
    cfg = yaml.safe_load((BASE / "config.yaml").read_text(encoding="utf-8"))
    names = load_names()
    for group in ["a", "hk"]:
        for info in cfg["instruments"][group].values():
            names[info["etf_code"]] = info["etf_name"]
    for row in holdings_daily.itertuples(index=False):
        names[row.code] = row.name

    metrics = records(perf.loc[(perf.segment == "全窗口") & (perf.strategy_key == "weekly")])[0]
    daily = []
    nav_rows = []
    comparisons = {"index_weekly": [], "original_target": []}
    comparison_peaks = {"index_weekly": 1.0, "original_target": 1.0}
    for row in nav.itertuples(index=False):
        date = str(row.date.date())
        nav_rows.append([date, round(float(row.nav), 6), round(float(row.ret), 8),
                         round(float(row.drawdown), 6)])
        daily.append([
            date,
            *[round(float(getattr(row, f"target_pos_{s}")), 6) for s in SLEEVES],
            *[round(float(getattr(row, f"pos_{s}")), 6) for s in SLEEVES],
            round(float(row.cash), 6), round(float(row.total_exposure), 6),
            round(float(row.k_exec), 6),
            round(float(row.native_sigma_risky), 6) if pd.notna(row.native_sigma_risky) else None,
            bool(row.is_rebalance),
        ])
        for key in comparisons:
            comparison_nav = float(getattr(row, f"{key}_nav"))
            comparison_peaks[key] = max(comparison_peaks[key], comparison_nav)
            comparisons[key].append([
                date, round(comparison_nav, 6),
                round(comparison_nav / comparison_peaks[key] - 1.0, 6),
            ])

    holdings = {}
    for date, group in holdings_daily.groupby("date"):
        holdings[str(date.date())] = [[
            r.code, r.sleeve, r.name, round(float(r.target_weight), 8),
            round(float(r.actual_weight), 8),
        ] for r in group.itertuples(index=False)]

    data = {
        "names": names,
        "metrics": metrics,
        "nav": nav_rows,
        "comparisons": comparisons,
        "daily": daily,
        "rebalances": records(targets),
        "rebalance_summary": records(rebalance_summary)[0],
        "performance": records(perf),
        "signals": build_signals(),
        "instruments": cfg["instruments"],
        "holdings": holdings,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    js = "window.STRATEGY_DATA = " + json.dumps(
        json_safe(data), ensure_ascii=False, separators=(",", ":"), allow_nan=False) + ";"
    OUT.write_text(js, encoding="utf-8")
    print(f"写出 {OUT}，{len(js)}字节，{len(nav_rows)}个交易日，"
          f"{len(targets)}次周度目标，precompute {len(data['signals'])}份")


if __name__ == "__main__":
    main()
