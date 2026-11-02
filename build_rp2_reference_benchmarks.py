# -*- coding: utf-8 -*-
"""由原始行情构建风险平价2.0网页的四条满仓参考基准。"""
from pathlib import Path

import numpy as np
import pandas as pd

ANNUAL_DAYS = 244
A_CODES = ['000300', '000905', '000852', '399006', '000680']
GL_WEIGHTS = {'SPX': 0.50, 'GDAXI': 0.15, 'FCHI': 0.15, 'N225': 0.20}
CMD_CODES = ['159980', '159985', '159981', '518880', '513350']
OIL_ENTRY = pd.Timestamp('2023-12-26')
FEE_RATE = 0.000055


def _metrics(frame: pd.DataFrame) -> dict:
    valid_nav = frame['nav'].dropna()
    ret = frame.loc[frame['nav'].notna(), 'ret'].dropna()
    n = len(valid_nav)
    if not n:
        raise RuntimeError('参考基准没有有效净值')
    years = n / ANNUAL_DAYS
    total_return = float(valid_nav.iloc[-1] - 1.0)
    annual_return = float(valid_nav.iloc[-1] ** (1.0 / years) - 1.0)
    vol = float(ret.std() * np.sqrt(ANNUAL_DAYS))
    sharpe = float(ret.mean() * ANNUAL_DAYS / vol) if vol > 0 else 0.0
    max_drawdown = float((valid_nav / valid_nav.cummax() - 1.0).min())
    return {
        'start': str(valid_nav.index[0].date()),
        'end': str(valid_nav.index[-1].date()),
        'days': n,
        'total_return': round(total_return, 4),
        'annual_return': round(annual_return, 4),
        'annual_vol': round(vol, 4),
        'sharpe': round(sharpe, 3),
        'max_drawdown': round(max_drawdown, 4),
        'calmar': round(annual_return / abs(max_drawdown), 3) if max_drawdown < 0 else None,
        'win_rate': round(float((ret > 0).mean()), 4),
        'total_cost': round(float(frame['fee'].sum()), 6),
    }


def _pack(daily: pd.DataFrame, dates: pd.DatetimeIndex, *, name: str,
          definition: str, price_basis: str, sources: list[str], notes: list[str],
          closed_dates=(), forced_missing=(), validation=None) -> dict:
    closed = pd.DatetimeIndex(closed_dates)
    forced = pd.DatetimeIndex(forced_missing)
    aligned = daily.reindex(dates).copy()
    if len(closed):
        filled_nav = daily['nav'].reindex(daily.index.union(dates)).sort_index().ffill().reindex(dates)
        aligned.loc[closed, 'nav'] = filled_nav.loc[closed]
        aligned.loc[closed, 'ret'] = 0.0
        aligned.loc[closed, 'fee'] = 0.0
    if len(forced):
        aligned.loc[forced, ['nav', 'ret', 'fee']] = np.nan
    first_valid = aligned['nav'].first_valid_index()
    if first_valid is None:
        raise RuntimeError(f'{name}没有有效净值')
    valid_mask = aligned['nav'].notna()
    fee_base = float(aligned.at[first_valid, 'nav'])
    aligned['nav'] = (1.0 + aligned['ret'].fillna(0.0)).cumprod()
    aligned.loc[~valid_mask, 'nav'] = np.nan
    base = float(aligned.at[first_valid, 'nav'])
    aligned['nav'] = aligned['nav'] / base
    aligned['fee'] = aligned['fee'] / fee_base
    missing_dates = aligned.index[aligned['nav'].isna()]
    if len(missing_dates):
        notes = notes + ['异常缺报价日期净值记null，不按0收益处理；其后首个有效收益承接最近有效行情。']
    quality = {
        'sources': sources,
        'missing_count': len(missing_dates),
        'missing_dates': [str(d.date()) for d in missing_dates],
        'normal_closed_count': len(closed),
        'normal_closed_dates': [str(d.date()) for d in closed],
        'notes': notes,
    }
    if validation:
        quality['validation'] = validation
    return {
        'name': name,
        'definition': definition,
        'price_basis': price_basis,
        'nav': [[str(d.date()), round(float(v), 6) if pd.notna(v) else None]
                for d, v in aligned['nav'].items()],
        'metrics': _metrics(aligned),
        'data_quality': quality,
    }


def _daily_from_returns(ret: pd.Series) -> pd.DataFrame:
    frame = pd.DataFrame({'ret': ret.astype(float)})
    frame['nav'] = (1.0 + frame['ret']).cumprod()
    frame['fee'] = 0.0
    return frame[['nav', 'ret', 'fee']]


def _build_a(root: Path, dates: pd.DatetimeIndex) -> dict:
    path = root / '03_运行类' / '指数_prices_long.csv'
    raw = pd.read_csv(path, dtype={'code': str}, usecols=['code', 'date', 'close'],
                      parse_dates=['date'], encoding='utf-8-sig')
    raw['code'] = raw['code'].str.strip()
    selected = raw[raw['code'].isin(A_CODES)]
    close = selected.drop_duplicates(['date', 'code']).pivot(
        index='date', columns='code', values='close').sort_index()
    returns = pd.DataFrame({code: close[code].dropna().pct_change(fill_method=None)
                            for code in A_CODES}).sort_index()
    ret = returns.mean(axis=1, skipna=False).dropna()
    return _pack(
        _daily_from_returns(ret), dates,
        name='A股五指数等权（A_FIVE_EQ）',
        definition='000300/000905/000852/399006/000680 日收益各20%，每日再平衡，纯数学零费。',
        price_basis='五条均为价格指数，不含股息再投资，不是全收益基准。',
        sources=['03_运行类/指数_prices_long.csv（close）'],
        notes=['不是指数点位均值；不使用A股策略、九格、N20或选股结果。'],
    )


def _build_hk(root: Path, dates: pd.DatetimeIndex) -> dict:
    proxy_path = root / '风险平价' / 'input' / 'hk_underlying_proxy.csv'
    env_path = root / '16_港股通' / '港股通九态系数择时' / 'output' / 'hk_env_labels.csv'
    proxy = pd.read_csv(proxy_path, parse_dates=['date'], encoding='utf-8-sig')
    proxy['ret_proxy'] = pd.to_numeric(proxy['ret_proxy'], errors='coerce')
    proxy = proxy.drop_duplicates('date').set_index('date').sort_index()
    env = pd.read_csv(env_path, usecols=['date', 'EW_close'], parse_dates=['date'],
                      encoding='utf-8-sig').drop_duplicates('date').set_index('date').sort_index()
    comparison = pd.DataFrame({
        'proxy': proxy['ret_proxy'],
        'env': env['EW_close'].pct_change(fill_method=None),
    }).dropna()
    error = float((comparison['proxy'] - comparison['env']).abs().max())
    if error > 1e-10:
        raise RuntimeError(f'港股ret_proxy与EW_close收益核验失败：{error}')
    valid = proxy['ret_proxy'].dropna()
    daily = _daily_from_returns(valid)
    forced = list(proxy.index[proxy['ret_proxy'].isna()].intersection(dates))
    forced += list(dates[(dates > valid.index[-1])])
    env_quoted = env.index[env['EW_close'].notna()]
    forced += list(dates.difference(proxy.index).intersection(env_quoted))
    closed = [d for d in dates.difference(proxy.index)
              if valid.index[0] <= d <= valid.index[-1]
              and d not in env_quoted and d not in set(forced)]
    return _pack(
        daily, dates,
        name='港股双指数等权（HK_EW）',
        definition='HSTECH与HSI点位等权EW的日收益，满仓，无九态或ETF轮动。',
        price_basis='HSTECH与HSI均为价格指数，不含股息再投资，不是全收益基准。',
        sources=['风险平价/input/hk_underlying_proxy.csv（ret_proxy）',
                 '16_港股通/港股通九态系数择时/output/hk_env_labels.csv（仅核验）'],
        notes=['A股交易日而港股正常休市时净值持平；源日期存在但缺收益、代理漏更或尾部停更记null。'],
        closed_dates=closed, forced_missing=forced,
        validation={'EW_close_pct_change_max_abs_diff': error,
                    'compared_return_days': len(comparison)},
    )


def _build_gl(root: Path, dates: pd.DatetimeIndex) -> dict:
    directory = root / '03_运行类' / '指数历史行情（东财）' / '全球指数'
    frames = {}
    for code in GL_WEIGHTS:
        path = directory / f'逐股输出（指数）_{code}.GI.csv'
        raw = pd.read_csv(path, encoding='gbk', thousands=',')
        raw = raw.rename(columns={'时间': 'date', '收盘价(元)': 'close'})
        raw['date'] = pd.to_datetime(raw['date'])
        raw['close'] = pd.to_numeric(raw['close'], errors='coerce')
        frames[code] = raw.dropna(subset=['close']).sort_values('date').set_index('date')['close']
    prices = pd.DataFrame(frames).sort_index().ffill().dropna()
    returns = prices.pct_change().fillna(0.0)
    weights = pd.Series(GL_WEIGHTS)
    ret = (returns[weights.index] * weights).sum(axis=1)
    daily = _daily_from_returns(ret)
    forced = dates[dates > prices.index[-1]]
    closed = [d for d in dates.difference(prices.index)
              if prices.index[0] <= d <= prices.index[-1]]
    return _pack(
        daily, dates,
        name='全球本币指数固定权重（GL_SIGNAL）',
        definition='SPX/GDAXI/FCHI/N225本币指数收益50%/15%/15%/20%，每日再平衡；并集日历ffill后dropna。',
        price_basis='GDAXI为全收益指数；SPX、FCHI、N225为价格指数。未统一汇率、分红或QDII溢折价。',
        sources=['03_运行类/指数历史行情（东财）/全球指数/逐股输出（指数）_{SPX,GDAXI,FCHI,N225}.GI.csv'],
        notes=['精确复刻全球组合指数择时1.0的原始文件读取与日历处理，但不使用其择时信号或ETF转换。',
               '四市场共同休市导致策略日历无合成报价时净值持平；尾部停更记null。'],
        closed_dates=closed, forced_missing=forced,
    )


def _commodity_daily(root: Path) -> pd.DataFrame:
    path = root / '03_运行类' / 'etf_prices_long.csv'
    raw = pd.read_csv(path, dtype={'code': str}, usecols=['code', 'date', 'open', 'close'],
                      parse_dates=['date'], encoding='utf-8-sig')
    raw['code'] = raw['code'].str.strip().str.zfill(6)
    selected = raw[raw['code'].isin(CMD_CODES)].drop_duplicates(['date', 'code'])
    opens = selected.pivot(index='date', columns='code', values='open').sort_index()
    closes = selected.pivot(index='date', columns='code', values='close').sort_index()
    base4 = CMD_CODES[:4]
    source_dates = opens[base4].dropna().index.intersection(closes[base4].dropna().index)
    cash, shares = 1.0, np.zeros(len(CMD_CODES))
    previous_nav = 1.0
    rows = []
    for dt in source_dates:
        active = base4 + (['513350'] if dt >= OIL_ENTRY else [])
        o = opens.loc[dt, CMD_CODES].to_numpy(dtype=float)
        c = closes.loc[dt, CMD_CODES].to_numpy(dtype=float)
        active_idx = [CMD_CODES.index(code) for code in active]
        if not np.isfinite(o[active_idx]).all() or not np.isfinite(c[active_idx]).all():
            continue
        pre = cash + sum(shares[i] * o[i] for i in range(len(CMD_CODES)) if shares[i] != 0)
        target = np.array([1.0 / len(active) if code in active else 0.0 for code in CMD_CODES])
        target_values = pre * target
        current_values = np.array([shares[i] * o[i] if shares[i] != 0 else 0.0
                                   for i in range(len(CMD_CODES))])
        buy = float(np.maximum(target_values - current_values, 0.0).sum())
        sell = float(np.maximum(current_values - target_values, 0.0).sum())
        fee = (buy + sell) * FEE_RATE
        cash = cash + sell - buy - fee
        shares = np.zeros(len(CMD_CODES))
        shares[active_idx] = target_values[active_idx] / o[active_idx]
        nav = cash + sum(shares[i] * c[i] for i in active_idx)
        rows.append({'date': dt, 'nav': nav, 'ret': nav / previous_nav - 1.0,
                     'fee': fee})
        previous_nav = nav
    return pd.DataFrame(rows).set_index('date')[['nav', 'ret', 'fee']]


def _build_cmd(root: Path, dates: pd.DatetimeIndex) -> dict:
    return _pack(
        _commodity_daily(root), dates,
        name='商品静态等权（CMD_STATIC）',
        definition='159980/159985/159981/518880各25%；自2023-12-26加入513350后五腿各20%，每日开盘调仓，单边费万0.55。',
        price_basis='使用长表已复权OHLC；费用已计入净值。复权ETF口径不等于独立全收益商品指数。',
        sources=['03_运行类/etf_prices_long.csv（复权open/close）'],
        notes=['513350上市前目标权重恒0且不回填价格；2023-12-26起纳入。',
               '每日开盘按目标权重买卖，买卖双边换手均按万0.55收费；异常缺报价日记null并暂停当日调仓。'],
    )


def build_reference_benchmarks(root: Path, nav_dates) -> dict:
    dates = pd.DatetimeIndex(pd.to_datetime(list(nav_dates))).sort_values().unique()
    return {
        'A_FIVE_EQ': _build_a(root, dates),
        'HK_EW': _build_hk(root, dates),
        'GL_SIGNAL': _build_gl(root, dates),
        'CMD_STATIC': _build_cmd(root, dates),
    }
