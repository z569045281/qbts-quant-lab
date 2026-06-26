#!/usr/bin/env python3
"""
Generate the monthly retrospective and write it to Supabase.

    .venv/bin/python retrospective.py

One Opus call (~$0.1). Reads the accumulated predictions + decision journal,
asks the model for a plain-Chinese review, and persists it to Supabase
`retrospective` (id="current"). The deployed dashboard's 月度复盘 button reads
that row — so run this once a month (or wire it to a schedule).

Requires in .env: ANTHROPIC_API_KEY + SUPABASE_SECRET_KEY (see CLAUDE.md).
"""
import os
import sys

from dotenv import load_dotenv

load_dotenv()


def main() -> None:
    sys.path.insert(0, os.path.join(os.path.dirname(__file__), "backend"))
    from data.fetcher import load_or_fetch
    from dashboard.retrospective import run_retrospective

    _, df_d = load_or_fetch()
    print("→ 生成月度复盘 (Opus ≈ $0.1)…")
    payload = run_retrospective(df_d)
    print(f"✓ 复盘已生成并写入 Supabase ({payload['period_start']} → {payload['period_end']})\n")
    print(payload["report_md"])


if __name__ == "__main__":
    main()
