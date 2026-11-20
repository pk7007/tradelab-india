"""Read-only five-minute CTS audit; outputs aggregates, never candle prices.

The bundled calendar is a bounded, source-linked 2023-2026 exception manifest,
not a complete exchange holiday calendar. CAS membership must be supplied by
the caller: the 2026 change does not apply to every NSE cash security.
"""
import argparse
from collections import Counter, defaultdict
import csv
import datetime as dt
import hashlib
import json
import math
from pathlib import Path

VERSION = "1.1"
IST = dt.timezone(dt.timedelta(hours=5, minutes=30))
ARCHIVE = "https://nsearchives.nseindia.com/content/circulars/"
CAS_SOURCE = "https://www.nseindia.in/static/products-services/closing-auction-session"
CAS_LAUNCH_SOURCE = "https://docs.publicnow.com/viewDoc?filename=37163%5CEXT%5C68692DBC6C77BAFC0C0F9FCFF1864437BCD7319B_34A5336001924B1ACA6AF27BB2DA59625922AE75.PDF"
SPECIAL_SESSIONS = {
    "2023-11-12": ("muhurat", [("18:15", "19:15")], "CMTR59124.pdf"),
    "2024-01-20": ("weekend_full", [("09:15", "15:30")], "MSD60340.pdf"),
    "2024-03-02": ("split_dr", [("09:15", "10:00"), ("11:30", "12:30")], "MSD60677.pdf"),
    "2024-05-18": ("split_dr", [("09:15", "10:00"), ("11:30", "12:30")], "MSD61893.pdf"),
    "2024-11-01": ("muhurat", [("18:00", "19:00")], "CMTR64628.pdf"),
    "2025-02-01": ("weekend_full", [("09:15", "15:30")], "MSD66381.pdf"),
    "2025-10-21": ("muhurat", [("13:45", "14:45")], "CMTR70319.pdf"),
    "2026-02-01": ("weekend_full", [("09:15", "15:30")], "CMTR72349.pdf"),
    "2026-11-08": ("muhurat", [("14:20", "15:30")], "CMTR76941.pdf"),
}


def session_spec(day, cas_effective=None):
    """Return exclusive-end continuous-session windows, kind and evidence URL."""
    if cas_effective is not None:
        dt.date.fromisoformat(cas_effective)
    cas = cas_effective is not None and day >= cas_effective
    if day in SPECIAL_SESSIONS:
        kind, windows, source = SPECIAL_SESSIONS[day]
        if day == "2026-11-08" and cas:
            windows = [("14:20", "15:15")]
        return windows, kind, ARCHIVE + source
    if dt.date.fromisoformat(day).weekday() >= 5:
        return [], "unverified_weekend", None
    return [("09:15", "15:15" if cas else "15:30")], "cas_cts" if cas else "regular_cts", CAS_SOURCE if cas else None


def expected_starts(day, windows):
    result = []
    for start, end in windows:
        current = dt.datetime.fromisoformat(day + "T" + start).replace(tzinfo=IST)
        finish = dt.datetime.fromisoformat(day + "T" + end).replace(tzinfo=IST)
        while current < finish:
            result.append(current)
            current += dt.timedelta(minutes=5)
    return result


def audit_rows(rows, cas_effective=None):
    """Validate source rows without repairing, sorting or silently deduplicating."""
    grouped = defaultdict(list)
    issues = Counter()
    row_count = 0
    previous = None
    seen = set()
    for row in rows:
        row_count += 1
        try:
            stamp = dt.datetime.fromisoformat(row["date"])
            if stamp.utcoffset() != IST.utcoffset(None):
                raise ValueError("Expected explicit IST offset")
        except (KeyError, TypeError, ValueError):
            issues["malformed_timestamp"] += 1
            continue
        day = stamp.date().isoformat()
        grouped[day].append(stamp)
        if stamp in seen:
            issues["duplicate_timestamp"] += 1
        seen.add(stamp)
        if previous is not None and stamp < previous:
            issues["out_of_order"] += 1
        previous = stamp
        if stamp.second or stamp.microsecond or stamp.minute % 5:
            issues["misaligned_timestamp"] += 1
        try:
            values = {key: float(row[key]) for key in ("open", "high", "low", "close", "volume")}
        except (KeyError, TypeError, ValueError, OverflowError):
            issues["malformed_numeric"] += 1
            continue
        if not all(math.isfinite(value) for value in values.values()):
            issues["nonfinite_numeric"] += 1
            continue
        if any(values[key] <= 0 for key in ("open", "high", "low", "close")):
            issues["nonpositive_price"] += 1
        if values["volume"] == 0:
            issues["zero_volume"] += 1
        if values["volume"] < 0:
            issues["negative_volume"] += 1
        if not (values["low"] <= min(values["open"], values["close"]) <= max(values["open"], values["close"]) <= values["high"]):
            issues["invalid_ohlc"] += 1

    sessions = []
    legacy_excluded = []
    for day, stamps in sorted(grouped.items()):
        windows, kind, source = session_spec(day, cas_effective)
        expected = expected_starts(day, windows)
        actual_set, expected_set = set(stamps), set(expected)
        missing = sorted(expected_set - actual_set)
        unexpected = sorted(actual_set - expected_set)
        legacy_expected = expected_starts(day, [("09:15", "15:30")])
        legacy_ok = stamps == legacy_expected and dt.date.fromisoformat(day).weekday() < 5
        complete = bool(expected) and stamps == expected
        record = dict(date=day, bars=len(stamps), kind=kind, complete=complete,
                      first=stamps[0].strftime("%H:%M"), last=stamps[-1].strftime("%H:%M"),
                      expectedBars=len(expected), missing=[x.strftime("%H:%M") for x in missing],
                      unexpected=[x.strftime("%H:%M") for x in unexpected],
                      duplicateBars=len(stamps)-len(actual_set), source=source)
        sessions.append(record)
        if not legacy_ok:
            legacy_excluded.append(record)
    return dict(schemaVersion=VERSION, rows=row_count, observedSessions=len(sessions),
                rowIssues=dict(issues), sessions=sessions,
                legacyExcludedSessions=legacy_excluded,
                legacyExcludedClassification=dict(Counter(x["kind"] for x in legacy_excluded)),
                completeSessions=sum(x["complete"] for x in sessions),
                completeMeansTimestampGridOnly=True,
                missingBars=sum(len(x["missing"]) for x in sessions),
                unexpectedBars=sum(len(x["unexpected"]) for x in sessions),
                limitations=["Absent whole sessions require a separate complete exchange holiday calendar.",
                             "CAS eligibility is a caller-supplied point-in-time assumption; do not apply to all NSE stocks.",
                             "OHLC shape checks do not independently verify provider prices or corporate actions.",
                             "CAS auction prints are separate from continuous trading and must not be fabricated as continuous bars."])


def audit_csv(csv_path, batch_dir=None, cas_effective=None):
    path = Path(csv_path)
    with path.open(encoding="utf-8", newline="") as handle:
        report = audit_rows(csv.DictReader(handle), cas_effective)
    report.update(createdAt=dt.datetime.now(dt.timezone.utc).isoformat(),
                  dataSha256=hashlib.sha256(path.read_bytes()).hexdigest(),
                  auditScriptSha256=hashlib.sha256(Path(__file__).read_bytes()).hexdigest(),
                  casEffective=cas_effective,
                  calendarVersion="nse-cts-exceptions-2023-2026-v1",
                  calendarEvidence=[CAS_SOURCE, CAS_LAUNCH_SOURCE])
    metadata_path = path.with_suffix(".meta.json")
    if not metadata_path.exists():
        metadata_path = path.with_suffix(".json")
    if metadata_path.exists():
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
        report["sourceMetadata"] = {key: metadata[key] for key in ("source", "timezone", "interval", "from", "to", "rows", "complete", "adjustments") if key in metadata}
        report["metadataSha256"] = hashlib.sha256(metadata_path.read_bytes()).hexdigest()
    if batch_dir:
        batch = Path(batch_dir)
        policy = json.loads((batch / "policy.json").read_text(encoding="utf-8"))
        summary = json.loads((batch / "summary.json").read_text(encoding="utf-8"))
        report["batchIntegrity"] = dict(policyDataHashMatches=policy.get("dataSha256") == report["dataSha256"],
                                       excludedDatesMatch=summary.get("excludedSessions") == [x["date"] for x in report["legacyExcludedSessions"]],
                                       originalHoldoutStart=summary.get("holdoutStart"), originalHoldoutEnd=summary.get("holdoutEnd"),
                                       originalPartition=policy.get("partition"))
        report["batchArtifactsSha256"] = {
            name: hashlib.sha256((batch / name).read_bytes()).hexdigest()
            for name in ("policy.json", "summary.json", "trials.jsonl", "development-metrics.json", "findings.json", "report.md")
            if (batch / name).is_file()
        }
    normal = [x["date"] for x in report["sessions"]
              if x["complete"] and x["kind"] in ("regular_cts", "cas_cts")]
    if len(normal) >= 80:
        report["calendarCorrectedNormalSessionPartition"] = {
            "usableNormalSessions": len(normal),
            "developmentStart": normal[0], "developmentEnd": normal[-61],
            "validationStart": normal[-60], "validationEnd": normal[-21],
            "holdoutStart": normal[-20], "holdoutEnd": normal[-1],
            "status": "Calendar-only diagnostic; exposed data cannot become a new sealed holdout.",
        }
    return report


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--csv", type=Path, required=True)
    parser.add_argument("--batch-dir", type=Path)
    parser.add_argument("--cas-effective", help="Verified CAS eligibility start date for this security (YYYY-MM-DD)")
    parser.add_argument("--output", type=Path, required=True, help="New private JSON report; existing files are never replaced")
    args = parser.parse_args()
    result = audit_csv(args.csv, args.batch_dir, args.cas_effective)
    with args.output.open("x", encoding="utf-8") as handle:
        json.dump(result, handle, indent=2, allow_nan=False)
    print(json.dumps({key: result[key] for key in ("schemaVersion", "rows", "observedSessions", "rowIssues", "completeSessions", "missingBars", "unexpectedBars", "legacyExcludedClassification")}))
