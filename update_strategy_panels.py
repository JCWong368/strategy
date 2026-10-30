# -*- coding: utf-8 -*-
"""宏观4.0.7、industry7.2.7/7.2.9 日更与 GitHub Pages 统一部署。"""
import argparse
import subprocess
import sys
import time
from pathlib import Path

import pandas as pd

HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[1]
PRICE_LONG = ROOT / "03_运行类" / "etf_prices_long.csv"
INDUSTRY729 = ROOT / "06_行业轮动" / "industry7.2.9_global_stoploss_partial_rebuild_4to2_cap1.0_momfilter_abs"
NAV_FILES = {
    "宏观配置4.0.7": ROOT / "实盘运行策略" / "宏观配置4.0.7" / "results" / "nav_curve.csv",
    "industry7.2.7": ROOT / "06_行业轮动" / "industry7.2.7_global_stoploss_partial_rebuild_4to2" / "output" / "nav_curve.csv",
    "industry7.2.9": INDUSTRY729 / "output" / "nav_curve.csv",
}
PAGE_PATHS = ["macro407", "industry727", "industry729", "update_strategy_panels.py"]


def run(cmd, cwd):
    cmd = [str(c) for c in cmd]
    print(f"[CMD] {' '.join(cmd)}", flush=True)
    subprocess.run(cmd, cwd=str(cwd), check=True)


def latest_price_date():
    dates = pd.read_csv(PRICE_LONG, usecols=["date"], encoding="utf-8-sig")["date"]
    return pd.Timestamp(dates.max()).strftime("%Y-%m-%d")


def check_freshness(target_date):
    stale = []
    for name, path in NAV_FILES.items():
        dates = pd.read_csv(path, usecols=["date"], encoding="utf-8-sig")["date"]
        end = pd.Timestamp(dates.max()).strftime("%Y-%m-%d")
        print(f"[CHECK] {name} 净值末日 = {end}（目标 {target_date}）", flush=True)
        if end != target_date:
            stale.append(f"{name}={end}")
    if stale:
        raise RuntimeError(f"策略日期未对齐，中止网页部署：{', '.join(stale)}；目标={target_date}")


def deploy(target_date):
    run(["git", "add", "--"] + PAGE_PATHS, HERE)
    changed = subprocess.run(
        ["git", "diff", "--cached", "--quiet", "--"] + PAGE_PATHS,
        cwd=str(HERE),
    ).returncode
    if changed not in (0, 1):
        raise RuntimeError(f"git diff --cached 失败，exit={changed}")
    if changed == 1:
        run(["git", "commit", "-m", f"update strategy panels {target_date}"], HERE)
    else:
        print("[DEPLOY] 三个页面无内容变化，跳过提交；仍执行空推检查。", flush=True)
    for attempt in range(1, 6):
        result = subprocess.run(["git", "push"], cwd=str(HERE))
        if result.returncode == 0:
            print("[DEPLOY] 已推送到 GitHub，Pages 稍后自动更新。", flush=True)
            return
        print(f"[DEPLOY] 第 {attempt} 次推送失败，15 秒后重试。", flush=True)
        if attempt < 5:
            time.sleep(15)
    raise RuntimeError("git push 连续 5 次失败；本地提交已保留，等待既有补推任务恢复")


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--end-date", default="", help="目标交易日 YYYY-MM-DD；默认取 ETF 长表最新日")
    parser.add_argument("--skip-backtest", action="store_true", help="跳过 industry7.2.9 回测，仅校验并重建网页")
    parser.add_argument("--skip-deploy", action="store_true", help="只更新回测和网页文件，不执行 git 提交/推送")
    args = parser.parse_args()
    target_date = args.end_date or latest_price_date()
    pd.Timestamp(target_date).strftime("%Y-%m-%d")
    print(f"[START] 三策略页面目标交易日：{target_date}", flush=True)

    if args.skip_backtest:
        print("[SKIP] industry7.2.9 回测", flush=True)
    else:
        run([sys.executable, "-X", "utf8", "backtest.py",
             "--start", "2020-01-02", "--end", target_date], INDUSTRY729)
    check_freshness(target_date)

    run([sys.executable, "-X", "utf8", "-c",
         "import build_data; build_data.build(build_data.ROOT / '实盘运行策略/宏观配置4.0.7', "
         "build_data.HERE / 'macro407' / 'data.js')"], HERE)
    run([sys.executable, "-X", "utf8", "build_industry727_data.py"], HERE)
    run([sys.executable, "-X", "utf8", "build_industry729_data.py"], HERE)
    if args.skip_deploy:
        print("[SKIP] Git 提交与推送（--skip-deploy）", flush=True)
    else:
        deploy(target_date)
    print(f"[DONE] 三策略页面更新完成：{target_date}", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(main())
