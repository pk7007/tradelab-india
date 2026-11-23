"""Personal Indian-market RSS reader. Run --help for one-shot or watch mode."""
from __future__ import annotations

import argparse
from contextlib import closing
import datetime as dt
from email.utils import parsedate_to_datetime
import hashlib
import html
import json
from pathlib import Path
import re
import sqlite3
import sys
import threading
import urllib.error
import urllib.request
from urllib.parse import urlsplit, urlunsplit, unquote_plus
import xml.etree.ElementTree as ET

from announcements import FEED as NSE_FEED, parse_feed as parse_nse
from nse_filings import filing_metadata

UTC = dt.timezone.utc
FEEDS = {
    "nse": ("NSE announcements", NSE_FEED),
    "et": ("Economic Times stocks", "https://economictimes.indiatimes.com/markets/stocks/rssfeeds/2146842.cms"),
    "google": ("Google News: RELIANCE stock OR NSE", "https://news.google.com/rss/search?q=RELIANCE+stock+OR+NSE&hl=en-IN&gl=IN&ceid=IN:en"),
}
MAX_BYTES = 3_000_000
MARKET_TERMS = ("nifty", "sensex", "bank nifty", "rbi", "repo rate", "inflation", "fii", "dii")
CATEGORIES = {
    "earnings": ("earnings", "financial results", "quarterly results", "profit", "revenue"),
    "corporate actions": ("dividend", "buyback", "stock split", "bonus", "rights issue"),
    "macro and policy": ("rbi", "repo rate", "inflation", "sebi", "monetary policy"),
    "indices and flows": ("nifty", "sensex", "fii", "dii", "bank nifty"),
}


def plain_text(value: str, limit: int) -> str:
    value = html.unescape(re.sub(r"<[^>]*>", " ", value))
    # Strip control/terminal escape characters from untrusted publisher text.
    value = "".join(c for c in value if c.isprintable() or c.isspace())
    return " ".join(value.split())[:limit]


def mentions(text: str, phrase: str) -> bool:
    return bool(re.search(r"(?<!\w)" + re.escape(phrase.casefold()) + r"(?!\w)", text.casefold()))


def canonical_url(url):
    parts = urlsplit(url)
    query = '&'.join(field for field in parts.query.split('&')
                     if field and not unquote_plus(field.partition('=')[0]).casefold().startswith('utm_'))
    return urlunsplit((parts.scheme, parts.netloc.lower(), parts.path, query, ''))


def retry_delay(exc, now):
    if not isinstance(exc, urllib.error.HTTPError) or exc.code not in (429, 503):
        return None
    value = (exc.headers or {}).get('Retry-After', '').strip()
    if value.isascii() and value.isdecimal() and len(value) <= 10:
        return int(value)
    try:
        when = parsedate_to_datetime(value)
        return max(0, int((when-now).total_seconds())+1)
    except (ValueError, TypeError, OverflowError):
        return None


def parse_et(raw: bytes, received: dt.datetime) -> list[dict]:
    return parse_editorial(raw, received, "economictimes.indiatimes.com")


def parse_google(raw: bytes, received: dt.datetime) -> list[dict]:
    return parse_editorial(raw, received, "news.google.com", include_publisher=True)


def rss_channel(raw: bytes):
    if len(raw) > MAX_BYTES or b"\x00" in raw:
        raise ValueError("Unsupported or oversized RSS feed.")
    xml = raw.decode("utf-8-sig")
    if "<!DOCTYPE" in xml.upper() or "<!ENTITY" in xml.upper():
        raise ValueError("Unsupported RSS declaration.")
    root = ET.fromstring(xml)  # nosec B314
    if root.tag != "rss" or root.find("channel") is None:
        raise ValueError("Expected RSS channel.")
    return root


def parse_editorial(raw: bytes, received: dt.datetime, hostname: str,
                    include_publisher: bool = False) -> list[dict]:
    root = rss_channel(raw)
    rows = []
    for node in root.findall("./channel/item")[:1000]:
        title = plain_text(node.findtext("title") or "", 500)
        url = (node.findtext("link") or "").strip()
        try:
            link = urlsplit(url)
            if (link.scheme != "https" or link.hostname != hostname
                    or link.username is not None or link.password is not None
                    or link.port not in (None, 443) or any(not c.isprintable() for c in url)):
                continue
            published = parsedate_to_datetime(node.findtext("pubDate") or "")
            if published.tzinfo is None or published > received:
                continue
        except (ValueError, TypeError, OverflowError):
            continue
        if title:
            rows.append(dict(title=title, description=plain_text(node.findtext("description") or "", 2000),
                             url=url, publishedAt=published.astimezone(UTC).isoformat()))
            if include_publisher:
                rows[-1]["publisher"] = plain_text(node.findtext("source") or "Unknown publisher", 200)
    return rows


class NoRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        raise ValueError("RSS source redirected; verify its configured address.")


def fetch_feed(url: str) -> bytes:
    request = urllib.request.Request(url, headers={
        "User-Agent": "TradeLabIndia/1.0 personal RSS reader",
        "Accept": "application/rss+xml,application/xml,text/xml",
    })
    with urllib.request.build_opener(NoRedirect()).open(request, timeout=15) as response:
        raw = response.read(MAX_BYTES + 1)
    if len(raw) > MAX_BYTES:
        raise ValueError("Oversized RSS feed.")
    return raw


class NewsAgent:
    """Poll independent sources; persist only identity hashes and receipt times."""

    def __init__(self, state: Path, sources=("nse", "et", "google"), watchlist=(), include_market=False,
                 max_age_hours=24, fetch=fetch_feed, clock=lambda: dt.datetime.now(UTC)):
        if not sources or any(source not in FEEDS for source in sources):
            raise ValueError("Choose sources from nse,et,google.")
        if not 1 <= max_age_hours <= 168:
            raise ValueError("News age must be between 1 and 168 hours.")
        self.sources = tuple(dict.fromkeys(sources))
        self.watchlist = tuple(dict.fromkeys(term.strip().casefold() for term in watchlist if term.strip()))
        self.include_market = include_market
        self.max_age = dt.timedelta(hours=max_age_hours)
        self.fetch = fetch
        self.clock = clock
        self.state = Path(state)
        self.state.parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.state)) as db, db:
            db.execute('BEGIN IMMEDIATE')
            db.execute("""CREATE TABLE IF NOT EXISTS news_seen (
                identity TEXT PRIMARY KEY, fingerprint TEXT NOT NULL,
                first_seen TEXT NOT NULL, last_seen TEXT NOT NULL)""")
            columns = {row[1] for row in db.execute('PRAGMA table_info(news_seen)')}
            if 'revision_seen' not in columns:
                db.execute('ALTER TABLE news_seen ADD COLUMN revision_seen TEXT')

    def poll_once(self, sources=None) -> dict:
        now = self.clock().astimezone(UTC)
        output, statuses, current = [], [], []
        selected = self.sources if sources is None else tuple(dict.fromkeys(sources))
        if not selected or not set(selected).issubset(self.sources):
            raise ValueError('Choose at least one configured source.')
        for source in selected:
            name, url = FEEDS[source]
            try:
                raw = self.fetch(url)
                # Receipt time follows the network read, not the beginning of a slow poll.
                received = self.clock().astimezone(UTC)
                if source == "nse":
                    # The shared parser accepts empty RSS roots; require a real channel here.
                    rss_channel(raw)
                parsers = {"nse": parse_nse, "et": parse_et, "google": parse_google}
                rows = parsers[source](raw, received)
            except (OSError, ValueError, ET.ParseError, urllib.error.URLError) as exc:
                statuses.append(dict(source=source, name=name, status="unavailable", stale=True,
                                     checkedAt=self.clock().isoformat(), error=type(exc).__name__,
                                     retryAfterSeconds=retry_delay(exc,self.clock())))
                continue
            relevant = 0
            with closing(sqlite3.connect(self.state)) as db, db:
                for row in rows:
                    published = dt.datetime.fromisoformat(row["publishedAt"])
                    if received - published > self.max_age:
                        continue
                    title = plain_text(row["title"], 500)
                    summary = plain_text(row.get("description", ""), 2000)
                    text = title + " " + summary
                    matched = [term for term in self.watchlist if mentions(text, term)]
                    market_match = any(mentions(text, term) for term in MARKET_TERMS)
                    if self.watchlist and not matched and not (self.include_market and market_match):
                        continue
                    relevant += 1
                    # Preserve established article IDs and revision history across upgrades.
                    identity = hashlib.sha256((source + "|" + row["url"]).encode()).hexdigest()
                    signature = [title, summary, published.astimezone(UTC).isoformat()]
                    if "publisher" in row:
                        signature.append(row["publisher"])
                    if row.get("filingLinks"):
                        signature.append(row["filingLinks"])
                    fingerprint = hashlib.sha256(json.dumps(
                        signature, ensure_ascii=True).encode()).hexdigest()
                    previous = db.execute("SELECT fingerprint, first_seen, revision_seen FROM news_seen WHERE identity=?",
                                          (identity,)).fetchone()
                    first_seen = previous[1] if previous else received.isoformat()
                    unchanged = previous is not None and previous[0] == fingerprint
                    revision_seen = previous[2] if unchanged and previous[2] else received.isoformat()
                    db.execute("INSERT OR REPLACE INTO news_seen(identity,fingerprint,first_seen,last_seen,revision_seen) VALUES (?, ?, ?, ?, ?)",
                               (identity, fingerprint, first_seen, received.isoformat(), revision_seen))
                    item = dict(id=identity, source=source, sourceName=name,
                                       publisher=row.get("publisher", name),
                                       title=title, summary=summary, url=row["url"],
                                       publishedAt=published.astimezone(UTC).isoformat(),
                                       firstSeenAt=first_seen, receivedAt=received.isoformat(), availableAt=revision_seen,
                                       change="unchanged" if unchanged else "updated" if previous else "new", textMatches=matched,
                                       categories=[category for category, terms in CATEGORIES.items()
                                                   if any(mentions(text, term) for term in terms)] or ["other"],
                                       executionAllowed=False)
                    if source == "nse":
                        item["filings"] = filing_metadata(row.get("filingLinks", []),
                            summary, item["publishedAt"], revision_seen)
                    headline = title.casefold()
                    if source == "google" and headline.endswith(" - "+item["publisher"].casefold()):
                        headline = headline[:-(3+len(item["publisher"]))]
                    # Exchange titles can consist solely of the issuer name.
                    # Include its disclosure text to avoid merging unrelated filings.
                    subject = headline + (" "+summary.casefold() if source == "nse" else "")
                    item.update(storyKey=hashlib.sha256(json.dumps(
                        [published.date().isoformat(), " ".join(subject.split())]).encode()).hexdigest(),
                        canonicalUrl=canonical_url(row["url"]),sourceIds=[identity],
                        evidenceType="exchange disclosure" if source=="nse" else "editorial coverage",
                        status="research_only",classificationVersion="rss-keywords-v1")
                    current.append(item)
                    if not previous or previous[0] != fingerprint:
                        output.append(item)
                # Bound the identity-only cache; no publisher text is written to disk.
                db.execute("DELETE FROM news_seen WHERE last_seen < ?",
                           ((received - dt.timedelta(days=30)).isoformat(),))
            statuses.append(dict(source=source, name=name, status="fetched", stale=False,
                                 checkedAt=received.isoformat(), parsedItems=len(rows), relevantItems=relevant))
        output.sort(key=lambda row: row["publishedAt"], reverse=True)
        healthy = sum(source["status"] == "fetched" for source in statuses)
        return dict(checkedAt=now.isoformat(), status="fetched" if healthy == len(statuses)
                    else "partial" if healthy else "unavailable", sources=statuses, items=output, currentItems=current,
                    executionAllowed=False)


def main(argv=None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--watch", action="store_true", help="Poll continuously until Ctrl+C.")
    mode.add_argument("--once", action="store_true", help="Check once (default).")
    parser.add_argument("--sources", default="nse,et,google", help="Comma-separated nse,et,google.")
    parser.add_argument("--watchlist", default="", help="Comma-separated company names, symbols or index phrases.")
    parser.add_argument("--include-market", action="store_true", help="Include index/macro keyword matches with a watchlist.")
    parser.add_argument("--interval", type=int, default=30, help="Seconds between polls; minimum 30.")
    parser.add_argument("--max-age-hours", type=int, default=24, help="Publication age limit, 1-168 hours.")
    parser.add_argument("--state", type=Path, default=Path(__file__).resolve().parent / "data/private/news-agent.sqlite")
    parser.add_argument("--json", action="store_true", help="Emit one JSON object per poll.")
    args = parser.parse_args(argv)
    if args.interval < 30:
        parser.error("Use an interval of at least 30 seconds.")
    try:
        agent = NewsAgent(args.state, sources=tuple(part.strip() for part in args.sources.split(",")),
                          watchlist=args.watchlist.split(","), include_market=args.include_market,
                          max_age_hours=args.max_age_hours)
    except ValueError as exc:
        parser.error(str(exc))
    if hasattr(sys.stdout, "reconfigure"):
        sys.stdout.reconfigure(encoding="utf-8")
    stop = threading.Event()
    try:
        while True:
            result = agent.poll_once()
            if args.json:
                print(json.dumps(result, ensure_ascii=True), flush=True)
            else:
                print(f"\n{result['checkedAt']} | {result['status']} | {len(result['items'])} new/changed items")
                for source in result["sources"]:
                    print(f"  {source['name']}: {source['status']}" +
                          (f" ({source['error']})" if source.get("error") else ""))
                for item in result["items"]:
                    attribution = item['sourceName']
                    if item['publisher'] != attribution:
                        attribution += " / " + item['publisher']
                    print(f"\n[{attribution} / {item['change']}] {item['title']}\n"
                          f"  Published: {item['publishedAt']} | First seen: {item['firstSeenAt']}\n"
                          f"  {item['summary']}\n  {item['url']}")
                sys.stdout.flush()
            if not args.watch:
                return 0 if result["status"] == "fetched" else 1
            stop.wait(args.interval)
    except KeyboardInterrupt:
        return 0


if __name__ == "__main__":
    raise SystemExit(main())
