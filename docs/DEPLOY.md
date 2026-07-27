# 部署与发版

> 读这份文件的时机:准备 commit / push / 改前端可见内容 / 改后端提示词后要让云端生效。

All deploys run from `main`. Push to `main` **only when the user asks** — `main` triggers
the deploy workflows.

## 两条流水线

- **Frontend**: push touching `frontend/**` → Pages workflow auto-deploys.
- **AWS**: push touching `backend/**` / `publish.py` / `quote_pusher.py` / `aws/**` →
  "Deploy AWS jobs" auto-runs (also manual). **Backend/prompt changes need this redeploy to
  reach the cloud image** — 改了 `decision.py` 不 push,云端每日 publish 还是老提示词。

## 铁律

- End commit messages with the `Co-Authored-By: Claude Opus 4.8 <noreply@anthropic.com>` line.
- **每次 push 里只要含 `frontend/**` 的可见变更,必须同步升 `frontend/public/version.json`**
  (feature → 次版本 1.x,小修/补漏 → 1.x.y)。这是版本守卫提示用户刷新的唯一依据——
  不升版本,已打开的页面永远不知道有新构建(用户明确要求,2026-07-03)。
- **Commit small and often** so other sessions/worktrees can see your work.

## Gotchas

- **Big image push to ECR occasionally times out** in CI — just re-run "Deploy AWS jobs"。
- 新 secret 不是加到 `.env` 就完事:`.env` + GitHub Actions secret + `aws/template.yaml`
  参数 + `.github/workflows/deploy-aws.yml` 传参,四处齐全才在云端生效。清单见
  [SECRETS.md](SECRETS.md)。
- 新建 Supabase 表要有对应 `sql/*_migration.sql`,并在 [SUPABASE.md](SUPABASE.md) 标注
  「待用户跑」——代码必须在表不存在时降级而不是崩。
