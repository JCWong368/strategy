# -*- coding: utf-8 -*-
"""风险平价权重竞争 网页展示数据生成（复刻 build_rp1_data.py 的数据块结构）

输出 风险平价权重竞争/data.js（window.STRATEGY_DATA = {...}），供同目录 index.html 使用。
数据块：
  names / metrics / nav / weights / benchmarks / positions / a_stock_detail / signals
    —— 与风险平价1.0 同 schema
  rp_daily —— {date: {w: RP竞价权重四腿, p: 袖仓位系数四腿, bid: 竞价额四腿}}
自校验：每日 ETF 权重合计 ≈ Σa_i（容差 1e-6，超限打印 WARN）。

用法（项目根下，解释器按项目硬规则探测）：
  PYTHONPATH=C:/quant_env/pylibs "<python>" -X utf8 策略汇报/网页展示/build_rpc_data.py
"""
import ast
import json
import math
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / '实盘运行策略' / '风险平价权重竞争'
OUT = HERE / '风险平价权重竞争' / 'data.js'

GL_ETF_INNER = {'513500': 0.5, '513030': 0.15, '513080': 0.15, '513880': 0.2}
CMD_CODES = ['159980', '159985', '159981', '518880', '513350']
EXTRA_NAMES = {'513500': '标普500ETF博时', '513030': '德国ETF华安',
               '513080': '华安法国CAC40 ETF', '513880': '日经225ETF华安',
               '513350': '标普油气ETF富国', '518880': '华夏黄金ETF',
               '159980': '大成有色金属期货ETF', '159985': '华夏豆粕期货ETF',
               '159981': '建信易盛能源化工期货ETF'}
LEGS = ['ashare', 'hk', 'global', 'cmdty']


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
    """每日 ETF 持仓（组合层权重）+ A股袖内权重明细（不含择时缩放）。
    返回 (positions, a_detail, max_dev)。"""
    nav = nav.copy()

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

    # 商品内部权重（环境1.2 未位移口径 = 当日 T+1 目标；其 {code}_weight 之和
    # 为当日 total_position，组合层 = a_cmdty/p_cmdty 缩放）
    cmd = pd.read_csv(ROOT / '09_商品' / '商品环境1.2' / 'output'
                      / 'allocation_daily.csv', encoding='utf-8-sig')
    cmd['date'] = cmd['date'].astype(str)
    cmd_tp = cmd.set_index('date')['total_position']
    cmd_w = cmd.set_index('date')[[f'{c}_weight' for c in CMD_CODES]]

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

        aa, ah, ag, ac = r['a_ashare'], r['a_hk'], r['a_global'], r['a_cmdty']
        p_cmd = r['p_cmdty']
        # 选股底仓（行业轮动 slot，与择时仓位无关，p_a=0 日也展示）
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
        if aa > 1e-12 and d in a_by_date:
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
                    add(code, aa * v / s)
        if ah > 1e-12 and d in hk_by_date:
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
                    add(code, ah * v / s)
        if ag > 1e-12:
            for code, w in GL_ETF_INNER.items():
                add(code, ag * w)
        if ac > 1e-12 and d in cmd_tp.index and cmd_tp[d] > 1e-12:
            scale = ac / p_cmd if pd.notna(p_cmd) and p_cmd > 1e-12 else 0.0
            for code in CMD_CODES:
                add(code, cmd_w.at[d, f'{code}_weight'] * scale)

        rows.sort(key=lambda x: -x[2])
        positions[d] = rows
        total = aa + ah + ag + ac
        dev = abs(raw_sum - total)
        max_dev = max(max_dev, dev)
    return positions, a_detail, max_dev


def build_signals():
    signals = {}
    for f in sorted((BASE / 'results' / 'precompute').glob('*_precompute.json')):
        d = f.name.split('_')[0]
        try:
            j = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        al = j['allocation']
        entry = {
            't1_date': j['meta']['t1_date'],
            'weights_t1': {'w_a_stock': al['a_ashare'], 'w_hk': al['a_hk'],
                           'w_global': al['a_global'], 'w_commodity': al['a_cmdty'],
                           'w_cash': al['cash']},
            'rpc_info': {'w_rp': j['w_rp'], 'p': j['p'], 'bid': j['bid'],
                         'cap_triggered': al['cap_triggered'],
                         'rp_weights_asof': j['meta']['rp_weights_asof']},
        }
        hf = f.with_name(f.name.replace('_precompute.json', '_precompute_holdings.csv'))
        if hf.exists():
            hd = pd.read_csv(hf, dtype={'code': str}, encoding='utf-8-sig')
            hd['code'] = hd['code'].str.strip().str.zfill(6)
            entry['t1_holdings'] = [[r.code, 0, round(r.weight, 6)]
                                    for r in hd.itertuples()]
        signals[d] = entry
    return signals


def main():
    names = load_names()
    nav = pd.read_csv(BASE / 'output' / 'allocation_daily.csv', encoding='utf-8-sig')
    nav['date'] = nav['date'].astype(str)
    nav = nav.sort_values('date').reset_index(drop=True)
    nav['dd'] = nav['port_nav'] / nav['port_nav'].cummax() - 1.0

    nav_series = [[r.date, round(r.port_nav, 6), round(r.port_ret, 6), round(r.dd, 6)]
                  for r in nav.itertuples()]
    weight_series = [[r.date, round(r.a_ashare, 6), round(r.a_hk, 6),
                      round(r.a_global, 6), round(r.a_cmdty, 6), round(r.cash, 6)]
                     for r in nav.itertuples()]

    n = len(nav)
    years = n / 244
    total_ret = nav['port_nav'].iloc[-1] - 1
    ann_ret = nav['port_nav'].iloc[-1] ** (1 / years) - 1
    vol = nav['port_ret'].std() * math.sqrt(244)
    sharpe = (nav['port_ret'].mean() * 244) / vol if vol > 0 else 0
    maxdd = nav['dd'].min()
    win_rate = (nav['port_ret'] > 0).mean()
    metrics = {
        'start': nav['date'].iloc[0], 'end': nav['date'].iloc[-1], 'days': n,
        'total_return': round(total_ret, 4), 'annual_return': round(ann_ret, 4),
        'annual_vol': round(vol, 4), 'sharpe': round(sharpe, 3),
        'max_drawdown': round(maxdd, 4),
        'calmar': round(ann_ret / abs(maxdd), 3) if maxdd < 0 else None,
        'win_rate': round(win_rate, 4),
        'total_cost': round(float(nav['fee'].sum()), 6),  # 净值口径累计费用
    }

    # 基准（沪深300 + 中证500 等权，起点归一）
    benchmarks = {}
    idx = pd.read_csv(ROOT / '03_运行类' / '指数_prices_long.csv', dtype={'code': str},
                      usecols=['code', 'date', 'close'], encoding='utf-8-sig')
    idx['code'] = idx['code'].str.strip()
    nav_dates = nav['date'].tolist()
    legs = []
    for code in ['000300', '000905']:
        s = (idx[idx['code'] == code].drop_duplicates('date')
             .set_index('date')['close'].sort_index())
        s = s.reindex(sorted(set(s.index) | set(nav_dates))).ffill().reindex(nav_dates)
        legs.append(s / s.dropna().iloc[0])
    ew = sum(legs) / len(legs)
    benchmarks['等权基准'] = [round(v, 6) if pd.notna(v) else None for v in ew]

    # 价格查找表（A股持仓代码 + 港股 slot 代码 + 全球/商品，ffill）
    a_pos_codes = pd.read_csv(ROOT / '择时改进探索' / '08_九格系数替代四态_A股子策略'
                              / 'output' / 'positions_history.csv',
                              dtype={'code': str}, encoding='utf-8-sig',
                              usecols=['code'])['code'].unique()
    slot_codes = pd.read_csv(ROOT / '06_行业轮动'
                             / 'industry7.2.7_global_stoploss_partial_rebuild_4to2'
                             / 'output' / 'daily_slot_holdings.csv',
                             encoding='utf-8-sig',
                             usecols=['codes'])['codes'].str.split(',').explode().unique()
    hk_codes = pd.read_csv(ROOT / '16_港股通' / '港股通轮动1.0' / 'output'
                           / 'daily_slot_holdings.csv', encoding='utf-8-sig',
                           usecols=['codes'])['codes'].str.split(',').explode().unique()
    need_codes = (set(a_pos_codes) | set(slot_codes) | set(hk_codes)
                  | set(GL_ETF_INNER) | set(CMD_CODES))
    px = pd.read_csv(ROOT / '03_运行类' / 'etf_prices_long.csv', dtype={'code': str},
                     usecols=['code', 'date', 'close'], encoding='utf-8-sig')
    px['code'] = px['code'].str.strip().str.zfill(6)
    px['date'] = px['date'].astype(str)
    px = px[px['code'].isin(need_codes)]
    close_tab = px.drop_duplicates(['date', 'code']).pivot(
        index='date', columns='code', values='close')
    close_tab = close_tab.reindex(sorted(set(close_tab.index) | set(nav_dates))).ffill()

    # 商品袖 p_cmdty（sleeve_series）并入 nav 供缩放
    sleeve = pd.read_csv(BASE / 'data' / 'sleeve_series.csv', encoding='utf-8-sig')
    nav = nav.merge(sleeve[['date', 'p_cmdty']], on='date', how='left')

    positions, a_detail, max_dev = build_positions(nav, close_tab)
    print(f'[自校验] 每日 ETF 权重合计 vs Σa_i：最大偏差 {max_dev:.3e}'
          + ('（>1e-6，请检查）' if max_dev > 1e-6 else ' ✓'))

    # rp_daily：w_rp / p_i / bid 逐日（四腿顺序 a/hk/gl/cmd）
    sleeve_p = sleeve.set_index('date')[['p_ashare', 'p_hk', 'p_global', 'p_cmdty']]
    rp_daily = {}
    for _, r in nav.iterrows():
        d = r['date']
        p_row = sleeve_p.loc[d] if d in sleeve_p.index else None
        rp_daily[d] = {
            'w': [round(float(r[f'w_rp_{l}']), 6) for l in LEGS],
            'p': [None if p_row is None or pd.isna(p_row[f'p_{l}'])
                  else round(float(p_row[f'p_{l}']), 6) for l in LEGS],
            'bid': [round(float(r[f'bid_{l}']), 6) for l in LEGS],
        }

    signals = build_signals()

    # 季度重估日（净值图标注）
    q = pd.read_csv(BASE / 'output' / 'rp_weights_quarterly.csv', encoding='utf-8-sig')
    rebal_dates = [str(d)[:10] for d in pd.to_datetime(q['rebal_date'])]

    data = {
        'names': names, 'metrics': metrics, 'nav': nav_series,
        'weights': weight_series, 'benchmarks': benchmarks,
        'positions': positions, 'a_stock_detail': a_detail, 'rp_daily': rp_daily,
        'rebal_dates': rebal_dates,
        'signals': signals,
    }
    OUT.parent.mkdir(parents=True, exist_ok=True)
    OUT.write_text('window.STRATEGY_DATA = '
                   + json.dumps(data, ensure_ascii=False, separators=(',', ':')) + ';\n',
                   encoding='utf-8')
    # data.js 加构建版本号防浏览器缓存（每日重建后页面总能取到新数据）
    import re
    import time
    html = OUT.parent / 'index.html'
    if html.exists():
        s = html.read_text(encoding='utf-8')
        s2 = re.sub(r'src="data\.js(?:\?v=[^"]*)?"',
                    f'src="data.js?v={int(time.time())}"', s)
        if s2 != s:
            html.write_text(s2, encoding='utf-8')
    print(f'OK -> {OUT}（{OUT.stat().st_size / 1024:.0f} KB）')
    print(f'净值 {n} 天 | 持仓日期 {len(positions)} | RP 日度 {len(rp_daily)} | '
          f'precompute 信号 {len(signals)}')


if __name__ == '__main__':
    main()
