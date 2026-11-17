# -*- coding: utf-8 -*-
"""风险平价2.8网页数据：生产回测、历史持仓与precompute。"""
from __future__ import annotations

import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

from build_rp2_data import load_names, build_a_environment, build_beta_z, build_hk_timing
from build_rp2_reference_benchmarks import build_reference_benchmarks
from build_rp28_panels import build_commodity_dual, build_execution_status, build_standalone

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / "实盘运行策略" / "风险平价2.8_商品双择时"
OUT = HERE / "风险平价2.8_商品双择时" / "data.js"
SLEEVES = ["a", "hk", "gl", "cmd"]
CMD_CODES = ["159980", "159985", "159981", "518880", "513350"]
GL_ETF_INNER = {"513500": 0.5, "513030": 0.15, "513080": 0.15, "513880": 0.2}


def build_positions(nav: pd.DataFrame, close_tab: pd.DataFrame) -> tuple[dict, float]:
    a_pos = pd.read_csv(ROOT / "择时改进探索" / "08_九格系数替代四态_A股子策略"
                        / "output" / "positions_history.csv", dtype={"code": str}, encoding="utf-8-sig")
    a_pos["code"] = a_pos.code.str.strip().str.zfill(6)
    a_pos["date"] = a_pos.date.astype(str)
    hk_pos = pd.read_csv(ROOT / "16_港股通" / "港股通轮动1.0" / "output"
                         / "daily_slot_holdings.csv", encoding="utf-8-sig")
    hk_pos["date"] = pd.to_datetime(hk_pos.date).dt.strftime("%Y-%m-%d")
    cmd = pd.read_csv(ROOT / "09_商品" / "商品风险平价双择时1.0" / "output"
                      / "primary_daily.csv", parse_dates=["date"])
    cmd["date"] = cmd.date.dt.strftime("%Y-%m-%d")
    cmd_by_date = {d: row for d, row in cmd.set_index("date").iterrows()}
    a_by_date = {d: group for d, group in a_pos.groupby("date")}
    hk_by_date = {d: group for d, group in hk_pos.groupby("date")}
    positions = {}
    max_dev = 0.0
    for row in nav.itertuples(index=False):
        d = str(row.date)[:10]
        weights = {}

        def add(code, value):
            if value > 1e-12:
                weights[code] = weights.get(code, 0.0) + float(value)

        if row.pos_a > 0 and d in a_by_date:
            values = []
            for item in a_by_date[d].itertuples():
                try:
                    price = close_tab.at[d, item.code]
                except KeyError:
                    price = np.nan
                values.append((item.code, item.qty * price))
            total = sum(value for _, value in values if pd.notna(value))
            if total > 0:
                for code, value in values:
                    if pd.notna(value) and value > 0:
                        add(code, row.pos_a * value / total)
        if row.pos_hk > 0 and d in hk_by_date:
            quantities = {}
            for item in hk_by_date[d].itertuples():
                for code, qty in ast.literal_eval(item.positions).items():
                    quantities[code] = quantities.get(code, 0.0) + float(qty)
            values = []
            for code, qty in quantities.items():
                try:
                    price = close_tab.at[d, code]
                except KeyError:
                    price = np.nan
                values.append((code, qty * price))
            total = sum(value for _, value in values if pd.notna(value))
            if total > 0:
                for code, value in values:
                    if pd.notna(value) and value > 0:
                        add(code, row.pos_hk * value / total)
        for code, inner in GL_ETF_INNER.items():
            add(code, row.pos_gl * inner)
        if row.pos_cmd > 0 and d in cmd_by_date:
            native = cmd_by_date[d]
            targets = {code: float(native[f"target_{code}"]) if pd.notna(native[f"target_{code}"]) else 0.0
                       for code in CMD_CODES}
            target_sum = sum(targets.values())
            if target_sum > 0:
                for code, value in targets.items():
                    add(code, row.pos_cmd * value / target_sum)
        add("511130", row.bond_pos)
        rows = [[code, 0, round(value, 6)]
                for code, value in sorted(weights.items(), key=lambda item: -item[1])]
        positions[d] = rows
        total = row.pos_a + row.pos_hk + row.pos_gl + row.pos_cmd + row.bond_pos
        max_dev = max(max_dev, abs(sum(weights.values()) - total))
    return positions, max_dev


def build_signals() -> dict:
    signals = {}
    for path in sorted((BASE / "results" / "precompute").glob("*_precompute.json")):
        try:
            pre = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        entry = {
            "t1_date": pre["meta"]["t1_date"],
            "weights_t1": {"w_a_stock": pre["pos"]["a"], "w_hk": pre["pos"]["hk"],
                           "w_global": pre["pos"]["gl"], "w_commodity": pre["pos"]["cmd"],
                           "w_bond": pre["bond_pos"], "w_cash": pre["cash"]},
            "rp_info": {"base_weights": pre["base_weights"], "p": pre["p"],
                        "borrow": pre["borrow"], "pool": pre["pool"],
                        "bond_code": pre["bond_code"], "bond_pos": pre["bond_pos"],
                        "base_weights_asof": pre["meta"]["base_weights_asof"]},
            "commodity": pre["commodity"],
            "freshness": pre["freshness"],
            "t1_holdings": [],
        }
        holdings_path = path.with_name(path.name.replace("_precompute.json", "_precompute_holdings.csv"))
        if holdings_path.exists():
            holdings = pd.read_csv(holdings_path, dtype={"code": str}, encoding="utf-8-sig")
            holdings["code"] = holdings.code.str.strip().str.zfill(6)
            entry["t1_holdings"] = [[r.code, 0, round(float(r.weight), 6)]
                                    for r in holdings.itertuples()]
        signals[pre["meta"]["t_date"]] = entry
    return signals


def main() -> None:
    nav = pd.read_csv(BASE / "output" / "nav_daily.csv", parse_dates=["date"])
    perf = pd.read_csv(BASE / "output" / "performance_compare.csv")
    quarterly = pd.read_csv(BASE / "output" / "quarterly_target_weights.csv", parse_dates=["rebal_date"])
    px = pd.read_csv(ROOT / "03_运行类" / "etf_prices_long.csv", dtype={"code": str},
                     usecols=["code", "date", "close"], parse_dates=["date"])
    close_tab = px.pivot(index="date", columns="code", values="close")
    close_tab.index = close_tab.index.astype(str)
    positions, max_dev = build_positions(nav, close_tab)
    if max_dev > 1e-5:
        raise RuntimeError(f"历史持仓与四袖/国债合计偏差过大：{max_dev:.3e}")

    nav_rows, weight_rows = [], []
    rp_daily = {}
    for row in nav.itertuples(index=False):
        d = str(row.date.date())
        nav_rows.append([d, round(float(row.nav), 6), round(float(row.ret), 8),
                         round(float(row.drawdown), 6)])
        weight_rows.append([d] + [round(float(getattr(row, f"w_{s}")), 6) for s in SLEEVES]
                           + [round(float(getattr(row, f"pos_{s}")), 6) for s in SLEEVES]
                           + [round(float(row.bond_pos), 6), round(float(row.cash_exposure), 6)])
        raw = [float(getattr(row, f"w_{s}")) * float(getattr(row, f"p_{s}")) for s in SLEEVES]
        pool_supply = 1.0 - sum(raw)
        pool_demand = sum(value * 0.5 for value, s in zip(raw, SLEEVES)
                          if float(getattr(row, f"p_{s}")) >= 0.9)
        rp_daily[d] = {
            "w": [round(float(getattr(row, f"w_{s}")), 6) for s in SLEEVES],
            "p": [round(float(getattr(row, f"p_{s}")), 6) for s in SLEEVES],
            "borrow": [round(float(getattr(row, f"borrow_{s}")), 6) for s in SLEEVES],
            "S": round(pool_supply, 6), "D": round(pool_demand, 6),
            "tight": bool(pool_demand > 0 and pool_supply < pool_demand - 1e-12),
        }
    ret = nav.ret.to_numpy(float)
    sd = float(np.std(ret, ddof=1))
    annual = float(np.expm1(np.log1p(ret).sum() * 252 / len(ret)))
    mdd = float(nav.drawdown.min())
    metrics = {
        "start": str(nav.date.iloc[0].date()), "end": str(nav.date.iloc[-1].date()),
        "days": len(nav), "total_return": float(nav.nav.iloc[-1] - 1.0),
        "annual_return": annual, "annual_vol": float(sd * np.sqrt(252)),
        "sharpe": float(np.mean(ret) / sd * np.sqrt(252)), "max_drawdown": mdd,
        "calmar": annual / abs(mdd), "win_rate": float(np.mean(ret > 0)),
        "total_cost": float(nav.fee.sum()),
    }
    benchmarks = {
        "rp27": {"name": "风险平价2.7", "nav": [[str(r.date.date()), round(float(r.nav_rp27_rebased), 6),
                                                  round(float(r.drawdown_rp27), 6)] for r in nav.itertuples()]},
        "rp20": {"name": "风险平价2.0", "nav": [[str(r.date.date()), round(float(r.nav_rp20_rebased), 6),
                                                  round(float(r.drawdown_rp20), 6)] for r in nav.itertuples()]},
    }
    signals = build_signals()
    standalone = build_standalone(ROOT, [str(d.date()) for d in nav.date])
    beta_z = {key: value for key, value in build_beta_z().items() if key in {"a", "gl"}}
    commodity_dual = build_commodity_dual(ROOT)
    execution_status = build_execution_status(ROOT)
    reference_benchmarks = build_reference_benchmarks(ROOT, [str(d.date()) for d in nav.date])
    data = {"names": load_names(), "metrics": metrics, "nav": nav_rows, "weights": weight_rows,
            "rp_daily": rp_daily, "rebal_dates": [str(d.date()) for d in quarterly.rebal_date],
            "benchmarks": benchmarks, "positions": positions, "signals": signals,
            "performance": perf.to_dict(orient="records"),
            "standalone_strategies": standalone, "beta_z": beta_z,
            "a_environment": build_a_environment(),
            "hk_timing": build_hk_timing(rp_daily, signals),
            "reference_benchmarks": reference_benchmarks,
            "commodity_dual": commodity_dual,
            "execution_status": execution_status}
    OUT.parent.mkdir(parents=True, exist_ok=True)
    js = "window.STRATEGY_DATA = " + json.dumps(data, ensure_ascii=False, separators=(",", ":")) + ";"
    OUT.write_text(js, encoding="utf-8")
    import re
    import time
    html_path = OUT.parent / "index.html"
    html = html_path.read_text(encoding="utf-8")
    html = re.sub(r'data\.js(?:\?v=\d+)?', f'data.js?v={int(time.time())}', html, count=1)
    html_path.write_text(html, encoding="utf-8")
    print(f"写出{OUT}，{len(js)}字节，{len(nav_rows)}日，持仓偏差{max_dev:.3e}，"
          f"precompute {len(data['signals'])}份")


if __name__ == "__main__":
    main()
