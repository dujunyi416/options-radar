# 📚 Options Radar

**一个开源的、agenda 感知的期权定价论文周报筛选引擎。** 每周一早上从 arXiv (q-fin.PR / MF / CP / RM)、Crossref 顶级金融期刊 (JF / JFE / RFS / Math Finance / Finance and Stochastics / Quantitative Finance / Journal of Derivatives / Review of Derivatives Research 等)、RePEc NEP 周报 (fmk / rmg) 抓取过去 7 天的新论文 → 用关键词 (options/long-dated/methodology) 预筛 → 一次 LLM 调用按"这会不会推进*你的*研究方向"排序 → 推送一份分 section 的周报到飞书和 Gmail：

- **🎯 必读** — 与 agenda 高度相关、放下别的也要读的 2-4 篇
- **⭐ 长期期权** — 命中 LEAPS / long-dated / 嵌入期权 / 养老金等专项关键词的论文 (核心方向)
- **🧮 方法 · 数值** — 神经网络定价 / rough vol / PDE / MC 方法
- **📊 实证 · 数据** — 隐含波动率曲面 / 流动性 / 期限结构等数据驱动研究
- **📎 其他相关** — 兜底篮子

通用论文 alert 满大街都是; 这个工具的全部价值在于排序函数里注入了**你自己的 research agenda**——而那份 agenda (`AGENDA` secret) 永远不进仓库。

## 它不是什么

- 不是实时告警 (一周一次, GitHub Actions cron)
- 不是文献综述工具 (只看新论文, 不做 retrospective)
- 不是多用户 SaaS——**fork 即订阅**: fork 本仓库, 填上自己的 secrets, 就得到自己的个性化筛选器

## 架构

```
GitHub Actions (每周日 22:13 UTC = 布里斯班周一 08:13)
  └─ src/fetch.py        arXiv API + Crossref + RePEc → 关键词预筛 → out/candidates.json
  └─ src/brief.py        GitHub Models 优先, Claude CLI fallback (注入 AGENDA secret) → out/brief.json
  │                      同时把通用元数据写入 data/YYYY-Www.jsonl (公开数据集)
  └─ src/push.py         推送飞书
  └─ src/render_email.py brief.json → HTML email
  └─ dawidd6/action-send-mail → 发到 Gmail
  └─ commit data/ + state/ 回仓库
```

`out/` (含个性化的 why_zh) 被 gitignore; 入库的只有通用元数据。

## 部署 (fork 后 5 分钟)

1. **Fork 本仓库** (public fork 即可, Actions 免费)
2. 在 repo Settings → Secrets and variables → Actions 添加:

   | Secret | 必需 | 怎么拿 |
   |---|---|---|
   | `CLAUDE_CODE_OAUTH_TOKEN` | 可选 (fallback) | 本机装 Claude Code 后 `claude setup-token` (Pro/Max 订阅额度). CI 默认走 GitHub Models (`GITHUB_TOKEN` 自动注入, workflow 已声明 `models: read`) |
   | `AGENDA` | ✅ | 照 [agenda.example.md](agenda.example.md) 写自己的研究方向, 整个文件内容贴进去 |
   | `FEISHU_WEBHOOK_URL` | ✅ | 飞书群 → 设置 → 群机器人 → 添加自定义机器人 |
   | `FEISHU_KEYWORD` | 可选 | 若机器人开了"自定义关键词"安全策略, 填关键词 (建议 `options` 或 `radar`) |
   | `SMTP_USER` | ✅ | Gmail 地址 (例如 `dujunyi416@gmail.com`) |
   | `SMTP_PASS` | ✅ | Gmail [应用专用密码](https://myaccount.google.com/apppasswords) (不是登录密码; 需先启用两步验证) |

3. Actions 页签手动跑一次 `weekly-radar` 验证, 之后每周一自动

任何一步失败 (token 过期、源全挂、推送被限流) 都会向飞书 + 邮件推一条**失败告警**带运行日志链接——周报工具最危险的死法是静默死亡, 这里把它焊死了。简报末尾还会自动带"⚠️ 源异常"脚注。

## 保持 agenda 新鲜 (重要)

排序质量 = agenda 新鲜度。研究方向变了就在本地改 `agenda.md` (已 gitignore), 然后一条命令同步:

```powershell
gh secret set AGENDA -b (Get-Content agenda.md -Raw)
```

> ⚠️ Windows 用户设置所有 secret 都请用 `-b` 参数传值。PowerShell 管道 (`"..." | gh secret set`) 会给值偷偷加上 U+FEFF (BOM), 导致运行时 `InvalidSchema: No connection adapters` 这类诡异错误。代码层已对凭证做了 BOM 清洗兜底, 但源头干净更好。

## 本地调试

```powershell
pip install -r requirements.txt

# Stage 1: 抓取 + 关键词预筛
python src/fetch.py
# → 检查 out/candidates.json 篇数 (预期 20-60 篇)

# Stage 2: LLM 排序 (CI 同逻辑: GitHub Models 优先, 本机无 token 时走 claude CLI)
$env:AGENDA = Get-Content agenda.md -Raw
# 可选: $env:GITHUB_TOKEN = gh auth token   # 本地也想走 GitHub Models 时
python src/brief.py
# → 检查 out/brief.json sections 是否合理, ⭐long-dated tag 是否命中长期期权论文

# Stage 3: 推送 + 渲染邮件
$env:FEISHU_WEBHOOK_URL = "..."
python src/push.py
python src/render_email.py
# → 用浏览器打开 out/email.html 看排版
```

## 调整口味

- **加/减来源**: 编辑 [config/sources.yaml](config/sources.yaml) (添 ISSN 就能新增期刊, 死源只会告警不会让运行失败)
- **改关键词**: 编辑 [config/keywords.yaml](config/keywords.yaml) — 四个桶: `core` / `long_dated` (会加 ⭐ tag) / `methodology` / `exclude` (优先级最高)
- **改排序哲学**: prompt 在 [src/brief.py](src/brief.py) 顶部 `PROMPT_TEMPLATE`
- **改推送时间**: [.github/workflows/weekly.yml](.github/workflows/weekly.yml) 的 cron

## 数据来源说明

| 来源 | API | 频率 | 备注 |
|---|---|---|---|
| arXiv | `export.arxiv.org/api/query` | 实时 | 最快, 但是 preprint, 注意质量 |
| Crossref | `api.crossref.org/journals/{ISSN}/works` | 实时, 滞后于实际发表数周 | 正式发表论文 |
| RePEc NEP | `nep.repec.org/{list}/{date}` | 周报, 周一发布 | working paper 综合, 涵盖 SSRN 大部分 |

> SSRN 自己反爬严格, 未直接接入. 大部分 SSRN 上的工作论文会同步到 RePEc/IDEAS, 已通过 NEP 报告间接覆盖。如运行 1-2 个月后发现重要遗漏, 可在 `fetch.py` 加 SSRN eJournal RSS adapter.

## License

MIT
