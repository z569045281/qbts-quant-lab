#!/usr/bin/env python
"""⚖️ 8/15 审判日一键报告(repo 根入口)。

    python audit.py

汇总 校准逐源命中 + AI 决策台账 + 纸面马 + 自选扫描账本,按预注册规则
(backend/dashboard/audit.py)给每个信号源判决:转正/剔除/继续测量。
只读不写;权重改动仍走人工 review。
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent / "backend"))

from dashboard.audit import format_report, run_audit  # noqa: E402

if __name__ == "__main__":
    print(format_report(run_audit()))
