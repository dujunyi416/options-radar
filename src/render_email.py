"""把 out/brief.json 渲染成 HTML 邮件 (out/email.html)，由 weekly.yml 用
dawidd6/action-send-mail step 发出。模板内联在文件里, 不额外起 templates/.
"""

import html
import json
from datetime import datetime, timezone, timedelta
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BRIEF_PATH = ROOT / "out" / "brief.json"
OUT_PATH = ROOT / "out" / "email.html"
REPORT_PATH = ROOT / "out" / "fetch_report.json"

SECTION_TITLES = {
    "must_read":      "🎯 必读",
    "long_dated":     "⭐ 长期期权",
    "methodology":    "🧮 方法 · 数值",
    "empirical":      "📊 实证 · 数据",
    "other_relevant": "📎 其他相关",
}
SECTION_ORDER = ("must_read", "long_dated", "methodology", "empirical", "other_relevant")


def format_authors(authors: str) -> str:
    if not authors:
        return ""
    parts = [a.strip() for a in authors.split(",") if a.strip()]
    if len(parts) <= 3:
        return ", ".join(parts)
    return ", ".join(parts[:3]) + " et al."


def render_item(item: dict) -> str:
    title = html.escape(item.get("headline_zh") or item.get("title") or "")
    url = html.escape(item.get("url") or "")
    eng_title = html.escape(item.get("title") or "")
    venue = html.escape(item.get("venue") or "")
    authors = html.escape(format_authors(item.get("authors", "")))
    why = html.escape(item.get("why_zh") or "")
    tags = item.get("tags") or []
    score = item.get("score")

    tag_html = ""
    if tags:
        tag_spans = []
        for t in tags[:5]:
            cls = "tag-star" if "⭐" in t else "tag"
            tag_spans.append(f'<span class="{cls}">{html.escape(t)}</span>')
        tag_html = " ".join(tag_spans)

    score_html = ""
    if score is not None:
        score_html = f' <span class="score">{score}</span>'

    meta_bits = []
    if venue:
        meta_bits.append(venue)
    if authors:
        meta_bits.append(authors)
    meta = " · ".join(meta_bits)

    return f"""
      <div class="item">
        <div class="item-title">
          <a href="{url}">{title}</a>{score_html}
        </div>
        {f'<div class="item-eng">{eng_title}</div>' if eng_title and eng_title != title else ""}
        <div class="item-meta">{meta} {tag_html}</div>
        {f'<div class="item-why">{why}</div>' if why else ""}
      </div>
    """


def render(brief: dict, week_str: str) -> str:
    overview = html.escape(brief.get("overview_zh", ""))
    degraded = brief.get("degraded", False)
    title_emoji = "⚠️" if degraded else "📚"

    sections_html = []
    for section in SECTION_ORDER:
        items = brief.get(section, [])
        if not items:
            continue
        items_html = "".join(render_item(it) for it in items)
        sections_html.append(f"""
          <h2>{SECTION_TITLES[section]}</h2>
          {items_html}
        """)

    failed = (json.loads(REPORT_PATH.read_text(encoding="utf-8"))
              if REPORT_PATH.exists() else {}).get("failed_sources", [])
    footer_html = ""
    if failed:
        footer_html = (
            f'<div class="footer-warn">⚠️ 源异常: {html.escape(", ".join(failed))}</div>'
        )

    style = """
      body { font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", "Microsoft YaHei", sans-serif;
             max-width: 720px; margin: 24px auto; padding: 0 16px; color: #222; line-height: 1.55; }
      h1 { font-size: 20px; margin: 0 0 8px; }
      h2 { font-size: 16px; border-bottom: 1px solid #ddd; padding-bottom: 4px; margin: 24px 0 12px; }
      .overview { background: #f7f7f9; padding: 12px 14px; border-radius: 6px; margin: 12px 0 24px; }
      .item { margin: 14px 0; padding: 8px 10px; border-left: 3px solid #eee; }
      .item-title { font-weight: 600; font-size: 14px; }
      .item-title a { color: #1a4480; text-decoration: none; }
      .item-title a:hover { text-decoration: underline; }
      .item-eng { font-size: 12px; color: #666; margin: 2px 0; font-style: italic; }
      .item-meta { font-size: 12px; color: #888; margin: 4px 0; }
      .item-why { font-size: 13px; color: #444; margin: 4px 0 0; padding-left: 8px; border-left: 2px solid #ccc; }
      .tag { background: #eef; color: #335; padding: 1px 6px; border-radius: 3px; font-size: 11px; margin-right: 4px; }
      .tag-star { background: #fef3c7; color: #92400e; padding: 1px 6px; border-radius: 3px; font-size: 11px; font-weight: 600; margin-right: 4px; }
      .score { font-size: 11px; color: #888; font-weight: 400; }
      .footer-warn { margin-top: 24px; padding: 8px 12px; background: #fff3cd; border-left: 3px solid #ffa500; font-size: 12px; }
    """

    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8"><style>{style}</style></head>
<body>
  <h1>{title_emoji} Options Radar · {week_str}</h1>
  {f'<div class="overview">{overview}</div>' if overview else ""}
  {''.join(sections_html)}
  {footer_html}
</body></html>
"""


def main() -> int:
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    aest = timezone(timedelta(hours=10))
    iso = datetime.now(aest).isocalendar()
    week_str = f"Week {iso.week:02d}, {iso.year}"

    if not brief or not any(brief.get(s) for s in SECTION_ORDER):
        # 空 brief 也渲染一个最小邮件, workflow 仍会发, 方便确认"本周确实没东西"
        brief = {"overview_zh": "本周无新论文命中关键词。", "must_read": []}

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(render(brief, week_str), encoding="utf-8")
    print(f"[done] -> {OUT_PATH.relative_to(ROOT)}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
