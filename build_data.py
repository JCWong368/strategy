# -*- coding: utf-8 -*-
"""
宏观配置4.0.7 网页展示数据生成脚本
读取策略回测结果 CSV + 近期 precompute JSON，生成 data.js（window.STRATEGY_DATA = {...}）。
用法: python build_data.py
"""
import json
import math
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]  # 选股回测代码根目录
# 4.0.7 策略目录（2026-08-07 起归档至 实盘运行策略/，13_宏观配置/ 下旧目录已冻结）
BASE = ROOT / "实盘运行策略" / "宏观配置4.0.7"
OUT = HERE / "macro407" / "data.js"

MODULES = ["w_a_stock", "w_hk", "w_commodity", "w_global", "w_cash", "w_alt_501025"]


def load_names() -> dict:
    names = {}
    for path, col in [
        (ROOT / "03_运行类" / "long_table_code_names.csv", "name"),
        (BASE / "data" / "ETF_my_pool_unique_66.csv", "基金简称"),
        (BASE / "data" / "hk" / "ETF精选池_跨境_香港.csv", "名称"),
    ]:
        if path.exists():
            df = pd.read_csv(path, dtype={"code": str}, encoding="utf-8-sig")
            for _, r in df.iterrows():
                code = str(r["code"]).strip().zfill(6)
                if code not in names and pd.notna(r[col]):
                    names[code] = str(r[col]).strip()
    return names


def main():
    names = load_names()

    # ---- 净值 & 模块权重 ----
    nav = pd.read_csv(BASE / "results" / "nav_curve.csv", encoding="utf-8-sig")
    nav["date"] = nav["date"].astype(str)
    nav = nav.sort_values("date").reset_index(drop=True)
    nav["dd"] = nav["combo_nav"] / nav["combo_nav"].cummax() - 1.0

    nav_series = [
        [r.date, round(r.combo_nav, 6), round(r.daily_return, 6), round(r.dd, 6)]
        for r in nav.itertuples()
    ]
    weight_series = [
        [r.date] + [round(getattr(r, m), 4) for m in MODULES]
        for r in nav.itertuples()
    ]

    # ---- 绩效指标 ----
    n = len(nav)
    years = n / 244
    total_ret = nav["combo_nav"].iloc[-1] - 1
    ann_ret = nav["combo_nav"].iloc[-1] ** (1 / years) - 1
    vol = nav["daily_return"].std() * math.sqrt(244)
    sharpe = (nav["daily_return"].mean() * 244) / vol if vol > 0 else 0
    maxdd = nav["dd"].min()
    win = (nav["daily_return"] > 0).mean()
    metrics = {
        "start": nav["date"].iloc[0],
        "end": nav["date"].iloc[-1],
        "days": n,
        "total_return": round(total_ret, 4),
        "annual_return": round(ann_ret, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(sharpe, 3),
        "max_drawdown": round(maxdd, 4),
        "calmar": round(ann_ret / abs(maxdd), 3) if maxdd < 0 else None,
        "win_rate": round(win, 4),
        "total_cost": round(nav["transaction_cost"].sum(), 0),
    }

    # ---- 基准指数（沪深300 + 中证500 等权，起点归一化为1）----
    benchmarks = {}
    idx_path = ROOT / "03_运行类" / "指数_prices_long.csv"
    if idx_path.exists():
        idx = pd.read_csv(idx_path, dtype={"code": str},
                          usecols=["code", "date", "close"], encoding="utf-8-sig")
        idx["code"] = idx["code"].str.strip()
        nav_dates = nav["date"].tolist()
        legs = []
        for code in ["000300", "000905"]:
            s = (idx[idx["code"] == code].drop_duplicates("date")
                 .set_index("date")["close"].sort_index())
            s = s.reindex(sorted(set(s.index) | set(nav_dates))).ffill().reindex(nav_dates)
            legs.append(s / s.dropna().iloc[0])
        ew = sum(legs) / len(legs)
        benchmarks["等权基准"] = [round(v, 6) if pd.notna(v) else None for v in ew]

    # ---- 每日持仓（含市值占比）----
    pos = pd.read_csv(BASE / "results" / "positions_history.csv",
                      dtype={"code": str}, encoding="utf-8-sig")
    pos["code"] = pos["code"].str.strip().str.zfill(6)
    pos["date"] = pos["date"].astype(str)
    # 价格查找表：持仓涉及的代码 × 策略交易日，前值填充
    px = pd.read_csv(ROOT / "03_运行类" / "etf_prices_long.csv", dtype={"code": str},
                     usecols=["code", "date", "close"], encoding="utf-8-sig")
    px["code"] = px["code"].str.strip().str.zfill(6)
    px["date"] = px["date"].astype(str)
    px = px[px["code"].isin(pos["code"].unique())]
    close_tab = px.drop_duplicates(["date", "code"]).pivot(index="date", columns="code", values="close")
    close_tab = close_tab.reindex(sorted(set(close_tab.index) | set(nav["date"]))).ffill()
    tv = nav.set_index("date")["total_value"]
    positions = {}
    for d, g in pos.groupby("date"):
        rows = []
        for r in g.itertuples():
            try:
                price = close_tab.at[d, r.code]
            except KeyError:
                price = None
            pct = round(r.qty * price / tv[d], 4) if pd.notna(price) and d in tv.index else None
            rows.append([r.code, int(r.qty), pct])
        positions[d] = rows

    # ---- 大盘 N20/N5 状态 ----
    st = pd.read_csv(BASE / "data" / "composite_n20n5_states.csv", encoding="utf-8-sig")
    market_state = {
        str(r.date): [r.combined, r.N20_state, r.N5_state, round(r.target_ratio, 4)]
        for r in st.itertuples()
    }

    # ---- 减仓记录 ----
    red = pd.read_csv(BASE / "results" / "reduction_records.csv", encoding="utf-8-sig")
    red = red[(red["sell_value"] > 0) | (red["blocked_value"] > 0)]
    reductions = [
        [str(r.date), round(r.reduction_ratio, 4), round(r.sell_value, 0), round(r.blocked_value, 0)]
        for r in red.itertuples()
    ]

    # ---- 近期完整信号（precompute JSON）----
    signals = {}
    for f in sorted((BASE / "results" / "precompute").glob("*_precompute.json")):
        d = f.name.split("_")[0]
        try:
            j = json.loads(f.read_text(encoding="utf-8"))
        except Exception:
            continue
        sig = j.get("signals", {})
        a = j.get("a_stock", {})
        entry = {
            "market_state": sig.get("market_state"),
            "t1_date": j.get("meta", {}).get("t1_date"),
            "weights_t": sig.get("weights_t"),
            "weights_t1": sig.get("weights_t1"),
            "a_stock_target_ratio": sig.get("a_stock_target_ratio"),
            "commodity_avg_coef": sig.get("commodity_avg_coef"),
            "global_avg_coef": sig.get("global_avg_coef"),
            "hk_rs_top2": sig.get("hk_rs_top2"),
            "a_stock_rs_top5": a.get("rs_top5"),
        }
        tx = a.get("transactions", {})
        entry["a_stock_transactions"] = {
            "sell": tx.get("sell", []),
            "buy": tx.get("buy", []),
        }
        # T+1 目标持仓（precompute_holdings.csv，自带 weight 列）
        hf = f.with_name(f.name.replace("_precompute.json", "_precompute_holdings.csv"))
        if hf.exists():
            hd = pd.read_csv(hf, dtype={"code": str}, encoding="utf-8-sig")
            hd["code"] = hd["code"].str.strip().str.zfill(6)
            entry["t1_holdings"] = [
                [r.code, int(r.qty), round(r.weight, 4)] for r in hd.itertuples()
            ]
        signals[d] = entry

    data = {
        "names": names,
        "metrics": metrics,
        "nav": nav_series,
        "weights": weight_series,
        "benchmarks": benchmarks,
        "positions": positions,
        "market_state": market_state,
        "reductions": reductions,
        "signals": signals,
    }
    OUT.write_text(
        "window.STRATEGY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";\n",
        encoding="utf-8",
    )
    print(f"OK -> {OUT}  ({OUT.stat().st_size/1024:.0f} KB)")
    print(f"净值 {len(nav_series)} 天 | 持仓日期 {len(positions)} | 状态 {len(market_state)} | 减仓 {len(reductions)} | 信号 {len(signals)}")


if __name__ == "__main__":
    main()
