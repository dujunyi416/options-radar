"""Stage 1: 拉 arXiv / Crossref / RePEc, 关键词预筛, 写 out/candidates.json.

3 个 adapter:
- arxiv: http://export.arxiv.org/api/query (Atom feed, feedparser 直接解析)
- crossref: https://api.crossref.org/journals/{ISSN}/works (JSON)
- repec: http://nep.repec.org/{list}/{YYYY-MM-DD} (HTML 周报, BS4 解析)

关键词预筛: 标题+摘要做 \\b词边界 匹配, exclude 优先级最高, long_dated 命中加 ⭐ tag.

去重语义 (方案 B):
- state/pushed.json 记录已推送到飞书的论文 key (由 push.py 在推送成功后写入).
- fetch.py 只读 pushed.json, 过滤掉已推过的论文, 让 Claude 在 "未推过" 池里选 top N.
- 手动触发 (WINDOW_DAYS=30) 会扩窗口召回更多 → 自然拿到 "下一档" 没推过的论文.

archive 语义:
- 所有通过关键词的论文 (不论是否最终推) 都 append 到 data/archive.jsonl,
  作为永久可搜索档案. data/INDEX.md 是它的人读首页.

HTTP 失败带指数退避重试 (5xx / 429 / 连接错误), 避免单次瞬时抖动整死一个源.
"""

import hashlib
import json
import os
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests
import yaml
from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent.parent
PUSHED_PATH = ROOT / "state" / "pushed.json"
OUT_PATH = ROOT / "out" / "candidates.json"
REPORT_PATH = ROOT / "out" / "fetch_report.json"
ARCHIVE_PATH = ROOT / "data" / "archive.jsonl"     # 全量永久档案 (命中关键词的论文)

FETCH_TIMEOUT = 30
USER_AGENT_TMPL = "options-radar/1.0 (https://github.com/dujunyi416/options-radar; mailto:{email})"


# ---------- HTTP 重试 wrapper ----------

def http_get(url: str, ua: str, *, retries: int = 3, backoff: float = 2.0) -> requests.Response:
    """轻量退避重试: 5xx/429/网络异常时重试; 其它 4xx 立即抛 (重试无意义)."""
    last_exc: Exception | None = None
    for attempt in range(retries):
        try:
            resp = requests.get(url, timeout=FETCH_TIMEOUT, headers={"User-Agent": ua})
            if resp.status_code == 429 or resp.status_code >= 500:
                raise requests.HTTPError(
                    f"{resp.status_code} {resp.reason}", response=resp
                )
            resp.raise_for_status()
            return resp
        except requests.RequestException as exc:
            last_exc = exc
            if attempt < retries - 1:
                wait = backoff ** attempt
                print(
                    f"[retry] {url[:80]} attempt {attempt + 1}/{retries} "
                    f"in {wait:.0f}s: {exc}",
                    file=sys.stderr,
                )
                time.sleep(wait)
    assert last_exc is not None
    raise last_exc


# ---------- 关键词预筛 ----------

def compile_patterns(words: list[str]) -> list[re.Pattern]:
    """词边界匹配。短语里的空格也接受连字符或多空格。"""
    pats = []
    for w in words:
        # 把空格当作 \s+ 或 -, 让 "long-dated" / "long dated" 等价
        escaped = re.escape(w).replace(r"\ ", r"[\s\-]+")
        pats.append(re.compile(rf"\b{escaped}\b", re.IGNORECASE))
    return pats


def load_keywords() -> dict:
    cfg = yaml.safe_load((ROOT / "config" / "keywords.yaml").read_text(encoding="utf-8"))
    return {
        "core": compile_patterns(cfg.get("core", [])),
        "long_dated": compile_patterns(cfg.get("long_dated", [])),
        "methodology": compile_patterns(cfg.get("methodology", [])),
        "exclude": compile_patterns(cfg.get("exclude", [])),
    }


def filter_paper(title: str, summary: str, kw: dict) -> tuple[bool, list[str]]:
    """返回 (keep, tags). exclude 命中直接丢弃; long_dated 命中打 ⭐ tag."""
    text = f"{title}\n{summary}"
    for p in kw["exclude"]:
        if p.search(text):
            return False, []
    tags = []
    has_long = any(p.search(text) for p in kw["long_dated"])
    has_core = any(p.search(text) for p in kw["core"])
    has_method = any(p.search(text) for p in kw["methodology"])
    if not (has_long or has_core or has_method):
        return False, []
    if has_long:
        tags.append("⭐long-dated")
    if has_core:
        tags.append("options")
    if has_method:
        tags.append("methodology")
    return True, tags


# ---------- 去重 ----------

def load_pushed() -> dict:
    """已推送到飞书的论文 key. 由 push.py 在推送成功后写入. fetch.py 只读不写."""
    if PUSHED_PATH.exists():
        try:
            return json.loads(PUSHED_PATH.read_text(encoding="utf-8"))
        except (json.JSONDecodeError, OSError):
            return {}
    return {}


def stable_key(doi: str | None, arxiv_id: str | None, url: str, title: str) -> str:
    """DOI > arxiv_id > sha256(url|title). DOI 大小写归一化避免 10.1111 vs 10.1111 重复."""
    if doi:
        return f"doi:{doi.lower().strip()}"
    if arxiv_id:
        return f"arxiv:{arxiv_id.strip()}"
    return "url:" + hashlib.sha256(f"{url}|{title}".encode("utf-8")).hexdigest()[:16]


# ---------- adapters ----------

def clean_text(s: str) -> str:
    if not s:
        return ""
    s = re.sub(r"<[^>]+>", " ", s)
    s = re.sub(r"\s+", " ", s).strip()
    return s


def fetch_arxiv(src: dict, ua: str, since: datetime) -> list[dict]:
    category = src["category"]
    url = (
        "http://export.arxiv.org/api/query?"
        f"search_query=cat:{quote(category)}"
        f"&sortBy=submittedDate&sortOrder=descending&max_results={src.get('cap', 50)}"
    )
    resp = http_get(url, ua)
    feed = feedparser.parse(resp.content)
    items = []
    for entry in feed.entries:
        pub = None
        for attr in ("published_parsed", "updated_parsed"):
            t = getattr(entry, attr, None)
            if t:
                pub = datetime.fromtimestamp(time.mktime(t), tz=timezone.utc)
                break
        if pub and pub < since:
            continue
        # arXiv id 在 entry.id 里, 形如 http://arxiv.org/abs/2406.12345v1
        m = re.search(r"arxiv\.org/abs/([^v\s]+)", entry.get("id", ""))
        arxiv_id = m.group(1) if m else None
        authors = ", ".join(a.get("name", "") for a in entry.get("authors", []))[:200]
        items.append({
            "title": clean_text(entry.get("title", "")),
            "summary": clean_text(entry.get("summary", ""))[:1500],
            "url": entry.get("link") or (f"https://arxiv.org/abs/{arxiv_id}" if arxiv_id else ""),
            "authors": authors,
            "venue": f"arXiv {category}",
            "published_ts": pub.isoformat() if pub else None,
            "doi": None,
            "arxiv_id": arxiv_id,
        })
    return items


def fetch_crossref(src: dict, ua: str, since: datetime) -> list[dict]:
    issn = src["issn"]
    since_str = since.strftime("%Y-%m-%d")
    url = (
        f"https://api.crossref.org/journals/{issn}/works"
        f"?filter=from-pub-date:{since_str}"
        f"&rows={src.get('cap', 10)}"
        f"&sort=published&order=desc"
    )
    resp = http_get(url, ua)
    data = resp.json()
    items = []
    for w in data.get("message", {}).get("items", []):
        title_list = w.get("title", [])
        title = clean_text(title_list[0]) if title_list else ""
        if not title:
            continue
        abstract = clean_text(w.get("abstract", ""))
        # Crossref published-print/online date 是 [[YYYY, MM, DD]] 嵌套数组
        date_parts = (
            w.get("published-online", {}).get("date-parts")
            or w.get("published-print", {}).get("date-parts")
            or w.get("issued", {}).get("date-parts")
            or [[]]
        )
        parts = date_parts[0] if date_parts else []
        pub = None
        if len(parts) >= 1:
            try:
                pub = datetime(
                    parts[0],
                    parts[1] if len(parts) > 1 else 1,
                    parts[2] if len(parts) > 2 else 1,
                    tzinfo=timezone.utc,
                )
            except (ValueError, TypeError):
                pub = None
        if pub and pub < since:
            continue
        authors = []
        for a in w.get("author", [])[:6]:
            given = a.get("given", "")
            family = a.get("family", "")
            full = f"{given} {family}".strip()
            if full:
                authors.append(full)
        doi = w.get("DOI", "")
        items.append({
            "title": title,
            "summary": abstract[:1500],
            "url": w.get("URL") or (f"https://doi.org/{doi}" if doi else ""),
            "authors": ", ".join(authors)[:200],
            "venue": src["name"],
            "published_ts": pub.isoformat() if pub else None,
            "doi": doi,
            "arxiv_id": None,
        })
    return items


_REPEC_ANCHOR_RE = re.compile(r"ideas\.repec\.org|econpapers\.repec\.org")


def _repec_abstract(anchor) -> str:
    """从 NEP 报告抽取一篇论文的摘要 — 截到下一个 paper 链接为止, 避免吞下一篇."""
    parts: list[str] = []
    total = 0
    for sib in anchor.find_all_next(limit=120):
        # 遇到下一个论文链接就停, 不把下一篇的内容当本篇 abstract
        if getattr(sib, "name", None) == "a" and _REPEC_ANCHOR_RE.search(sib.get("href", "")):
            break
        # 优先取块级元素的纯文本; 跳过没意义的导航/小标签
        if getattr(sib, "name", None) in ("p", "blockquote", "div", "dd", "dt", "li", "span"):
            t = clean_text(sib.get_text(" ", strip=True))
        elif sib.name is None:  # NavigableString
            t = clean_text(str(sib))
        else:
            continue
        if not t or len(t) < 3:
            continue
        parts.append(t)
        total += len(t)
        if total > 1000:
            break
    return clean_text(" ".join(parts))


def fetch_repec(src: dict, ua: str, since: datetime) -> list[dict]:
    """RePEc NEP 周报 URL 不固定, 试探最近 14 天里能命中的日期 (周一发布)."""
    nep_list = src["nep_list"]
    base = f"http://nep.repec.org/{nep_list}/"
    today = datetime.now(timezone.utc).date()
    html = None
    issue_date = None
    # 往回找最近一期 (按周发布, 14 天足够)
    for back in range(0, 15):
        d = today - timedelta(days=back)
        url = f"{base}{d.isoformat()}"
        try:
            r = http_get(url, ua, retries=2, backoff=1.5)
            if r.ok and "<html" in r.text.lower():
                html = r.text
                issue_date = d
                break
        except requests.RequestException:
            # 单个日期 404/失败不算源失败, 继续往回找
            continue
    if not html or issue_date is None:
        return []
    # 该期早于 since 的就跳过
    issue_dt = datetime(issue_date.year, issue_date.month, issue_date.day, tzinfo=timezone.utc)
    if issue_dt < since:
        return []

    soup = BeautifulSoup(html, "html.parser")
    items = []
    cap = src.get("cap", 20)
    seen_urls = set()
    for a in soup.find_all("a", href=_REPEC_ANCHOR_RE):
        if len(items) >= cap:
            break
        href = a.get("href", "")
        if href in seen_urls:
            continue
        title = clean_text(a.get_text())
        if len(title) < 10:        # 过滤导航/编号链接
            continue
        abstract = _repec_abstract(a)
        items.append({
            "title": title,
            "summary": abstract[:1500],
            "url": href,
            "authors": "",
            "venue": f"RePEc {nep_list} ({issue_date.isoformat()})",
            "published_ts": issue_dt.isoformat(),
            "doi": None,
            "arxiv_id": None,
        })
        seen_urls.add(href)
    return items


ADAPTERS = {
    "arxiv": fetch_arxiv,
    "crossref": fetch_crossref,
    "repec": fetch_repec,
}


# ---------- 主流程 ----------

def main() -> int:
    config = yaml.safe_load((ROOT / "config" / "sources.yaml").read_text(encoding="utf-8"))
    # env 覆盖 (用于手动触发时调整): WINDOW_DAYS=30 扩窗口召回更多
    window_days = int(os.environ.get("WINDOW_DAYS") or config.get("window_days", 7))
    max_candidates = config.get("max_candidates", 80)
    contact_email = config.get("contact_email", "anonymous@example.com")
    ua = USER_AGENT_TMPL.format(email=contact_email)

    now = datetime.now(timezone.utc)
    since = now - timedelta(days=window_days)
    pushed = load_pushed()
    kw = load_keywords()
    print(
        f"[info] window={window_days}d, pushed.json has {len(pushed)} entries "
        f"(will be excluded from candidates)",
        file=sys.stderr,
    )

    candidates: list[dict] = []           # 未推过, 给 Claude 排
    all_kw_pass: list[dict] = []          # 所有通过关键词的, 写 archive
    failed_sources: list[str] = []
    counts = {"raw": 0, "after_window": 0, "after_keyword": 0, "after_pushed_filter": 0}

    for src in config["sources"]:
        adapter = ADAPTERS.get(src["type"])
        if not adapter:
            print(f"[warn] {src['name']}: unknown type {src['type']}", file=sys.stderr)
            failed_sources.append(src["name"])
            continue
        try:
            raw_items = adapter(src, ua, since)
        except Exception as exc:  # noqa: BLE001
            print(f"[warn] {src['name']}: {exc}", file=sys.stderr)
            failed_sources.append(src["name"])
            continue
        counts["raw"] += len(raw_items)

        kept = 0
        for it in raw_items:
            counts["after_window"] += 1
            key = stable_key(it.get("doi"), it.get("arxiv_id"), it["url"], it["title"])
            keep, tags = filter_paper(it["title"], it["summary"], kw)
            if not keep:
                continue
            counts["after_keyword"] += 1
            entry = {
                "id": -1,  # 重排后再分配
                "key": key,
                "source": src["name"],
                "topic": src["topic"],
                "title": it["title"],
                "summary": it["summary"],
                "url": it["url"],
                "authors": it["authors"],
                "venue": it["venue"],
                "published_ts": it["published_ts"],
                "fetched_ts": now.isoformat(),
                "doi": it.get("doi"),
                "arxiv_id": it.get("arxiv_id"),
                "tags": tags,
            }
            # 所有通过关键词的进 archive (不论是否 pushed)
            all_kw_pass.append(entry)
            # 已推过的不进 candidates (避免重复打扰)
            if key in pushed:
                continue
            counts["after_pushed_filter"] += 1
            candidates.append(entry)
            kept += 1
        print(f"[ok] {src['name']}: {len(raw_items)} raw -> +{kept} new (not yet pushed)")

    candidates.sort(key=lambda c: c["published_ts"] or "", reverse=True)
    candidates = candidates[:max_candidates]
    for i, c in enumerate(candidates):
        c["id"] = i

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(json.dumps(candidates, ensure_ascii=False, indent=1), encoding="utf-8")
    REPORT_PATH.write_text(
        json.dumps({
            "failed_sources": failed_sources,
            "n_candidates": len(candidates),
            "total_sources": len(config["sources"]),
            "counts": counts,
            "pushed_count": len(pushed),
        }),
        encoding="utf-8",
    )

    # 永久档案: 所有命中关键词的论文 append 到 data/archive.jsonl
    existing_archive: dict[str, dict] = {}
    if ARCHIVE_PATH.exists():
        for line in ARCHIVE_PATH.read_text(encoding="utf-8").splitlines():
            if line.strip():
                try:
                    prev = json.loads(line)
                    existing_archive[prev["key"]] = prev
                except (json.JSONDecodeError, KeyError):
                    continue
    n_new = 0
    for c in all_kw_pass:
        row = {
            "key": c["key"],
            "title": c["title"],
            "source": c["source"],
            "venue": c.get("venue", ""),
            "url": c["url"],
            "doi": c.get("doi"),
            "arxiv_id": c.get("arxiv_id"),
            "authors": c.get("authors", ""),
            "published_ts": c.get("published_ts"),
            "first_seen_ts": c["fetched_ts"],
            "tags": c.get("tags", []),
            "summary": (c.get("summary") or "")[:2000],
        }
        if c["key"] in existing_archive:
            # 保留首次见到时间, 其余字段允许刷新 (tags 可能因 keyword 扩充而变)
            row["first_seen_ts"] = existing_archive[c["key"]]["first_seen_ts"]
        else:
            n_new += 1
        existing_archive[c["key"]] = row
    ARCHIVE_PATH.parent.mkdir(parents=True, exist_ok=True)
    sorted_archive = sorted(
        existing_archive.values(),
        key=lambda r: r.get("first_seen_ts") or "",
        reverse=True,
    )
    with ARCHIVE_PATH.open("w", encoding="utf-8") as f:
        for row in sorted_archive:
            f.write(json.dumps(row, ensure_ascii=False) + "\n")

    print(
        f"[done] {len(candidates)} candidates for Claude "
        f"(raw {counts['raw']} -> kw {counts['after_keyword']} -> not-pushed {counts['after_pushed_filter']}) "
        f"-> {OUT_PATH.relative_to(ROOT)}; archive: +{n_new} new -> {len(existing_archive)} total"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
