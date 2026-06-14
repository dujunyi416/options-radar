"""Stage 3: 推送 out/brief.json 到飞书. Gmail 走 GitHub Actions 的 send-mail step.

只配了一个渠道; 失败时 weekly.yml 的 alert step 会兜底.
"""

import json
import os
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path

import requests

ROOT = Path(__file__).resolve().parent.parent
BRIEF_PATH = ROOT / "out" / "brief.json"
REPORT_PATH = ROOT / "out" / "fetch_report.json"

SECTION_TITLES = {
    "must_read":      "🎯 必读",
    "long_dated":     "⭐ 长期期权",
    "methodology":    "🧮 方法 · 数值",
    "empirical":      "📊 实证 · 数据",
    "other_relevant": "📎 其他相关",
}
SECTION_ORDER = ("must_read", "long_dated", "methodology", "empirical", "other_relevant")


def env(name: str) -> str:
    """读 env 并清洗 BOM (PowerShell `gh secret set` 管道会偷偷加 U+FEFF)."""
    return os.environ.get(name, "").strip().lstrip("﻿").strip()


def _read_report() -> dict:
    if not REPORT_PATH.exists():
        return {}
    try:
        return json.loads(REPORT_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {}


def health_footer() -> str:
    failed = _read_report().get("failed_sources", [])
    if not failed:
        return ""
    return f"⚠️ 源异常: {', '.join(failed)}"


def detect_outage_brief() -> dict | None:
    """0 候选 + ≥50% 源失败 → 视为全网瘫痪, 强行推一条告警 brief."""
    report = _read_report()
    n_candidates = report.get("n_candidates", -1)
    failed = report.get("failed_sources", [])
    total = report.get("total_sources", 0)
    if n_candidates != 0 or total == 0 or len(failed) < total * 0.5:
        return None
    sample = ", ".join(failed[:5]) + ("…" if len(failed) > 5 else "")
    return {
        "degraded": True,
        "overview_zh": (
            f"⚠️ 本周抓取全面失败: 0 候选, 失败源 {len(failed)}/{total} 个 "
            f"({sample})。可能是 runner 网络异常或多源同时腐烂, 去 Actions 看 fetch 日志。"
        ),
        "must_read": [],
        "long_dated": [],
        "methodology": [],
        "empirical": [],
        "other_relevant": [],
    }


def format_authors(authors: str) -> str:
    if not authors:
        return ""
    # 超过 3 个作者只显示前 3 + et al.
    parts = [a.strip() for a in authors.split(",") if a.strip()]
    if len(parts) <= 3:
        return ", ".join(parts)
    return ", ".join(parts[:3]) + " et al."


def push_feishu(brief: dict, date_str: str) -> bool | None:
    """返回 True=推送成功, False=推送失败, None=未配置 (静默跳过)."""
    webhook = env("FEISHU_WEBHOOK_URL")
    if not webhook:
        print("[info] FEISHU_WEBHOOK_URL not set, skipping feishu")
        return None
    content = []
    if brief.get("overview_zh"):
        content.append([{"tag": "text", "text": brief["overview_zh"]}])
        content.append([{"tag": "text", "text": ""}])
    for section in SECTION_ORDER:
        items = brief.get(section, [])
        if not items:
            continue
        content.append([{"tag": "text", "text": SECTION_TITLES[section]}])
        for item in items:
            title = item.get("headline_zh") or item.get("title") or ""
            venue = item.get("venue", "")
            tag_str = " ".join(item.get("tags", [])[:4])
            head_line = [{"tag": "a", "text": f"• {title}", "href": item.get("url", "")}]
            content.append(head_line)
            meta_bits = []
            if venue:
                meta_bits.append(venue)
            authors = format_authors(item.get("authors", ""))
            if authors:
                meta_bits.append(authors)
            if tag_str:
                meta_bits.append(tag_str)
            if meta_bits:
                content.append([{"tag": "text", "text": "  " + " · ".join(meta_bits)}])
            if item.get("why_zh"):
                content.append([{"tag": "text", "text": f"  └ {item['why_zh']}"}])
        content.append([{"tag": "text", "text": ""}])
    footer = health_footer()
    if footer:
        content.append([{"tag": "text", "text": footer}])

    keyword = env("FEISHU_KEYWORD")
    if keyword:
        content.append([{"tag": "text", "text": f"#{keyword}"}])

    title_emoji = "⚠️" if brief.get("degraded") else "📚"
    resp = requests.post(
        webhook,
        json={
            "msg_type": "post",
            "content": {
                "post": {
                    "zh_cn": {
                        "title": f"{title_emoji} Options Radar · {date_str}",
                        "content": content,
                    }
                }
            },
        },
        timeout=30,
    )
    body = {}
    try:
        body = resp.json()
    except ValueError:
        pass
    if not resp.ok or body.get("code", -1) != 0:
        print(f"[error] feishu: {resp.status_code} {resp.text[:500]}", file=sys.stderr)
        return False
    print("[ok] pushed to Feishu")
    return True


def main() -> int:
    brief = json.loads(BRIEF_PATH.read_text(encoding="utf-8"))
    is_empty = not brief or not any(brief.get(s) for s in SECTION_ORDER)
    if is_empty:
        outage = detect_outage_brief()
        if outage:
            print("[warn] all sources down — pushing outage alert", file=sys.stderr)
            brief = outage
            is_empty = False
    if is_empty:
        print("[done] empty brief, nothing to push")
        return 0

    aest = timezone(timedelta(hours=10))
    iso = datetime.now(aest).isocalendar()
    date_str = f"Week {iso.week:02d}, {iso.year}"

    try:
        result = push_feishu(brief, date_str)
    except Exception as exc:  # noqa: BLE001
        print(f"[error] push_feishu: {exc}", file=sys.stderr)
        result = False
    # 三态: True=成功(0), False=配置了但推送失败(1, 触发 workflow alert),
    #       None=未配置(0, 静默跳过 — 邮件渠道仍会发)
    if result is False:
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
