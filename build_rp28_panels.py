# -*- coding: utf-8 -*-
"""风险平价2.8专属面板数据：商品双择时、独立绩效与执行状态。"""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pandas as pd

CMD_CODES = ["159980", "159985", "159981", "518880", "513350"]
CMD_NAMES = {"159980": "有色金属", "159985": "豆粕", "159981": "能源化工",
             "518880": "黄金", "513350": "标普油气"}
ANNUAL_DAYS = 244


def perf_metrics(nav: pd.Series, exposure: pd.Series) -> dict:
    nav = nav.dropna()
    ret = nav.pct_change(fill_method=None).dropna()
    if len(nav) < 2:
        raise RuntimeError("独立净值有效日期不足")
    annual = float(nav.iloc[-1] ** (ANNUAL_DAYS / len(nav)) - 1.0)
    vol = float(ret.std() * np.sqrt(ANNUAL_DAYS))
    maxdd = float((nav / nav.cummax() - 1.0).min())
    return {
        "start": str(nav.index[0].date()), "end": str(nav.index[-1].date()), "days": len(nav),
        "total_return": round(float(nav.iloc[-1] - 1.0), 4), "annual_return": round(annual, 4),
        "annual_vol": round(vol, 4),
        "sharpe": round(float(ret.mean() * ANNUAL_DAYS / vol), 3) if vol > 0 else 0.0,
        "max_drawdown": round(maxdd, 4),
        "calmar": round(annual / abs(maxdd), 3) if maxdd < 0 else None,
        "win_rate": round(float((ret > 0).mean()), 4),
        "avg_exposure": round(float(exposure.loc[nav.index].mean()), 4),
    }


def build_standalone(root: Path, dates: list[str]) -> dict:
    specs = {
        "a": {
            "name": "A股九格子策略", "short_name": "A股九格",
            "path": root / "择时改进探索/08_九格系数替代四态_A股子策略/output/nav_curve.csv",
            "nav_col": "combo_nav", "p_col": "w_a_stock",
            "definition": "行业轮动选股与slot执行，叠加N20四态固定系数×九态环境系数，独立运行。",
            "notes": ["原生净值已含交易费用与现金收益；九态映射为样本内设定。"],
        },
        "hk": {
            "name": "港股通九态子策略", "short_name": "港股",
            "path": root / "16_港股通/港股通九态系数择时/output/overlay_coef_v1.csv",
            "nav_col": "nav_overlay", "p_col": "coef_t1",
            "definition": "港股通轮动底仓叠加九态仓位系数，按反事实现金分层口径独立运行。",
            "notes": ["系数乘底仓整体日收益，并非精确分层持仓撮合；现金年化1%、单边费万0.55。"],
        },
        "gl": {
            "name": "全球组合指数择时子策略", "short_name": "全球",
            "path": root / "10_全球/全球组合指数择时1.0_ETF对照/output/daily_B_指数信号+ETF交易.csv",
            "nav_col": "nav", "p_col": "pos",
            "definition": "四国指数N5信号驱动四只QDII ETF，T+1开盘执行，月调与系数变化日调仓。",
            "notes": ["原生回测为零手续费口径，年换手较高，不可直接与其他扣费策略比较可交易性。"],
        },
        "cmd": {
            "name": "商品双择时子策略", "short_name": "商品",
            "path": root / "09_商品/商品风险平价双择时1.0/output/primary_daily.csv",
            "nav_col": "nav", "p_col": "total_position",
            "definition": "商品RP、整体N20与逐品种N60的整数手ETF组合，作为2.8商品原生输入。",
            "notes": ["原生内部费用为0，整数手交易形成少量现金残差；与组合层整体N20费用分开观察。"],
        },
    }
    axis = pd.DatetimeIndex(pd.to_datetime(dates)).sort_values().unique()
    result = {"window": {"start": str(axis[0].date()), "end": str(axis[-1].date())},
              "annual_days": ANNUAL_DAYS, "items": {}}
    for key, spec in specs.items():
        raw = pd.read_csv(spec["path"], encoding="utf-8-sig",
                          usecols=["date", spec["nav_col"], spec["p_col"]], parse_dates=["date"])
        raw = raw.sort_values("date").drop_duplicates("date", keep="last").set_index("date")
        raw = raw.rename(columns={spec["nav_col"]: "nav", spec["p_col"]: "p"})[["nav", "p"]]
        raw[["nav", "p"]] = raw[["nav", "p"]].apply(pd.to_numeric, errors="coerce")
        raw = raw.dropna(subset=["nav"])
        aligned = raw.reindex(axis)
        if aligned.nav.first_valid_index() != axis[0]:
            raise RuntimeError(f"{spec['name']}在共同窗口起点缺少独立净值")
        normalized = aligned.nav / float(aligned.nav.iloc[0])
        ret = normalized.pct_change(fill_method=None)
        ret.iloc[0] = 0.0
        metrics = perf_metrics(normalized, aligned.p)
        yearly = {}
        for year, group in ret.dropna().groupby(ret.dropna().index.year):
            yearly[str(year)] = round(float((1.0 + group).prod() - 1.0), 4)
        result["items"][key] = {
            **{k: spec[k] for k in ["name", "short_name", "definition", "notes"]},
            "source": str(spec["path"].relative_to(root)),
            "source_end": str(raw.index.max().date()),
            "metrics": metrics, "yearly": yearly,
            "series": [[str(dt.date()), round(float(normalized.loc[dt]), 6),
                        round(float(ret.loc[dt]), 6) if pd.notna(ret.loc[dt]) else None,
                        round(float(aligned.at[dt, "p"]), 6) if pd.notna(aligned.at[dt, "p"]) else None]
                       if pd.notna(normalized.loc[dt]) else [str(dt.date()), None, None, None]
                       for dt in axis],
        }
    return result


def build_commodity_dual(root: Path) -> dict:
    base = root / "09_商品" / "商品风险平价双择时1.0" / "output"
    overall = pd.read_csv(base / "overall_n20_signals.csv", parse_dates=["date"])
    overall = overall.sort_values("date").drop_duplicates("date", keep="last")
    coefficients = {"A": 1.0, "B": 1.0, "C": 0.2, "D": 0.7}
    overall_rows = [[r.date.strftime("%Y-%m-%d"), float(r.beta_annual) if pd.notna(r.beta_annual) else None,
                     float(r.z_score) if pd.notna(r.z_score) else None, r.state,
                     coefficients.get(r.state)] for r in overall.itertuples(index=False)]
    signals = pd.read_csv(base / "asset_n60_signals.csv", dtype={"code": str}, parse_dates=["date"])
    primary = pd.read_csv(base / "primary_daily.csv", parse_dates=["date"]).set_index("date")
    latest = {}
    history = {}
    for code in CMD_CODES:
        rows = signals.loc[signals.code == code].sort_values("date")
        output = []
        for r in rows.itertuples(index=False):
            d = r.date
            if d not in primary.index:
                continue
            native = primary.loc[d]
            scores = {c: float(native[f"rp_target_{c}"]) * float(native[f"coeff_{c}"])
                      if pd.notna(native[f"rp_target_{c}"]) and pd.notna(native[f"coeff_{c}"]) else 0.0
                      for c in CMD_CODES}
            score_sum = sum(scores.values())
            inner = scores[code] / score_sum if score_sum > 0 else 0.0
            output.append([d.strftime("%Y-%m-%d"),
                           float(r.beta_annual) if pd.notna(r.beta_annual) else None,
                           float(r.z_score) if pd.notna(r.z_score) else None, r.state,
                           float(r.signal_coefficient) if pd.notna(r.signal_coefficient) else None,
                           float(native[f"rp_target_{code}"]) if pd.notna(native[f"rp_target_{code}"]) else 0.0,
                           inner])
        valid = [r for r in output if r[4]]
        latest[code] = valid[-1] if valid else None
        history[code] = output
    diagnostics = pd.read_csv(root / "实盘运行策略" / "风险平价2.8_商品双择时" / "output"
                              / "commodity_diagnostics.csv")
    return {
        "overall": overall_rows,
        "assets": history,
        "latest": latest,
        "names": CMD_NAMES,
        "diagnostics": {key: value.item() if isinstance(value, np.generic) else value
                        for key, value in diagnostics.iloc[0].to_dict().items()},
        "source_end": str(overall.date.max().date()),
    }


def build_execution_status(root: Path) -> dict:
    base = root / "富易" / "开盘前调仓" / "风险平价2.8_商品双择时"
    scaled_files = sorted(base.glob("scaled_holdings_*.json"), key=lambda p: p.stat().st_mtime)
    if not scaled_files:
        return {"available": False}
    scaled_path = scaled_files[-1]
    scaled = json.loads(scaled_path.read_text(encoding="utf-8"))
    t = scaled["precompute_date"]
    pre = json.loads((root / "实盘运行策略" / "风险平价2.8_商品双择时" / "results" / "precompute"
                      / f"{t}_precompute.json").read_text(encoding="utf-8"))
    t1 = pre["meta"]["t1_date"]
    order_path = base / f"{t1}_开盘前调仓指令.xlsx"
    order = {"exists": order_path.exists(), "filename": order_path.name}
    if order_path.exists():
        frame = pd.read_excel(order_path)
        buy = frame[frame["交易类型"].astype(str).str.contains("买入")]
        sell = frame[frame["交易类型"].astype(str).str.contains("卖出")]
        order.update({
            "buy_count": len(buy), "buy_qty": int(buy["委托数量"].sum()),
            "sell_count": len(sell), "sell_qty": int(sell["委托数量"].sum()),
            "mtime": pd.Timestamp(order_path.stat().st_mtime, unit="s").strftime("%Y-%m-%d %H:%M:%S"),
        })
    return {
        "available": True, "t_date": t, "t1_date": t1,
        "total_assets": scaled["total_assets"], "used_mv": scaled["used_mv"],
        "residual_cash": scaled["residual_cash"], "residual_pct": scaled["residual_pct"],
        "scaled_weight_sum": float(sum(h["scaled_weight"] for h in scaled["holdings"])),
        "order": order,
    }
