"""把 data/archive.jsonl 渲染成 data/INDEX.md (按 ISO 周分组, 时间倒序).

archive.jsonl 由 fetch.py 维护, 包含所有曾经命中关键词的论文 (不论是否最终推过).
INDEX.md 是 GitHub 自动渲染的人读首页 — 用户能从一个文件浏览/搜索全部历史.
"""

import json
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
ARCHIVE_PATH = ROOT / "data" / "archive.jsonl"
INDEX_PATH = ROOT / "data" / "INDEX.md"


def parse_iso(s: str | None) -> datetime | None:
    if not s:
        return None
    try:
        return datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None


def week_slug(dt: datetime) -> str:
    iso = dt.isocalendar()
    return f"{iso.year}-W{iso.week:02d}"


def md_cell(s: str) -> str:
    return (s or "").replace("|", "\\|").replace("\n", " ")


def main() -> int:
    if not ARCHIVE_PATH.exists():
        print(f"[skip] {ARCHIVE_PATH.relative_to(ROOT)} not found, nothing to index")
        return 0
    rows: list[dict] = []
    for line in ARCHIVE_PATH.read_text(encoding="utf-8").splitlines():
        if line.strip():
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    if not rows:
        return 0

    # 按 published_ts (论文发表周) 分组, 没有就 fallback 到 first_seen_ts
    by_week: dict[str, list[dict]] = defaultdict(list)
    undated: list[dict] = []
    for r in rows:
        dt = parse_iso(r.get("published_ts")) or parse_iso(r.get("first_seen_ts"))
        if not dt:
            undated.append(r)
            continue
        by_week[week_slug(dt)].append(r)

    weeks_sorted = sorted(by_week.keys(), reverse=True)
    now = datetime.now(timezone(timedelta(hours=10)))

    out: list[str] = [
        f"# Options Radar Archive · {len(rows)} 篇\n",
        f"> 所有命中关键词的论文 (不论是否最终被推送). 按论文发表周倒序.",
        f"> 最近更新: {now.strftime('%Y-%m-%d %H:%M AEST')}",
        f"> 按 Ctrl/Cmd + F 在本页搜索. JSON 原始档案: [archive.jsonl](archive.jsonl)\n",
    ]

    for week in weeks_sorted:
        items = sorted(by_week[week], key=lambda r: r.get("published_ts") or "", reverse=True)
        out.append(f"\n## {week} · {len(items)} 篇\n")
        for r in items:
            pub = (r.get("published_ts") or "")[:10]
            title = md_cell(r.get("title") or "")
            url = r.get("url") or ""
            source = md_cell(r.get("source", ""))
            tags = " ".join(f"`{t}`" for t in r.get("tags", []))
            authors = md_cell(r.get("authors", ""))
            authors_short = authors[:80] + ("…" if len(authors) > 80 else "")
            line = f"- **{pub}** · `{source}` · [{title}]({url}) {tags}"
            if authors_short:
                line += f"\n  - _{authors_short}_"
            out.append(line)

    if undated:
        out.append(f"\n## 无日期 · {len(undated)} 篇\n")
        for r in undated:
            title = md_cell(r.get("title") or "")
            url = r.get("url") or ""
            out.append(f"- [{title}]({url})")

    INDEX_PATH.write_text("\n".join(out), encoding="utf-8")
    print(
        f"[done] {len(rows)} papers in {len(weeks_sorted)} weeks "
        f"-> {INDEX_PATH.relative_to(ROOT)}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
