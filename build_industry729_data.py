# -*- coding: utf-8 -*-
import json
import re
from datetime import datetime
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
STRATEGY = ROOT / "06_行业轮动" / "industry7.2.9_global_stoploss_partial_rebuild_4to2_cap1.0_momfilter_abs"
OUT = HERE / "industry729" / "data.js"


def clean(value):
    if isinstance(value, dict):
        return {str(k): clean(v) for k, v in value.items()}
    if isinstance(value, (list, tuple)):
        return [clean(v) for v in value]
    if isinstance(value, pd.Timestamp):
        return value.strftime("%Y-%m-%d")
    if isinstance(value, np.generic):
        value = value.item()
    if isinstance(value, float) and not np.isfinite(value):
        return None
    return value


def main():
    nav = pd.read_csv(STRATEGY / "output" / "nav_curve.csv", parse_dates=["date"])
    nav = nav.sort_values("date").reset_index(drop=True)
    nav["drawdown"] = nav["strategy_nav"] / nav["strategy_nav"].cummax() - 1
    with open(STRATEGY / "output" / "metrics.json", encoding="utf-8") as f:
        metrics_raw = json.load(f)
    m = metrics_raw["strategy"]
    slots = pd.read_csv(STRATEGY / "output" / "daily_slot_holdings.csv")
    latest_date = slots["date"].max()
    latest = slots[slots["date"] == latest_date].sort_values("slot")
    pool = pd.read_csv(ROOT / "05_基金池" / "ETF_my_pool_unique_66.csv", dtype={"code": str})
    names = dict(zip(pool["code"], pool["基金简称"]))
    names["511360"] = "海富通中证短融ETF"
    aggregated = {}
    slot_rows = []
    for _, row in latest.iterrows():
        positions = json.loads(row["positions"])
        for code, quantity in positions.items():
            aggregated[code] = aggregated.get(code, 0) + int(quantity)
        slot_rows.append({
            "slot": int(row["slot"]),
            "codes": row["codes"],
            "maturity_date": row["maturity_date"],
            "positions": positions,
        })
    holdings = [{"code": code, "name": names.get(code, code), "quantity": quantity}
                for code, quantity in sorted(aggregated.items(), key=lambda x: -x[1])]
    payload = {
        "meta": {
            "start": nav["date"].iloc[0], "end": nav["date"].iloc[-1], "days": len(nav),
            "holdings_date": latest_date,
            "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        },
        "metrics": {
            "total_return": m["累计收益"], "annual_return": m["年化收益(CAGR)"],
            "annual_vol": m["年化波动率"], "max_drawdown": m["最大回撤"],
            "sharpe": round(m["夏普比率"], 3), "calmar": round(m["Calmar比率"], 3),
        },
        "nav": nav[["date", "strategy_nav", "ew_benchmark_nav", "custom_benchmark_nav", "drawdown"]].values.tolist(),
        "annual": [[int(r["year"]), r["return"], r["volatility"]] for r in metrics_raw["annual_returns"]],
        "slots": slot_rows,
        "holdings": holdings,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    text = json.dumps(clean(payload), ensure_ascii=False, allow_nan=False, separators=(",", ":"))
    OUT.write_text("window.INDUSTRY729_DATA = " + text + ";\n", encoding="utf-8")
    html_path = OUT.parent / "index.html"
    html = html_path.read_text(encoding="utf-8")
    versioned = f'<script src="data.js?v={payload["meta"]["end"]}"></script>'
    html, count = re.subn(r'<script src="data\.js(?:\?v=[^"]*)?"></script>', versioned, html, count=1)
    if count != 1:
        raise RuntimeError("未能更新 industry729 数据版本号")
    html_path.write_text(html, encoding="utf-8")
    print(f"OK -> {OUT} ({OUT.stat().st_size / 1024:.0f} KB), {len(nav)} days, holdings={latest_date}")


if __name__ == "__main__":
    main()
