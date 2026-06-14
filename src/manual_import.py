"""手动补漏: 把 arXiv ID / DOI / URL 列表 enrich 成 markdown, 方便复制到 Zotero.

不进 weekly cron, 不污染 state/seen.json. 输出到 stdout + out/manual_import.md.

用法:
    python src/manual_import.py 2606.12345 10.1080/14697688.2026.2667872
    python src/manual_import.py --file manual_import.txt
"""

import argparse
import re
import sys
import time
from pathlib import Path
from urllib.parse import quote

import feedparser
import requests

ROOT = Path(__file__).resolve().parent.parent
UA = "options-radar-manual/1.0 (mailto:dujunyi416@gmail.com)"
TIMEOUT = 30


def parse_id(s: str) -> tuple[str, str]:
    """识别输入是 arXiv ID / DOI / 普通 URL. 返回 (type, normalized_id)."""
    s = s.strip()
    if not s:
        return ("", "")
    # arXiv 新格式 YYMM.NNNNN
    if re.match(r"^\d{4}\.\d{4,5}(v\d+)?$", s):
        return ("arxiv", s.split("v")[0])
    m = re.search(r"arxiv\.org/abs/([^v?\s]+)", s)
    if m:
        return ("arxiv", m.group(1).split("v")[0])
    if "doi.org/" in s:
        return ("doi", s.split("doi.org/")[-1])
    if s.startswith("10."):
        return ("doi", s)
    if s.startswith("http"):
        return ("url", s)
    return ("url", s)


def fetch_arxiv(arxiv_id: str) -> dict | None:
    url = f"http://export.arxiv.org/api/query?id_list={quote(arxiv_id)}"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException as exc:
        print(f"[err] arxiv {arxiv_id}: {exc}", file=sys.stderr)
        return None
    if not r.ok:
        return None
    feed = feedparser.parse(r.content)
    if not feed.entries:
        return None
    e = feed.entries[0]
    return {
        "title": re.sub(r"\s+", " ", e.get("title") or "").strip(),
        "authors": ", ".join(a.get("name", "") for a in e.get("authors", []))[:200],
        "summary": re.sub(r"\s+", " ", e.get("summary") or "").strip(),
        "url": f"https://arxiv.org/abs/{arxiv_id}",
        "venue": "arXiv",
    }


def fetch_doi(doi: str) -> dict | None:
    url = f"https://api.crossref.org/works/{quote(doi, safe='/')}"
    try:
        r = requests.get(url, timeout=TIMEOUT, headers={"User-Agent": UA})
    except requests.RequestException as exc:
        print(f"[err] doi {doi}: {exc}", file=sys.stderr)
        return None
    if not r.ok:
        return None
    m = r.json().get("message", {})
    title_list = m.get("title") or []
    abstract = re.sub(r"<[^>]+>", " ", m.get("abstract", "") or "")
    abstract = re.sub(r"\s+", " ", abstract).strip()
    return {
        "title": (title_list[0] if title_list else "").strip(),
        "authors": ", ".join(
            f"{a.get('given', '')} {a.get('family', '')}".strip()
            for a in (m.get("author") or [])[:6]
        )[:200],
        "summary": abstract,
        "url": m.get("URL") or f"https://doi.org/{doi}",
        "venue": ((m.get("container-title") or [""])[0] or "").strip(),
    }


def to_markdown(meta: dict) -> str:
    summary = meta["summary"]
    if len(summary) > 700:
        summary = summary[:700].rsplit(" ", 1)[0] + "…"
    return (
        f"### [{meta['title']}]({meta['url']})\n\n"
        f"**{meta['venue']}** · {meta['authors']}\n\n"
        f"> {summary or '(no abstract)'}\n"
    )


def main(argv=None) -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("ids", nargs="*", help="arXiv ID, DOI, 或 URL")
    p.add_argument("--file", help="一行一个 ID 的文件 (# 开头是注释)")
    args = p.parse_args(argv)

    ids: list[str] = list(args.ids)
    if args.file:
        for line in Path(args.file).read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if line and not line.startswith("#"):
                ids.append(line)
    if not ids:
        p.error("no ids provided. give them on cmdline or via --file.")

    out_path = ROOT / "out" / "manual_import.md"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    blocks: list[str] = [f"# Manual Import ({len(ids)} items)\n"]
    n_ok = 0
    for raw in ids:
        kind, ident = parse_id(raw)
        if kind == "arxiv":
            meta = fetch_arxiv(ident)
        elif kind == "doi":
            meta = fetch_doi(ident)
        else:
            print(f"[skip] {raw}: no resolver for type={kind!r}", file=sys.stderr)
            continue
        if not meta:
            print(f"[skip] {raw}: lookup returned nothing", file=sys.stderr)
            continue
        block = to_markdown(meta)
        print(block)
        blocks.append(block)
        n_ok += 1
        time.sleep(1)  # 善待 API
    out_path.write_text("\n".join(blocks), encoding="utf-8")
    print(f"\n[done] {n_ok}/{len(ids)} -> {out_path.relative_to(ROOT)}", file=sys.stderr)
    return 0 if n_ok > 0 else 1


if __name__ == "__main__":
    raise SystemExit(main())
