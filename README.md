# 每日 AI 热点情报推送系统

> 每天 20:00（北京时间）自动推送一份中文日报到飞书 / 企业微信 / Telegram / 邮件。

- 数据源：Hacker News、GitHub Trending、Product Hunt、Reddit、Google News、RSS、YouTube
- 去重、降级、缓存完整
- OpenRouter 模型总结（默认 DeepSeek，有免费额度）

---

## 目录

1. [快速开始](#快速开始)
2. [配置 .env](#配置-env)
3. [配置 Webhook](#配置推送渠道-webhook)
4. [设置 GitHub Secrets](#设置-github-secrets)
5. [部署 GitHub Actions](#部署-github-actions)
6. [修改推送时间](#修改推送时间)
7. [增加新的 AI 新闻源](#增加新的-ai-新闻源)
8. [数据来源与计划任务说明](#数据来源与计划任务说明)
9. [常见问题与排查](#常见问题与排查)
10. [本地运行](#本地运行)

---

## 快速开始

```bash
# 1. Clone
git clone <this repo>
cd ai-news-daily

# 2. Install
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# 3. Copy env & fill
cp .env.example .env

# 4. Test locally
python -m src.main

# 5. Or manually trigger from GitHub => Releases => Start Test
```

---

## 配置 .env

复制 `.env.example` 并填写必填项：

```bash
cp .env.example .env
```

### 必填

| 变量 | 用途 | 备注 |
|------|------|------|
| `FEISHU_WEBHOOK_URL` | 飞书自定义机器人 Webhook | 需要一个有权限的群 |
| `OPENROUTER_API_KEY` | OpenRouter API Key | [openrouter.ai](https://openrouter.ai) 注册即送额度 |
| `OPENROUTER_MODEL` | 模型名称 | 免费首选 `deepseek/deepseek-chat` |

### 可选

| 变量 | 用途 |
|------|------|
| `WECOM_WEBHOOK_URL` | 企业微信机器人群 Webhook |
| `TELEGRAM_BOT_TOKEN` + `TELEGRAM_CHAT_ID` | Telegram Bot |
| `EMAIL_TO` / `EMAIL_USER` / `EMAIL_PASSWORD` / `SMTP_HOST` / `SMTP_PORT` | 邮件推送 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | Reddit 增强（无也能读部分） |
| `YOUTUBE_API_KEY` | YouTube 官方数据（无则降级） |
| `RSSHUB_BASE` | RSSHub 实例地址，默认 `https://rsshub.app` |

---

## 配置推送渠道 Webhook

### 飞书自定义机器人（推荐）

1. 在飞书群聊中：「群设置」→「群机器人」→「添加机器人」→「自定义机器人」
2. 填写名称、描述 → 复制 **Webhook 地址**
3. 粘贴到 `.env` 的 `FEISHU_WEBHOOK_URL`
4. 在仓库 Secrets 中创建同名 Secret
5. 推荐机器人类型：`富文本` 或自定义 JSON。

> 如果 `FEISHU_WEBHOOK_URL` 和 `WECOM_WEBHOOK_URL` 同时存在，代码会自动选 feishu 优先。

### 企业微信机器人

1. 企业微信群：「群机器人」→「添加群机器人」→「新建」
2. 复制 `key` 查询参数
3. 填入 `.env` `WECOM_WEBHOOK_URL`

### Telegram Bot

1. 与 `@BotFather` 对话 -> `/newbot` -> 得到 token
2. 向你的 bot 发送一条消息
3. 查询 `https://api.telegram.org/bot<TOKEN>/getUpdates` 拿到 `chat.id`
4. 填入 `.env`

### 邮件推送

使用支持 SMTP 的邮箱。推荐用 `EMAIL_PASSWORD` 为 Gmail 的 "应用专用密码"（非主密码）。

---

## 设置 GitHub Secrets

在 Repo → Settings → Secrets and variables → Actions → New repository secret 里创建：

| Secret 名 | 值 |
|-----------|-----|
| `FEISHU_WEBHOOK_URL` | 飞书 Webhook |
| `OPENROUTER_API_KEY` | OpenRouter Key |
| `OPENROUTER_MODEL` | 模型标识（如 deepseek/deepseek-chat） |
| `WECOM_WEBHOOK_URL` | 可选 |
| `TELEGRAM_BOT_TOKEN` | 可选 |
| `TELEGRAM_CHAT_ID` | 可选 |
| `EMAIL_TO` / `EMAIL_USER` / `EMAIL_PASSWORD` | 可选 |
| `SMTP_HOST` / `SMTP_PORT` | 可选 |
| `REDDIT_CLIENT_ID` / `REDDIT_CLIENT_SECRET` | 可选 |
| `YOUTUBE_API_KEY` | 可选 |
| `PRODUCT_HUNT_TOKEN` | 可选 |
| `RSSHUB_BASE` | 可选，默认 `https://rsshub.app` |

---

## 部署 GitHub Actions

1. 将代码 push 到 GitHub 仓库
2. 进入 **Actions** 标签 → 左侧列表 `Daily AI News`
3. 点击右侧 **Run workflow → Run workflow**
4. 等待约 1-3 分钟运行
5. 在 Actions 页面查看日志，若有问题复制 `ai-news-daily-report` 产物查看

---

## 修改推送时间

编辑 `.github/workflows/daily-ai-news.yml` 中的 schedule cron：

| 北京时间 | UTC 时间 | Cron 表达式 |
|-----------|---------|--------------|
| 08:00 | 00:00 | `0 0 * * *` |
| **20:00** | **12:00** | **`0 12 * * *`** |
| 22:00 | 14:00 | `0 14 * * *` |

---

## 增加新的 AI 新闻源

1. 在 `src/sources.py` 中继承 `BaseCollector`，实现 `fetch(lookback_hours)` 方法。
2. 在 `COLLECTOR_CLASSES` 列表里加上新的类名。
3. 如果不希望它硬编码，也可以把类名加到 `config.yaml` 里的 `sources.enabled`，然后在 `fetch_all` 里动态读取配置。

### 示例：新增 Medium AI 热文（RSS）

```python
class MediumAICollector(BaseCollector):
    name = "Medium AI"
    weight = 1.0

    def fetch(self, lookback_hours=24):
        url = "https://medium.com/feed/tag/artificial-intelligence"
        r = requests.get(url, timeout=15)
        feed = feedparser.parse(r.content)
        # ... 解析后 append 到 results
```

---

## 数据来源与计划任务说明

### 已接入的公开数据源

- **Hacker News**: [hn.algolia.com](https://hn.algolia.com) — 无认证，含 upvote/comments 数据
- **GitHub Trending**: `rsshub.app/github/trending/...` RSS，或直接抓 GitHub 网页（含 stars）
- **Product Hunt**: `producthunt.com/feed`
- **Reddit**: `www.reddit.com/r/.../new.json` 公开 JSON，限流 60req/min，已做过滤
- **Google News**: `news.google.com/rss/search`
- **批量 RSS + RSSHub**
- **YouTube**: 公开 trending 页面抓取（Title/Url，无官方 API 时自动降级）

### 为什么做得慢？

这些数据源都是免费的、无认证或弱认证入口（RSS/公开 JSON 页面），**anti-bot 策略宽容度高**，只要我们降低请求频率，就可以稳定使用。

### 为什么建议用 GitHub Actions

1. **免费**：Ubuntu runner 每 repo 每月约 2000 分钟，超出也便宜。
2. **周期稳定**：cron 准点执行，不依赖你本地路由器。
3. **推送链路短**：Actions 直接调用各 Webhook，无需你开着电脑。
4. **日志 + 产物可稽核**：每一步的输出都在 Actions 留下审计记录。

### 计划任务逻辑

- 每天 UTC 12:00（＝ Beijing 20:00）执行一次
- 手动触发（`workflow_dispatch`）支持，可编辑 `lookback_hours`
- 运行时间通常 1~3 分钟
- 产出物（报告 + 原始 JSON）保留 7 天

---

## 常见问题与排查

### 飞书收不到消息
- 检查 Secrets 里的 `FEISHU_WEBHOOK_URL` 是否完整
- 群机器人未被关闭/隔离
- 查看 Actions 日志是否有 "Feishu push failed" 及 body 内容
- 公共网络需能访问 `open.feishu.cn`

### GitHub Actions 工作流不触发
- 确认 repo 里 `.github/workflows/daily-ai-news.yml` 已经 push
- 进入 Actions 检查 "Daily AI News" workflow 的草稿状态
- cron 表达式遵循 UTC，不是北京时间

### LLM 报错 / 报告变短
- 检查 `OPENROUTER_API_KEY` 是否有效且有余额
- OpenRouter 免费模型（deepseek/gemini-2.0-flash）偶尔限流
- 可切换到其他模型，在 `.env` 里修改 `OPENROUTER_MODEL`

### RSSHub / GitHub / Reddit 403/429
- RSSHub 公共实例可能是最高频限制。自己部署 RSSHub 并在 `RSSHUB_BASE` 配置。
- 适当降低并发，代码已做串行 fetch。
- YouTube 页面抓取不稳定，属于已知降级情况，优先用 Google News RSS 作为补充。

### 重复新闻太多
- 调小 `config.yaml > ranker > dedup_similarity_threshold` 更严格
- 增加关键词白名单

---

## 本地运行

```bash
cp .env.example .env
# 编辑 .env
python -m venv .venv
source .venv/bin/activate
pip install -r requirements.txt
python -m src.main
```

产物和原始数据在 `./data/ai-news-daily/`。

---

## 贡献

欢迎增删 Collector 或调整权重，`src/sources.py` 与 `src/ranker.py` 是核心入口。请遵守各平台 robots 政策，**禁止反爬**。

---

## 许可证

MIT
