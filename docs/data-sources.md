# Data sources and provenance

## Policy

Use synthetic demo data until a historical-data provider and intended use are reviewed. Publicly viewable data is not automatically licensed for copying, storage, redistribution, or commercial use. Do not scrape or redistribute market data without confirmed permission.

## Required provenance record

For each dataset, record provider, original URL, instrument/universe, interval, exchange timezone, retrieval timestamp, coverage, adjustments/corporate-action treatment, missing-data behavior, license/terms, permitted uses, attribution, and checksum/version where appropriate.

## Quality checks

Validate ordering and timezone of timestamps, gaps, duplicates, symbol changes, corporate actions, outliers, and source revisions. Label missing or synthetic values. Prevent look-ahead leakage and retain a reproducible data version for each simulation.

## Digest source registry

The initial registry is `data/digest-sources.json`. Entries are research candidates only; `enabled` is false. Recheck terms and endpoint behavior before activating any source. NSE website policy says its site content is copyrighted and subject to terms; RSS availability alone is not permission to reproduce. BSE has no verified permitted feed endpoint in this initial registry. See [weekly digest operations](weekly-market-digest.md).
