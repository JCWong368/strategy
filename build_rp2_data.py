# -*- coding: utf-8 -*-
"""风险平价2.0 网页展示数据生成（完整复刻 macro407 数据块 + RP 专属块）

输出 风险平价2.0/data.js（window.STRATEGY_DATA = {...}），供同目录 index.html 使用。
数据块：
  names / metrics / nav / weights / benchmarks        —— 与 macro407 同 schema
  reference_benchmarks —— 四条独立满仓基准（由原始行情构建，含指标与数据质量）
  standalone_strategies —— 四子策略原生独立净值、择时仓位、绩效与分年收益
                           （含择时；不乘RP权重、不加共享池或国债）
  positions      —— 每日 ETF 持仓（组合层权重，回测生效口径）
  rp_daily       —— RP 底座生效权重 w_eff + 池借款 borrow + 池快照 S/D/tight
  rebal_dates    —— 季度重估日列表（净值图标注用）
  signals        —— precompute 信号（含 T+1 目标持仓，最新数据日及其后）
  beta_z         —— A股、全球、商品五腿的 beta/Z/状态历史（信号计算日）
  a_environment  —— A股九态环境、系数及回退状态历史（环境标签日）
  hk_timing      —— 港股九态仓位系数历史（生效日）与最新信号（标签日）
自校验：每日 ETF 权重合计 ≈ 四袖仓位+bond_pos（容差 1e-6，超限打印 WARN）；
        beta/Z 与 A/B/C/D 状态象限逐日一致；港股 p_hk 与 rp_daily/precompute
        同口径交叉核验，不一致即中止。

用法（项目根下，解释器按项目硬规则探测）：
  PYTHONPATH=C:/quant_env/pylibs "<python>" -X utf8 策略汇报/网页展示/build_rp2_data.py
"""
import ast
import copy
import json
import math
import sys
from pathlib import Path

import numpy as np
import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
BASE = ROOT / '实盘运行策略' / '风险平价2.0'
OUT = HERE / '风险平价2.0' / 'data.js'
sys.path.insert(0, str(ROOT / '风险平价' / 'src'))
import core  # noqa: E402
from build_rp2_reference_benchmarks import build_reference_benchmarks  # noqa: E402

CFG = core.load_cfg()
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
    """每日 ETF 持仓（组合层权重）+ A股袖内权重明细（不含择时缩放）。
    返回 (positions, a_detail, max_dev)。"""
    nav = nav.copy()
    nav['date'] = nav['date'].astype(str)
    pos_a = nav.set_index('date')['pos_a']
    pos_hk = nav.set_index('date')['pos_hk']
    pos_gl = nav.set_index('date')['pos_gl']
    pos_cmd = nav.set_index('date')['pos_cmd']

    # A股：组合层行用 08_九格 positions_history × pos_a；选股底仓（a_detail）
    # 用行业轮动 slot 持仓——joint9 只缩放整体仓位不改选股，p_a=0 日选股依然可见
    a_pos = pd.read_csv(ROOT / '择时改进探索' / '08_九格系数替代四态_A股子策略'
                        / 'output' / 'positions_history.csv',
                        dtype={'code': str}, encoding='utf-8-sig')
    a_pos['code'] = a_pos['code'].str.strip().str.zfill(6)
    a_pos['date'] = a_pos['date'].astype(str)
    slot = pd.read_csv(ROOT / '06_行业轮动'
                       / 'industry7.2.7_global_stoploss_partial_rebuild_4to2'
                       / 'output' / 'daily_slot_holdings.csv', encoding='utf-8-sig')
    slot['date'] = pd.to_datetime(slot['date']).dt.strftime('%Y-%m-%d')

    # 港股：轮动1.0 daily_slot_holdings（当日全部 slot 合并）
    hk_pos = pd.read_csv(ROOT / '16_港股通' / '港股通轮动1.0' / 'output'
                         / 'daily_slot_holdings.csv', encoding='utf-8-sig')
    hk_pos['date'] = pd.to_datetime(hk_pos['date']).dt.strftime('%Y-%m-%d')

    # 商品：环境1.2 allocation（内部权重 × pos_cmd/p_cmd）
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

        pa, phk, pgl, pcmd = r['pos_a'], r['pos_hk'], r['pos_gl'], r['pos_cmd']
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
        # 组合层 A股行（引擎实际持仓 × pos_a，p_a=0 时为空）
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
                add(code, cmd_w.at[d, f'{code}_weight'] * scale)
        add('511130', r['bond_pos'])

        rows.sort(key=lambda x: -x[2])
        positions[d] = rows
        total = pa + phk + pgl + pcmd + r['bond_pos']
        dev = abs(raw_sum - total)
        max_dev = max(max_dev, dev)
    return positions, a_detail, max_dev


def build_rp_daily(nav: pd.DataFrame):
    """RP 底座生效权重 + 池借款（与回测 simulate_archive 同函数重算）。"""
    cfg_ext = copy.deepcopy(CFG)
    cfg_ext['window']['end'] = '2026-12-31'
    inp = core.load_inputs(cfg_ext)
    win = inp['win']
    rp = core.compute_rp_base(CFG, inp['sig_hist'], win)
    sys.path.insert(0, str(BASE))
    from run_backtest import load_rp1  # noqa: E402
    w_arch = load_rp1().archive_weights(rp['daily_eff'])
    w = {s: w_arch[f'w_{s}'].to_numpy(dtype=float) for s in core.SLEEVES}
    p = {s: win[core.P_COL[s]].to_numpy(dtype=float) for s in core.SLEEVES}
    wp = {s: w[s] * p[s] for s in core.SLEEVES}
    pool = core.pool_borrow(wp, w, p, CFG)
    dates = [str(d)[:10] for d in win['date']]
    rp_daily = {}
    for i, d in enumerate(dates):
        rp_daily[d] = {
            'w': [round(float(w[s][i]), 6) for s in core.SLEEVES],
            'p': [round(float(p[s][i]), 6) for s in core.SLEEVES],
            'borrow': [round(float(pool['borrow'][s][i]), 6) for s in core.SLEEVES],
            'S': round(float(pool['S'][i]), 6),
            'D': round(float(pool['D'][i]), 6),
            'tight': bool(pool['tight'][i]),
        }
    rebal_dates = [str(d)[:10] for d in rp['quarterly']['rebal_date']]
    return rp_daily, rebal_dates


def build_signals():
    signals = {}
    for f in sorted((BASE / 'results' / 'precompute').glob('*_precompute.json')):
        d = f.name.split('_')[0]
        try:
            j = json.loads(f.read_text(encoding='utf-8'))
        except Exception:
            continue
        pos, p = j['pos'], j['p']
        entry = {
            't1_date': j['meta']['t1_date'],
            'weights_t1': {'w_a_stock': pos['a'], 'w_hk': pos['hk'],
                           'w_global': pos['gl'], 'w_commodity': pos['cmd'],
                           'w_bond': j['bond_pos'], 'w_cash': j['cash']},
            'rp_info': {'base_weights': j['base_weights'], 'p': p,
                        'borrow': j['borrow'], 'pool': j['pool'],
                        'bond_code': j['bond_code'], 'bond_pos': j['bond_pos'],
                        'base_weights_asof': j['meta']['base_weights_asof']},
        }
        hf = f.with_name(f.name.replace('_precompute.json', '_precompute_holdings.csv'))
        if hf.exists():
            hd = pd.read_csv(hf, dtype={'code': str}, encoding='utf-8-sig')
            hd['code'] = hd['code'].str.strip().str.zfill(6)
            entry['t1_holdings'] = [[r.code, 0, round(r.weight, 6)]
                                    for r in hd.itertuples()]
        signals[d] = entry
    return signals


def build_a_environment():
    """A股九态环境：标签日历史、系数映射及预热/缺失回退标记。"""
    a9_source = (ROOT / '择时改进探索' / '08_九格系数替代四态_A股子策略'
                 / 'run_backtest.py').read_text(encoding='utf-8')
    coef_map = None
    for node in ast.parse(a9_source).body:
        if isinstance(node, ast.Assign) and any(
                isinstance(t, ast.Name) and t.id == 'JOINT9_COEF' for t in node.targets):
            coef_map = ast.literal_eval(node.value)
            break
    if coef_map is None:
        raise RuntimeError('无法读取A股九格 JOINT9_COEF 单一事实源')

    path = ROOT / '市场环境' / 'timeseries' / 'env_labels_main.csv'
    env = pd.read_csv(path, encoding='utf-8-sig', parse_dates=['date'])
    env = env.sort_values('date').drop_duplicates('date', keep='last')
    first_valid = env.loc[env['joint9'].isin(coef_map), 'date'].min()
    rows = []
    for r in env.itertuples(index=False):
        cell = str(r.joint9) if pd.notna(r.joint9) and r.joint9 else None
        valid = cell in coef_map
        if valid:
            parts = cell.split('×')
            if len(parts) != 2 or parts[0] != r.M1d or parts[1] != r.M2:
                raise RuntimeError(f'A股九态与 M1d/M2 不一致：{r.date.date()}={cell}')
            coef = float(coef_map[cell])
            status = '正常'
        else:
            coef = None
            status = ('预热期·回退原环境系数' if r.date < first_valid
                      else '九格缺失·回退原环境系数')
        rows.append([r.date.strftime('%Y-%m-%d'), cell,
                     str(r.M1d) if pd.notna(r.M1d) else None,
                     str(r.M2) if pd.notna(r.M2) else None, coef, status])
    return {'rows': rows, 'coef_map': coef_map,
            'source_end': env['date'].max().strftime('%Y-%m-%d')}


def build_hk_timing(rp_daily, signals):
    """港股九态仓位系数：历史按生效日，最新信号按标签日；只读上游产物。"""
    from bisect import bisect_right

    hk_dir = ROOT / '16_港股通' / '港股通九态系数择时'
    sys.path.insert(0, str(hk_dir))
    from overlay_backtest import COEF as coef_map

    overlay = pd.read_csv(hk_dir / 'output' / 'overlay_coef_v1.csv',
                          encoding='utf-8-sig', parse_dates=['date'])
    overlay = overlay.sort_values('date').drop_duplicates('date', keep='last')
    labels = pd.read_csv(hk_dir / 'output' / 'hk_env_labels.csv',
                         encoding='utf-8-sig', parse_dates=['date'])
    labels = labels[pd.notna(labels['EW_joint9']) & (labels['EW_joint9'] != '')]
    label_days = list(labels['date'].sort_values())
    label_by_day = dict(zip(labels['date'], labels['EW_joint9']))

    def label_asof(day):
        if day is None:
            return None
        pos = bisect_right(label_days, day) - 1
        return label_days[pos] if pos >= 0 else None

    rows = []
    previous_date = None
    for r in overlay.itertuples(index=False):
        effective_date = r.date
        p = float(r.coef_t1)
        if not 0 <= p <= 1:
            raise RuntimeError(f'港股仓位系数越界：{effective_date.date()}={p}')
        cell = str(r.cell_lag1) if pd.notna(r.cell_lag1) and r.cell_lag1 else None
        label_date = label_asof(previous_date or effective_date)
        if cell is None:
            status = '无标签回退1.0'
        elif label_date is not None and previous_date is not None and label_date < previous_date:
            status = '沿用历史标签'
        else:
            status = '正常'
        rows.append([effective_date.strftime('%Y-%m-%d'), p, cell,
                     previous_date.strftime('%Y-%m-%d') if previous_date is not None else None,
                     label_date.strftime('%Y-%m-%d') if label_date is not None else None,
                     status])
        rp = rp_daily.get(effective_date.strftime('%Y-%m-%d'))
        if rp is not None and abs(p - rp['p'][1]) > 1e-6:
            raise RuntimeError(f'港股 p_hk 与 rp_daily 不一致：{effective_date.date()}')
        previous_date = effective_date

    latest_label_date = label_days[-1]
    latest_cell = str(label_by_day[latest_label_date])
    latest_signal = {
        'date': latest_label_date.strftime('%Y-%m-%d'),
        'cell': latest_cell,
        'coef': float(coef_map.get(latest_cell, 1.0)),
        'effective_date': '次交易日',
    }
    if signals:
        pre_date = max(signals)
        pre = signals[pre_date]
        if pre_date == latest_signal['date']:
            pre_p = float(pre['rp_info']['p']['p_hk'])
            if abs(pre_p - latest_signal['coef']) > 1e-6:
                raise RuntimeError('港股最新信号系数与 precompute p_hk 不一致')
            latest_signal['effective_date'] = pre['t1_date']
    return {'rows': rows, 'latest_signal': latest_signal, 'coef_map': coef_map}


def build_standalone_strategies(root: Path, nav_dates, rp_daily) -> dict:
    """四子策略原生独立净值：含各自择时，不乘RP权重、不加共享池或国债。"""
    annual_days = 244
    specs = {
        'a': {
            'name': 'A股九格子策略', 'short_name': 'A股', 'p_index': 0,
            'path': root / '择时改进探索/08_九格系数替代四态_A股子策略/output/nav_curve.csv',
            'nav_col': 'combo_nav', 'p_col': 'w_a_stock',
            'source': '择时改进探索/08_九格系数替代四态_A股子策略/output/nav_curve.csv',
            'definition': '行业轮动选股与slot执行，叠加N20四态固定系数×九态环境系数，独立满仓上限运行。',
            'notes': ['原生净值已含交易费用与现金收益；九态映射为样本内设定。'],
        },
        'hk': {
            'name': '港股通九态子策略', 'short_name': '港股', 'p_index': 1,
            'path': root / '16_港股通/港股通九态系数择时/output/overlay_coef_v1.csv',
            'nav_col': 'nav_overlay', 'p_col': 'coef_t1',
            'source': '16_港股通/港股通九态系数择时/output/overlay_coef_v1.csv',
            'definition': '港股通轮动底仓叠加九态仓位系数，按反事实现金分层口径独立运行。',
            'notes': ['系数乘底仓整体日收益，并非精确分层持仓撮合；现金年化1%、单边费万0.55。',
                      '九态映射为样本内人工设定。'],
        },
        'gl': {
            'name': '全球组合指数择时子策略', 'short_name': '全球', 'p_index': 2,
            'path': root / '10_全球/全球组合指数择时1.0_ETF对照/output/daily_B_指数信号+ETF交易.csv',
            'nav_col': 'nav', 'p_col': 'pos',
            'source': '10_全球/全球组合指数择时1.0_ETF对照/output/daily_B_指数信号+ETF交易.csv',
            'definition': '四国指数N5信号驱动四只QDII ETF，T+1开盘执行，月调与系数变化日调仓。',
            'notes': ['原生回测为零手续费口径，年换手较高，不可直接与其他扣费策略比较可交易性。',
                      'QDII溢折价、汇率与跟踪误差已体现在ETF价格中，但不另建模型。'],
        },
        'cmd': {
            'name': '商品环境1.2子策略', 'short_name': '商品', 'p_index': 3,
            'path': root / '09_商品/商品环境1.2/output/allocation_daily.csv',
            'nav_col': 'nav', 'p_col': 'total_position',
            'source': '09_商品/商品环境1.2/output/allocation_daily.csv',
            'definition': '商品五腿状态与环境系数分配，总仓位由在场腿平均有效系数决定，T+1开盘执行。',
            'notes': ['原生净值已含单边万0.55费用，现金不计息；部分状态与环境系数为样本内设定。'],
        },
    }
    dates = pd.DatetimeIndex(pd.to_datetime(list(nav_dates))).sort_values().unique()
    raw_items = {}
    for key, spec in specs.items():
        raw = pd.read_csv(spec['path'], encoding='utf-8-sig',
                          usecols=['date', spec['nav_col'], spec['p_col']], parse_dates=['date'])
        raw = (raw.sort_values('date').drop_duplicates('date', keep='last')
               .set_index('date')[[spec['nav_col'], spec['p_col']]])
        raw.columns = ['nav', 'p']
        raw[['nav', 'p']] = raw[['nav', 'p']].apply(pd.to_numeric, errors='coerce')
        raw = raw.dropna(subset=['nav'])
        if raw.empty or not raw.index.is_monotonic_increasing:
            raise RuntimeError(f'{spec["name"]}独立净值无效')
        raw['ret'] = raw['nav'].pct_change(fill_method=None)
        raw_items[key] = raw

    common_end = min([dates.max()] + [raw.index.max() for raw in raw_items.values()])
    target_dates = dates[dates <= common_end]
    if not len(target_dates):
        raise RuntimeError('四子策略与风险平价2.0没有共同展示日期')
    result = {
        'window': {'start': str(target_dates[0].date()), 'end': str(target_dates[-1].date())},
        'annual_days': annual_days,
        'items': {},
    }
    for key, spec in specs.items():
        raw = raw_items[key]
        aligned = raw.reindex(target_dates)
        first_valid = aligned['nav'].first_valid_index()
        if first_valid is None or first_valid != target_dates[0]:
            raise RuntimeError(f'{spec["name"]}在共同窗口起点缺少独立净值')
        normalized = aligned['nav'] / float(aligned['nav'].iloc[0])
        ret = aligned['ret'].copy()
        ret.iloc[0] = 0.0
        valid = normalized.notna()
        valid_nav = normalized[valid]
        valid_ret = ret[valid].dropna()
        n = len(valid_nav)
        if n < 2:
            raise RuntimeError(f'{spec["name"]}独立净值有效日期不足')
        ann = float(valid_nav.iloc[-1] ** (annual_days / n) - 1.0)
        vol = float(valid_ret.std() * np.sqrt(annual_days))
        maxdd = float((valid_nav / valid_nav.cummax() - 1.0).min())
        metrics = {
            'start': str(valid_nav.index[0].date()), 'end': str(valid_nav.index[-1].date()),
            'days': n, 'total_return': round(float(valid_nav.iloc[-1] - 1.0), 4),
            'annual_return': round(ann, 4), 'annual_vol': round(vol, 4),
            'sharpe': round(float(valid_ret.mean() * annual_days / vol), 3) if vol > 0 else 0.0,
            'max_drawdown': round(maxdd, 4),
            'calmar': round(ann / abs(maxdd), 3) if maxdd < 0 else None,
            'win_rate': round(float((valid_ret > 0).mean()), 4),
            'avg_exposure': round(float(aligned.loc[valid, 'p'].mean()), 4),
        }
        yearly = {}
        for year, group in ret[valid].dropna().groupby(ret[valid].dropna().index.year):
            yearly[str(year)] = round(float((1.0 + group).prod() - 1.0), 4)

        p_diffs = []
        for dt, p in aligned['p'].dropna().items():
            day = str(dt.date())
            if day in rp_daily:
                p_diffs.append(abs(float(p) - float(rp_daily[day]['p'][spec['p_index']])))
        max_p_diff = max(p_diffs, default=0.0)
        if max_p_diff > 1e-6:
            raise RuntimeError(f'{spec["name"]}独立择时仓位与rp_daily不一致：{max_p_diff}')
        missing_dates = [str(d.date()) for d in aligned.index[aligned['nav'].isna()]]
        result['items'][key] = {
            'name': spec['name'], 'short_name': spec['short_name'],
            'definition': spec['definition'], 'source': spec['source'],
            'source_end': str(raw.index.max().date()), 'metrics': metrics, 'yearly': yearly,
            'series': [[str(dt.date()), round(float(normalized.loc[dt]), 6),
                        round(float(ret.loc[dt]), 6) if pd.notna(ret.loc[dt]) else None,
                        round(float(aligned.at[dt, 'p']), 6) if pd.notna(aligned.at[dt, 'p']) else None]
                       if valid.loc[dt] else [str(dt.date()), None, None, None]
                       for dt in target_dates],
            'data_quality': {
                'missing_count': len(missing_dates), 'missing_dates': missing_dates,
                'timing_max_abs_diff_vs_rp': max_p_diff,
                'timing_compared_days': len(p_diffs),
                'notes': spec['notes'],
            },
        }
    return result


def build_beta_z():
    """袖最终 beta/Z 信号参数：A股、全球及商品五腿；使用信号计算日。"""
    commodity_states = ROOT / '09_商品' / '商品择时2.0_N5组合回测' / 'states'
    sources = [
        ('a', 'A股', 'A股综合指数', 'N20',
         ROOT / '02_分析类' / '综合指数N20N5状态' / 'composite_n20n5_states.csv',
         'beta_n20', 'Z_n20', 'N20'),
        ('gl', '全球', '全球四国组合指数', 'N5',
         ROOT / '10_全球' / '全球组合指数择时1.0' / 'output' / 'signal_daily.csv',
         'beta_annual', 'Z', 'N20_state'),
    ]
    for code, name in [('159980', '有色'), ('159985', '豆粕'),
                       ('159981', '能化'), ('518880', '黄金')]:
        sources.append((f'cmd_{code}', '商品', f'{name}{code}', 'N5',
                        commodity_states / f'{code}_n5_states.csv',
                        'beta_annual', 'Z', 'N5'))
    sources.append((
        'cmd_513350', '商品', '油气513350', 'N3',
        ROOT / '09_商品' / '商品环境1.0' / '油气' / 'N窗口搜索' / 'output' /
        'states' / '513350_n3_states.csv', 'beta_annual', 'Z', 'N5'))

    def quadrant(beta, z):
        if beta >= 0 and z >= 0:
            return 'A'
        if beta >= 0:
            return 'B'
        return 'D' if z >= 0 else 'C'

    out = {}
    for key, sleeve, name, window, path, beta_col, z_col, state_col in sources:
        df = pd.read_csv(path, encoding='utf-8-sig',
                         usecols=['date', beta_col, z_col, state_col])
        df['date'] = pd.to_datetime(df['date'])
        df = df.sort_values('date').drop_duplicates('date', keep='last')
        rows = []
        mismatches = []
        for r in df.itertuples(index=False):
            beta_raw, z_raw = getattr(r, beta_col), getattr(r, z_col)
            beta = float(beta_raw) if pd.notna(beta_raw) else None
            z = float(z_raw) if pd.notna(z_raw) else None
            state = str(getattr(r, state_col)) if pd.notna(getattr(r, state_col)) else None
            if beta is not None and z is not None and state:
                expected = quadrant(beta, z)
                if state != expected:
                    mismatches.append((r.date.strftime('%Y-%m-%d'), state, expected))
            rows.append([r.date.strftime('%Y-%m-%d'), beta, z, state])
        if mismatches:
            raise RuntimeError(f'{name} beta/Z 与状态象限不一致：{mismatches[:5]}')
        out[key] = {'name': name, 'sleeve': sleeve, 'window': window, 'rows': rows}
    return out


def main():
    names = load_names()
    nav = pd.read_csv(BASE / 'output' / 'nav_daily.csv', encoding='utf-8-sig')
    nav['date'] = nav['date'].astype(str)
    nav = nav.sort_values('date').reset_index(drop=True)
    nav['dd'] = nav['nav'] / nav['nav'].cummax() - 1.0

    nav_series = [[r.date, round(r.nav, 6), round(r.ret, 6), round(r.dd, 6)]
                  for r in nav.itertuples()]
    weight_series = [[r.date, round(r.pos_a, 6), round(r.pos_hk, 6),
                      round(r.pos_gl, 6), round(r.pos_cmd, 6), round(r.bond_pos, 6),
                      round(r.cash_exposure, 6)] for r in nav.itertuples()]

    n = len(nav)
    years = n / 244
    total_ret = nav['nav'].iloc[-1] - 1
    ann_ret = nav['nav'].iloc[-1] ** (1 / years) - 1
    vol = nav['ret'].std() * math.sqrt(244)
    sharpe = (nav['ret'].mean() * 244) / vol if vol > 0 else 0
    maxdd = nav['dd'].min()
    win_rate = (nav['ret'] > 0).mean()
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
                  | set(GL_ETF_INNER) | set(CMD_CODES) | {'511130'})
    px = pd.read_csv(ROOT / '03_运行类' / 'etf_prices_long.csv', dtype={'code': str},
                     usecols=['code', 'date', 'close'], encoding='utf-8-sig')
    px['code'] = px['code'].str.strip().str.zfill(6)
    px['date'] = px['date'].astype(str)
    px = px[px['code'].isin(need_codes)]
    close_tab = px.drop_duplicates(['date', 'code']).pivot(
        index='date', columns='code', values='close')
    close_tab = close_tab.reindex(sorted(set(close_tab.index) | set(nav_dates))).ffill()

    positions, a_detail, max_dev = build_positions(nav, close_tab)
    print(f'[自校验] 每日 ETF 权重合计 vs 四袖+国债：最大偏差 {max_dev:.3e}'
          + ('（>1e-6，请检查）' if max_dev > 1e-6 else ' ✓'))

    rp_daily, rebal_dates = build_rp_daily(nav)
    standalone = build_standalone_strategies(ROOT, nav_dates, rp_daily)
    print(f'[独立绩效] {standalone["window"]["start"]} ~ {standalone["window"]["end"]} | '
          + ' | '.join(f'{v["short_name"]} p核对 {v["data_quality"]["timing_max_abs_diff_vs_rp"]:.1e}'
                       for v in standalone['items'].values()))
    signals = build_signals()
    reference_benchmarks = build_reference_benchmarks(ROOT, nav_dates)
    beta_z = build_beta_z()
    a_environment = build_a_environment()
    hk_timing = build_hk_timing(rp_daily, signals)

    data = {
        'names': names, 'metrics': metrics, 'nav': nav_series,
        'weights': weight_series, 'benchmarks': benchmarks,
        'reference_benchmarks': reference_benchmarks,
        'standalone_strategies': standalone,
        'positions': positions, 'a_stock_detail': a_detail, 'rp_daily': rp_daily,
        'rebal_dates': rebal_dates, 'signals': signals, 'beta_z': beta_z,
        'a_environment': a_environment, 'hk_timing': hk_timing,
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
          f'重估日 {len(rebal_dates)} | precompute 信号 {len(signals)}')


if __name__ == '__main__':
    main()
