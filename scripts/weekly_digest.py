#!/usr/bin/env python3
"""Create a linked, metadata-only weekly digest from enabled reviewed feeds."""

from __future__ import annotations

import datetime as dt
import html
import json
import re
import sys
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from pathlib import Path
from urllib.parse import urlsplit, urlunsplit

ROOT = Path(__file__).resolve().parents[1]
REGISTRY = ROOT / "data" / "digest-sources.json"
UPDATES = ROOT / "updates"
MAX_ITEMS_PER_SOURCE = 30
MAX_SUMMARY_CHARS = 220
USER_AGENT = "TradeLabIndiaPublicSourceDigest/1.0 (metadata and links only)"


def plain_text(value: str) -> str:
    value = re.sub(r"<[^>]*>", " ", value or "")
    return re.sub(r"\s+", " ", html.unescape(value)).strip()


def canonical_url(url: str) -> str:
    parts = urlsplit(url.strip())
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), parts.path.rstrip("/"), parts.query, ""))


def parse_date(value: str) -> str:
    if not value:
        return "Date not supplied by source"
    try:
        from email.utils import parsedate_to_datetime

        parsed = parsedate_to_datetime(value)
        return parsed.isoformat()
    except (TypeError, ValueError, OverflowError):
        return value.strip()


def parse_feed(content: bytes, source: dict) -> list[dict]:
    root = ET.fromstring(content)
    entries = root.findall(".//item")
    if not entries:
        entries = root.findall(".//{http://www.w3.org/2005/Atom}entry")
    items = []
    for entry in entries[:MAX_ITEMS_PER_SOURCE]:
        def field(*names: str) -> str:
            for name in names:
                node = entry.find(name)
                if node is not None:
                    if name.endswith("}link"):
                        return node.attrib.get("href", "") or (node.text or "")
                    return node.text or ""
            return ""

        title = plain_text(field("title", "{http://www.w3.org/2005/Atom}title"))
        link = field("link", "{http://www.w3.org/2005/Atom}link").strip()
        guid = plain_text(field("guid", "{http://www.w3.org/2005/Atom}id"))
        if not link and guid.startswith("https://"):
            link = guid
        summary = plain_text(field("description", "summary", "{http://www.w3.org/2005/Atom}summary"))
        published = parse_date(field("pubDate", "published", "updated", "{http://www.w3.org/2005/Atom}published", "{http://www.w3.org/2005/Atom}updated"))
        if not title or not link.startswith("https://"):
            continue
        items.append({
            "title": title,
            "url": link,
            "id": guid or link,
            "summary": summary[:MAX_SUMMARY_CHARS].rstrip(),
            "published": published,
            "publisher": source["name"],
            "category": source.get("category", "Uncategorized"),
        })
    return items


def fetch(source: dict) -> list[dict]:
    request = urllib.request.Request(source["feed_url"], headers={"User-Agent": USER_AGENT, "Accept": "application/rss+xml, application/atom+xml, application/xml, text/xml"})
    with urllib.request.urlopen(request, timeout=25) as response:
        content = response.read(2_000_001)
    if len(content) > 2_000_000:
        raise ValueError("feed exceeded 2 MB limit")
    return parse_feed(content, source)


def main() -> int:
    today = dt.datetime.now(dt.timezone.utc).date().isoformat()
    failures: list[str] = []
    items: list[dict] = []

    try:
        registry = json.loads(REGISTRY.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"ERROR: could not read source registry: {exc}", file=sys.stderr)
        return 1

    if not registry.get("workflow_enabled", False):
        failures.append("The source registry workflow_enabled switch is false; no sources were fetched.")
    else:
        enabled = [source for source in registry.get("sources", []) if source.get("enabled") and source.get("feed_url")]
        if not enabled:
            failures.append("No enabled sources with feed URLs are configured.")
        for source in enabled:
            try:
                items.extend(fetch(source))
            except (OSError, urllib.error.URLError, ET.ParseError, ValueError, KeyError) as exc:
                failures.append(f"{source.get('name', source.get('id', 'Unknown source'))}: {type(exc).__name__}: {exc}")

    deduplicated: dict[str, dict] = {}
    for item in items:
        key = canonical_url(item["url"]) or item["id"]
        deduplicated.setdefault(key, item)
    items = sorted(deduplicated.values(), key=lambda item: (item["published"], item["publisher"], item["title"]), reverse=True)

    lines = [f"# Weekly public-source digest — {today}", "", "> Informational source summaries only. Not financial advice, predictions, or trading signals.", ""]
    if items:
        for item in items:
            lines.extend([
                f"## [{item['title']}]({item['url']})",
                "",
                f"- **Publisher:** {item['publisher']}",
                f"- **Published:** {item['published']}",
                f"- **Category:** {item['category']}",
                f"- **Summary:** {item['summary'] or 'No short summary supplied by the source; open the original for details.'}",
                "",
            ])
    else:
        lines.extend(["No qualifying articles were found.", ""])

    if failures:
        lines.extend(["## Fetch and review status", ""])
        for failure in failures:
            lines.append(f"- **Action needed:** {failure}")
        lines.append("")
    else:
        lines.extend(["Source fetch completed without reported errors.", ""])

    UPDATES.mkdir(parents=True, exist_ok=True)
    digest_path = UPDATES / f"{today}.md"
    digest_path.write_text("\n".join(lines), encoding="utf-8")

    prior = sorted((path for path in UPDATES.glob("????-??-??.md") if path.name != digest_path.name), reverse=True)
    index_lines = ["# Weekly digest index", "", f"- [{today}]({today}.md)"]
    index_lines.extend(f"- [{path.stem}]({path.name})" for path in prior)
    index_lines.append("")
    (UPDATES / "README.md").write_text("\n".join(index_lines), encoding="utf-8")

    print(f"Wrote {digest_path.relative_to(ROOT)} with {len(items)} unique item(s).")
    for failure in failures:
        print(f"DIGEST STATUS: {failure}", file=sys.stderr)
    return 0 if not failures else 1


if __name__ == "__main__":
    raise SystemExit(main())
