"""把 out/brief.json + out/candidates.json 渲染成 data/{ISO-week}.md.

供 GitHub 上人读回看历史 (markdown 自动渲染). 与 data/*.jsonl (机读) 并行存档.
weekly.yml 在 push 后调用. 失败不会让 workflow 挂.
"""

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEF_PATH = ROOT / "out" / "brief.json"
CAND_PATH = ROOT / "out" / "candidates.json"
REPORT_PATH = ROOT / "out" / "fetch_report.json"

SECTION_TITLES = {
    "must_read":      "🎯 必读",
    "long_dated":     "⭐ 长期期权",
    "methodology":    "🧮 方法 · 数值",
    "empirical":      "📊 实证 · 数据",
    "other_relevant": "📎 其他相关",
}
SECTION_ORDER = ("must_read", "long_dated", "methodology", "empirical", "other_relevant")


def format_authors(authors: str, n: int = 3) -> str:
    if not authors:
        return ""
    parts = [a.strip() for a in authors.split(",") if a.strip()]
    return ", ".join(parts[:n]) + (" et al." if len(parts) > n else "")


def md_escape_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ").replace("\r", "")


def render_brief_item(item: dict) -> str:
    title = item.get("headline_zh") or item.get("title") or ""
    eng = item.get("title") or ""
    url = item.get("url") or ""
    venue = item.get("venue") or ""
    authors = format_authors(item.get("authors", ""))
    why = item.get("why_zh") or ""
    score = item.get("score")
    tags = item.get("tags") or []

    bits = []
    if venue:
        bits.append(f"**{venue}**")
    if authors:
        bits.append(authors)
    if tags:
        bits.append(" ".join(f"`{t}`" for t in tags[:4]))
    meta = " · ".join(bits)
    score_str = f" (score {score})" if score is not None else ""

    lines = [f"- [{title}]({url}){score_str}"]
    if eng and eng != title:
        lines.append(f"  - _{eng}_")
    if meta:
        lines.append(f"  - {meta}")
    if why:
        lines.append(f"  - └ {why}")
    return "\n".join(lines)


def main() -> int:
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8")) if BRIEF_PATH.exists() else {}
    candidates = json.loads(CAND_PATH.read_text(encoding="utf-8")) if CAND_PATH.exists() else []
    report = json.loads(REPORT_PATH.read_text(encoding="utf-8")) if REPORT_PATH.exists() else {}

    aest = timezone(timedelta(hours=10))
    now = datetime.now(aest)
    iso = now.isocalendar()
    week_slug = f"{iso.year}-W{iso.week:02d}"

    n_pushed = sum(len(brief.get(s, [])) for s in SECTION_ORDER)
    counts = report.get("counts", {})

    out: list[str] = [f"# Options Radar · Week {iso.week:02d}, {iso.year}\n"]
    out.append(
        f"> 抓取于 {now.strftime('%Y-%m-%d %H:%M AEST')} · "
        f"候选 {report.get('n_candidates', '?')} 篇 · "
        f"raw {counts.get('raw', '?')} → keyword {counts.get('after_keyword', '?')} → "
        f"推送 {n_pushed}\n"
    )

    failed = report.get("failed_sources") or []
    if failed:
        out.append(f"\n⚠️ **源异常**: {', '.join(failed)}\n")

    if brief.get("overview_zh"):
        out.append(f"\n## 概览\n\n> {brief['overview_zh']}\n")

    if brief.get("degraded"):
        out.append(f"\n> ⚠️ **DEGRADED MODE**: {brief.get('degraded_reason', 'unknown')}\n")

    for section in SECTION_ORDER:
        items = brief.get(section, [])
        if not items:
            continue
        out.append(f"\n## {SECTION_TITLES[section]}\n")
        for item in items:
            out.append(render_brief_item(item))
            out.append("")

    # 完整候选列表 (含未入选的, 满足 "想偶尔点进去看看" 的需求)
    if candidates:
        picked_ids = {
            item.get("id")
            for section in SECTION_ORDER
            for item in brief.get(section, [])
        }
        out.append(f"\n## 📚 全部候选 ({len(candidates)} 篇)\n")
        out.append("`✓` = 已入选推送; 其他是关键词过滤通过但 Claude 未推荐.\n")
        out.append("\n| 日期 | 来源 | 标题 | 标签 | 推送 |")
        out.append("|---|---|---|---|---|")
        for c in sorted(candidates, key=lambda x: x.get("published_ts") or "", reverse=True):
            pub = (c.get("published_ts") or "")[:10]
            venue = md_escape_cell(c.get("source") or "")
            title = md_escape_cell(c.get("title") or "")
            url = c.get("url") or ""
            tags = " ".join(c.get("tags", []))
            marker = "✓" if c["id"] in picked_ids else ""
            out.append(f"| {pub} | {venue} | [{title}]({url}) | {tags} | {marker} |")

    out_path = ROOT / "data" / f"{week_slug}.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text("\n".join(out), encoding="utf-8")
    print(f"[done] -> {out_path.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
