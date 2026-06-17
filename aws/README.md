# Route A — serverless decision + live quotes on AWS

Turns the two dashboard buttons into cloud jobs so they work without your
laptop:

| Job | AWS | Trigger | Cost |
|---|---|---|---|
| **出今天的决策** | Lambda `PublishFunction` (+ Function URL) | dashboard button + daily 09:00 ET | ~$0 infra + ~$0.1 Opus/run |
| **实时报价** | Lambda `QuoteFunction` | EventBridge every minute, 04:00–19:59 ET weekdays | ~$0 (free tier) |

Both run from **one container image** (`Dockerfile`) — the decision job needs the
heavy `vectorbt`/`lightgbm`/`pandas` stack, the quote job just rides along.

The frontend stays on GitHub Pages and the data store stays on Supabase — only
these two jobs move to AWS.

---

## Deploy from GitHub Actions (recommended — no local tooling)

CI runs on a clean Linux box with Docker + Python, so you don't need a working
local Docker / SAM / AWS CLI. One-time setup:

1. **Create an IAM user** for CI with programmatic access. Quick option:
   attach `AdministratorAccess` (a personal account). Tighter: CloudFormation,
   Lambda, ECR, IAM, EventBridge Scheduler, S3, and CloudWatch Logs.
2. **Add repo secrets** (Settings → Secrets and variables → Actions → Secrets):
   - `AWS_ACCESS_KEY_ID`, `AWS_SECRET_ACCESS_KEY`
   - `ANTHROPIC_API_KEY`
   - `SUPABASE_SECRET_KEY` (the `sb_secret_…` key)
   - `NEXT_PUBLIC_SUPABASE_URL` — already set for the Pages deploy; reused here as the Supabase URL.
3. **Add repo variables** (same page → Variables):
   - `AWS_REGION` (e.g. `us-east-1`) — optional, defaults to `us-east-1`.
   - `PUBLISH_ALLOW_ORIGIN` (e.g. `https://z569045281.github.io`) — optional, defaults to `*`.
4. Run **Actions → "Deploy AWS jobs (decision + quotes)" → Run workflow**.
   When it finishes, the job summary prints the **Publish Function URL** — set it
   as the `NEXT_PUBLIC_PUBLISH_URL` repo *variable* and re-run the Pages deploy.

That's it — the stack updates on every manual run. To redeploy after code
changes, just run the workflow again.

---

## Deploy locally (alternative)

### Prerequisites (one-time)

- An **AWS account** + the **AWS CLI** configured (`aws configure` with an access key).
- **Docker** running (SAM builds the image locally).
- **AWS SAM CLI** — install via the **standalone installer**, not Homebrew
  (Homebrew links it to your system Python, which can break it). See AWS docs.

## Deploy

From the repo root:

```bash
sam build -t aws/template.yaml

sam deploy --guided \
  --template aws/template.yaml \
  --stack-name qbts-jobs \
  --capabilities CAPABILITY_IAM \
  --resolve-image-repos \
  --parameter-overrides \
    AnthropicApiKey=sk-ant-... \
    SupabaseUrl=https://<project>.supabase.co \
    SupabaseSecretKey=sb_secret_... \
    AllowOrigin=https://z569045281.github.io
```

- `--resolve-image-repos` lets SAM create/manage the ECR repository for you.
- `--guided` asks a few questions the first time and saves them to
  `aws/samconfig.toml` (gitignored — it holds your secrets). After that, just
  `sam build -t aws/template.yaml && sam deploy`.
- Use the **secret** Supabase key (`sb_secret_…`), not the publishable one — the
  job writes to Supabase.

When it finishes, SAM prints **`PublishUrl`** — copy it. (Re-fetch anytime:
`aws cloudformation describe-stacks --stack-name qbts-jobs --query "Stacks[0].Outputs"`.)

## Point the dashboard button at the cloud

The "出今天的决策" button uses `NEXT_PUBLIC_PUBLISH_URL` when it's set. Add it to
the GitHub Pages build:

1. GitHub repo → Settings → Secrets and variables → Actions → **Variables** →
   New variable: `NEXT_PUBLIC_PUBLISH_URL` = the `PublishUrl` from above.
2. Re-run the **Deploy dashboard to GitHub Pages** workflow.

On the deployed site the button now POSTs to the Lambda; live quotes update on
their own (no button — EventBridge runs them). Locally (no `NEXT_PUBLIC_PUBLISH_URL`)
the dashboard keeps using your local backend exactly as before.

## Test without the UI

```bash
# decision (takes ~1–2 min; writes a dashboard_state row)
curl -X POST "<PublishUrl>"

# one quote push
aws lambda invoke --function-name <QuoteFunction name> /dev/stdout
```

---

## Important caveats

### Factors are intentionally left untouched
The cloud publish writes only the snapshot + decision + calibration. It does
**not** rewrite the `factors` table — factor mining is local, and the full
`publish.py` would wipe factors from an empty cloud leaderboard. After you mine
new factors locally, run `publish.py` locally once to push them.

### The decision journal does NOT persist in the cloud (yet)
Lambda's filesystem is read-only except `/tmp`, which is wiped on cold starts.
The journal / calibration / prediction logs are file-based, so in this setup the
"历史决策战绩 / 自省" history won't accumulate across cloud runs — the card will
read empty on the deployed site. The decision itself is generated and shown
correctly; only the *track record* is affected.

To make the journal survive in the cloud, move it from JSONL files to a Supabase
table (`decision_journal`) and have `journal.py` read/write that. That's a
focused follow-up — ask and I'll wire it.

If you'd rather keep the journal working with zero changes, run the **decision**
publish from your laptop (button or `publish.py`) and let only **live quotes**
run on AWS — they're stateless and unaffected.

### Securing the button
The Function URL is `AuthType: NONE` — public. The URL lives in the frontend JS,
so anyone who finds it can trigger a ~$0.1 Opus call. For a personal project
that's usually fine; to harden it:
- set `AllowOrigin` to your exact origin (done above) — blocks casual browser abuse,
- add a Lambda **reserved concurrency = 1** and an **AWS Budgets** alarm,
- or switch to a shared-secret header / `AWS_IAM` auth (more work).

### Schedules
- Quote schedule fires every minute 04:00–19:59 ET weekdays. Off-hours it would
  just record a "closed" row, so it's restricted to save invocations.
- Daily decision auto-runs 09:00 ET weekdays. To change or remove it, edit the
  `DailyMarketOpen` event in `template.yaml` and redeploy.

## Tear down

```bash
sam delete --stack-name qbts-jobs
```
