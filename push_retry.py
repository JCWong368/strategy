# -*- coding: utf-8 -*-
"""网页展示仓库推送重试（06:30 / 07:00 / 07:30 定时任务）

用途：06:00 风险平价1.0 定时链路若因清晨网络未就绪推送失败（本地 commit 已保留），
由后续三个时点的本脚本补推。

行为：
  - 本地无未推送提交（HEAD == origin/main）→ 打印并退出 0（git push 空推是无副作用
    的 no-op，重复运行不会产生任何负面影响）；
  - 有未推送提交 → git push，失败重试 5 次、间隔 15 秒；
  - 日志：富易/开盘前调仓/logs/网页推送_YYYYMMDD_HHMMSS.log
"""
import subprocess
import sys
from pathlib import Path

WEB_DIR = Path(__file__).resolve().parent
LOG_DIR = WEB_DIR.parents[1] / '富易' / '开盘前调仓' / 'logs'
LOG_DIR.mkdir(parents=True, exist_ok=True)


def run(cmd, fh):
    fh.write(f"\n[CMD] {' '.join(cmd)}\n")
    fh.flush()
    return subprocess.run(cmd, cwd=str(WEB_DIR), stdout=fh,
                          stderr=subprocess.STDOUT).returncode


def main():
    import pandas as pd
    log_path = LOG_DIR / f"网页推送_{pd.Timestamp.now().strftime('%Y%m%d_%H%M%S')}.log"
    with open(log_path, 'w', encoding='utf-8') as fh:
        fh.write(f'网页推送重试任务，工作目录 {WEB_DIR}\n')
        rc = run(['git', 'rev-list', 'origin/main..HEAD', '--count'], fh)
        if rc != 0:
            print(f'[PUSH] ✗ 无法判定未推送提交数（exit {rc}），日志: {log_path}')
            return rc
        # 重新读取计数输出
        out = subprocess.run(['git', 'rev-list', 'origin/main..HEAD', '--count'],
                             cwd=str(WEB_DIR), capture_output=True, text=True).stdout.strip()
        if out == '0':
            fh.write('[PUSH] 本地与远端一致，无需推送（空推无副作用，直接退出）\n')
            print('[PUSH] 本地与远端一致，无需推送。')
            return 0
        fh.write(f'[PUSH] 待推送提交 {out} 个\n')
        for attempt in range(1, 6):
            rc = run(['git', 'push'], fh)
            if rc == 0:
                fh.write('[PUSH] ✓ 推送成功\n')
                print(f'[PUSH] ✓ 推送成功（第 {attempt} 次）。日志: {log_path}')
                return 0
            fh.write(f'[PUSH] 第 {attempt} 次推送失败，15 秒后重试\n')
            print(f'[PUSH] 第 {attempt} 次推送失败，15 秒后重试...')
            import time
            time.sleep(15)
        print(f'[PUSH] ✗ 5 次重试均失败，日志: {log_path}')
        return 1


if __name__ == '__main__':
    sys.exit(main())
