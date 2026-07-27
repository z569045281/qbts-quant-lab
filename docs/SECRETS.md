# Secrets / API keys

> 读这份文件的时机:新增或改动任何 API key、排查"云端没生效/信号静默"。

## 接线四件套(新 key 必须全做)

1. 根目录 `.env`(gitignored)
2. GitHub Actions secret(同名)
3. `aws/template.yaml` 参数 + 传给对应 Lambda 的 `Environment`
4. `.github/workflows/deploy-aws.yml` 里把 secret 传进 SAM 参数

⚠️ **Both `.env` AND `.env.example` are gitignored** — 新 secret 记在**这份文件**
/ `aws/README.md`,不要只写在 `.env.example`(没人看得到)。Repo is public。

## 清单

| Key | 必需? | 用途 | 缺失时的行为 |
|---|---|---|---|
| `ANTHROPIC_API_KEY` | ✅ | 主决策(Fable 5 / Opus 4.8 回退)、Haiku 新闻/反思/地缘/自检 | 决策出不来 |
| `SUPABASE_SECRET_KEY` | ✅ | 写库(`sb_secret_…`,**write-capable,只在本地/CI**;publishable key 是安全可公开的只读 key) | publish 写不进去 |
| `ALPACA_API_KEY` / `ALPACA_SECRET_KEY` | 半 | 千元挑战 bot 下真单(paper)+ 夜盘行情 `feed=overnight` | 空 = bot 关、夜盘退回昨收 |
| `DEEPSEEK_API_KEY` | 可选 | DeepSeek 影子决策 + **SpaceX 仪表盘的唯一决策来源** | 影子全关(主决策零影响);SPCX decision=None |
| `FRED_API_KEY` | 可选 | 回填宏观日历的 **actual** 值(`backend/dashboard/fred.py`)。FF feed 只有 forecast/previous,永远没有 actual | 日历照常,actual 空 |
| `ADANOS_API_KEY` | 可选 | `sk_live_…`,零售 Reddit buzz+sentiment(Adanos 免费档 250 req/mo,adanos.org/register) | 情绪信号直接关闭,干净降级 |
| `NTFY_TOPIC` | 可选 | 所有手机推送(SMC TRIGGER / 地缘 / 游击战 / 心跳 / 周末BTC) | 不推送,功能照常算照常显示 |
| `NTFY_URL` | 可选 | 默认 `https://ntfy.sh` | — |
| `SEC_USER_AGENT` | 可选 | EDGAR 要求 email 形状的 UA 否则 403;默认已内置一个假域名 UA(像 FINRA 那样) | 用默认值 |

## 注意

- 推送标题必须保持 ASCII(HTTP header 是 latin-1),中文细节放 UTF-8 body。
- Alpaca 数据 API:`feed=sip` / `feed=boats` 都 403 需订阅,**只用 `feed=overnight`**(免费档
  即可拿实时 Blue Ocean 成交/盘口)。
- 详细的模块级用法见 [SIGNALS.md](SIGNALS.md)、[DECISION.md](DECISION.md)、[CHALLENGE.md](CHALLENGE.md)。
