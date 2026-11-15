# -*- coding: utf-8 -*-
"""无杠杆5%波动率目标（五袖ENS）网页展示数据生成

输出 无杠杆5%_五袖ENS/data.js（window.STRATEGY_DATA = {...}），供同目录 index.html 使用。
"""
import ast
import json
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / '实盘运行策略' / '无杠杆5%_五袖ENS'
OUT = HERE / '无杠杆5%_五袖ENS' / 'data.js'
OUT.parent.mkdir(parents=True, exist_ok=True)

SLEEVES = ['a', 'hk', 'gl', 'cmd', 'bond']
GL_ETF_INNER = {'513500': 0.5, '513030': 0.15, '513080': 0.15, '513880': 0.2}
CMD_CODES = ['159980', '159985', '159981', '518880', '513350']
EXTRA_NAMES = {'513500': '标普500ETF博时', '513030': '德国ETF华安',
               '513080': '华安法国CAC40 ETF', '513880': '日经225ETF华安',
               '513350': '标普油气ETF富国', '518880': '华夏黄金ETF',
               '159980': '大成有色金属期货ETF', '159985': '华夏豆粕期货ETF',
               '159981': '建信易盛能源化工期货ETF', '511130': '30年国债ETF博时'}


def load_names() -> dict:
    names = dict(EXTRA_NAMES)
    for path, col in [
            (ROOT / '03_运行类' / 'long_table_code_names.csv', 'name'),
            (ROOT / '05_基金池' / 'ETF_my_pool_unique_66.csv', '基金简称'),
            (ROOT / '16_港股通' / 'ETF精选池_跨境_香港.csv', '名称')]:
        if path.exists():
            df = pd.read_csv(path, dtype={'code': str}, encoding='utf-8-sig')
            for _, r in df.iterrows():
                code = str(r['code']).strip().zfill(6)
                if code not in names and pd.notna(r[col]):
                    names[code] = str(r[col]).strip()
    return names


def build_positions(nav: pd.DataFrame, close_tab: pd.DataFrame) -> tuple:
    nav = nav.copy()
    nav['date'] = nav['date'].astype(str)
    a_pos = pd.read_csv(ROOT / '择时改进探索' / '08_九格系数替代四态_A股子策略'
                        / 'output' / 'positions_history.csv',
                        dtype={'code': str}, encoding='utf-8-sig')
    a_pos['code'] = a_pos['code'].str.strip().str.zfill(6)
    a_pos['date'] = a_pos['date'].astype(str)
    slot = pd.read_csv(ROOT / '06_行业轮动'
                       / 'industry7.2.7_global_stoploss_partial_rebuild_4to2'
                       / 'output' / 'daily_slot_holdings.csv', encoding='utf-8-sig')
    slot['date'] = pd.to_datetime(slot['date']).dt.strftime('%Y-%m-%d')
    hk_pos = pd.read_csv(ROOT / '16_港股通' / '港股通轮动1.0' / 'output'
                         / 'daily_slot_holdings.csv', encoding='utf-8-sig')
    hk_pos['date'] = pd.to_datetime(hk_pos['date']).dt.strftime('%Y-%m-%d')
    cmd = pd.read_csv(ROOT / '09_商品' / '商品风险平价双择时1.0' / 'output'
                      / 'primary_daily.csv', encoding='utf-8-sig')
    cmd['date'] = cmd['date'].astype(str)
    cmd_tp = cmd.set_index('date')['total_position']
    cmd_w = cmd.set_index('date')[[f'weight_{c}' for c in CMD_CODES]]

    positions = {}
    a_detail = {}
    max_dev = 0.0
    a_by_date = {d: g for d, g in a_pos.groupby('date')}
    slot_by_date = {d: g for d, g in slot.groupby('date')}
    hk_by_date = {d: g for d, g in hk_pos.groupby('date')}
    for _, r in nav.iterrows():
        d = r['date']
        rows = []
        raw_sum = 0.0

        def add(code, w):
            nonlocal raw_sum
            if w and w > 1e-8:
                raw_sum += float(w)
                rows.append([code, 0, round(float(w), 6)])

        pa = r['new_pos_a']
        phk = r['new_pos_hk']
        pgl = r['new_pos_gl']
        pcmd = r['new_pos_cmd']
        pbond = r['new_pos_bond']
        if d in slot_by_date:
            qty = {}
            for rr in slot_by_date[d].itertuples():
                for k, v in ast.literal_eval(rr.positions).items():
                    qty[k] = qty.get(k, 0.0) + float(v)
            mvs = []
            for code, q in qty.items():
                try:
                    price = close_tab.at[d, code]
                except KeyError:
                    price = np.nan
                mvs.append((code, q * price))
            s = sum(v for _, v in mvs if pd.notna(v))
            if s > 0:
                a_detail[d] = [[code, 0, round(v / s, 6)]
                               for code, v in sorted(mvs, key=lambda x: -x[1])
                               if pd.notna(v) and v > 0]
        if pa > 1e-12 and d in a_by_date:
            g = a_by_date[d]
            mvs = []
            for rr in g.itertuples():
                try:
                    price = close_tab.at[d, rr.code]
                except KeyError:
                    price = np.nan
                mvs.append((rr.code, rr.qty * price))
            s = sum(v for _, v in mvs if pd.notna(v))
            if s > 0:
                for code, v in mvs:
                    add(code, pa * v / s)
        if phk > 1e-12 and d in hk_by_date:
            qty = {}
            for rr in hk_by_date[d].itertuples():
                for k, v in ast.literal_eval(rr.positions).items():
                    qty[k] = qty.get(k, 0.0) + float(v)
            mvs = []
            for code, q in qty.items():
                try:
                    price = close_tab.at[d, code]
                except KeyError:
                    price = np.nan
                mvs.append((code, q * price))
            s = sum(v for _, v in mvs if pd.notna(v))
            if s > 0:
                for code, v in mvs:
                    add(code, phk * v / s)
        if pgl > 1e-12:
            for code, w in GL_ETF_INNER.items():
                add(code, pgl * w)
        if pcmd > 1e-12 and d in cmd_tp.index and cmd_tp[d] > 1e-12:
            scale = pcmd / cmd_tp[d]
            for code in CMD_CODES:
                add(code, cmd_w.at[d, f'weight_{code}'] * scale)
        add('511130', pbond)

        rows.sort(key=lambda x: -x[2])
        positions[d] = rows
        total = pa + phk + pgl + pcmd + pbond
        dev = abs(raw_sum - total)
        max_dev = max(max_dev, dev)
    return positions, a_detail, max_dev


def build_signals() -> dict:
    signals = {}
    for path in sorted((BASE / 'results' / 'precompute').glob('*_precompute.json')):
        try:
            pre = json.loads(path.read_text(encoding='utf-8'))
        except (OSError, json.JSONDecodeError):
            continue
        t = pre['meta']['t_date']
        entry = {
            't1_date': pre['meta']['t1_date'],
            'base_weights_asof': pre['meta']['base_weights_asof'],
            'base_weights': pre['base_weights'],
            'p': pre['p'],
            'base_pos': pre['base_pos'],
            'base_total_exposure': pre['base_total_exposure'],
            'borrow': pre['borrow'],
            'pool': pre['pool'],
            'bond_ens': pre['bond_ens'],
            'volatility': pre['volatility'],
            'pos': pre['pos'],
            'total_exposure': pre['total_exposure'],
            'cash': pre['cash'],
            'commodity_native_cash': pre['commodity_native_cash'],
            'total_cash': pre['total_cash'],
            'freshness': pre['freshness'],
            'weight_sum': pre['weight_sum'],
            't1_holdings': [],
        }
        holdings_path = path.with_name(path.name.replace(
            '_precompute.json', '_precompute_holdings.csv'))
        if holdings_path.exists():
            holdings = pd.read_csv(holdings_path, dtype={'code': str}, encoding='utf-8-sig')
            holdings['code'] = holdings['code'].str.strip().str.zfill(6)
            entry['t1_holdings'] = [
                [r.code, 0, round(float(r.weight), 6)] for r in holdings.itertuples()
            ]
        signals[t] = entry
    return signals


def main():
    nav = pd.read_csv(BASE / 'output' / 'nav_daily.csv', parse_dates=['date'])
    perf = pd.read_csv(BASE / 'output' / 'performance_summary.csv')
    weights_q = pd.read_csv(ROOT / '风险平价' / '五袖平价' / '无杠杆版' / 'output'
                            / 'quarterly_target_weights.csv', parse_dates=['rebal_date'])
    px = pd.read_csv(ROOT / '03_运行类' / 'etf_prices_long.csv', dtype={'code': str},
                     usecols=['code', 'date', 'close'], parse_dates=['date'])
    close_tab = px.pivot(index='date', columns='code', values='close')
    close_tab.index = close_tab.index.astype(str)

    names = load_names()
    positions, a_detail, max_dev = build_positions(nav, close_tab)
    print(f'持仓权重自校验 max_dev={max_dev:.3e}')

    nav_rows = []
    weight_rows = []
    rp_daily = {}
    ens_rows = []
    k_rows = []
    for _, r in nav.iterrows():
        d = str(r['date'])[:10]
        nav_rows.append([d, round(float(r['nav']), 6), round(float(r['ret']), 8),
                         round(float(r['drawdown']), 6)])
        weight_rows.append([d] + [round(float(r[f'w_{s}']), 6) for s in SLEEVES]
                           + [round(float(r[f'new_pos_{s}']), 6) for s in SLEEVES]
                           + [round(float(r['new_cash']), 6), round(float(r['new_total_exposure']), 6)])
        rp_daily[d] = {
            'w': [round(float(r[f'w_{s}']), 6) for s in SLEEVES],
            'p': [round(float(r[f'p_{s}']), 6) for s in SLEEVES],
            'borrow': [round(float(r[f'borrow_{s}']), 6) for s in SLEEVES],
            'S': round(float(r['pool_supply']), 6),
            'D': round(float(r['pool_demand']), 6),
            'tight': bool(r['pool_tight']),
        }
        ens_rows.append([d, float(r['target_ens']), float(r['ens_votes']),
                         float(r['ret_10']) if pd.notna(r['ret_10']) else None,
                         float(r['ret_20']) if pd.notna(r['ret_20']) else None,
                         float(r['ret_60']) if pd.notna(r['ret_60']) else None,
                         str(r['signal_date'])[:10] if pd.notna(r['signal_date']) else None])
        k_rows.append([d, round(float(r['k_exec']), 6), round(float(r['k_raw']), 6),
                       round(float(r['k_cap']), 6),
                       round(float(r['sigma_risky']), 6) if pd.notna(r['sigma_risky']) else None,
                       round(float(r['new_total_exposure']), 6), round(float(r['new_cash']), 6)])

    def perf_from_series(ret, exposure, bond_pos):
        r = ret.to_numpy(float)
        nav = np.r_[1.0, np.cumprod(1.0 + r)]
        dd = nav / np.maximum.accumulate(nav) - 1.0
        sd = float(np.std(r, ddof=1))
        ann = float(np.expm1(np.log1p(r).sum() * 252 / len(r)))
        mdd = float(dd.min())
        return {
            'total_return': float(np.prod(1.0 + r) - 1.0), 'geom_ann': ann,
            'ann_vol': float(sd * np.sqrt(252)), 'sharpe': float(np.mean(r) / sd * np.sqrt(252)),
            'max_dd': mdd, 'calmar': float(ann / abs(mdd)) if mdd < 0 else None,
            'win_rate': float(np.mean(r > 0)), 'mean_exposure': float(exposure.mean()),
            'mean_bond_pos': float(bond_pos.mean()),
        }

    benchmarks = {
        'baseline': {
            'name': '五袖＋国债ENS',
            'nav': [[str(r['date'])[:10], round(float(r['baseline_nav_rebased']), 6),
                     round(float(r['baseline_drawdown']), 6)] for _, r in nav.iterrows()],
            'metrics': perf_from_series(nav['baseline_ret'], nav['baseline_total_exposure'], nav['baseline_bond_pos']),
        },
        'rp28': {
            'name': '风险平价2.8',
            'nav': [[str(r['date'])[:10], round(float(r['rp28_nav_rebased']), 6),
                     round(float(r['rp28_drawdown']), 6)] for _, r in nav.iterrows()],
            'metrics': perf_from_series(nav['rp28_ret'], nav['rp28_total_exposure'], nav['rp28_bond_pos']),
        },
    }

    data = {
        'names': names,
        'metrics': perf_from_series(nav['ret'], nav['new_total_exposure'], nav['new_pos_bond']),
        'nav': nav_rows,
        'weights': weight_rows,
        'rp_daily': rp_daily,
        'rebal_dates': [str(d)[:10] for d in weights_q['rebal_date']],
        'ens_signals': ens_rows,
        'k_daily': k_rows,
        'benchmarks': benchmarks,
        'positions': positions,
        'a_detail': a_detail,
        'performance': perf.to_dict(orient='records'),
        'signals': build_signals(),
    }
    js = 'window.STRATEGY_DATA = ' + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';'
    OUT.write_text(js, encoding='utf-8')
    print(f'写出 {OUT}，{len(js)} 字节，{len(nav_rows)} 个交易日')


if __name__ == '__main__':
    main()
