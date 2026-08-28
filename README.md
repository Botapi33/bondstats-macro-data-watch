# BondStats Macro Data Watch

**Track the economic data that moves rates, policy expectations and sovereign bond markets.**

Production-oriented, official-source-only macro monitor for BondStats.

## Coverage

### United States
- CPI — YoY
- Core CPI — YoY
- Nonfarm Payrolls — monthly change
- Unemployment Rate
- PCE Inflation — YoY
- Core PCE — YoY
- Real GDP — QoQ annualized

### Euro Area
- HICP — YoY
- Core HICP — YoY, excluding energy, food, alcohol and tobacco
- Unemployment Rate
- Real GDP — QoQ

## Automation

GitHub Actions runs every six hours and can also be started manually with **Run workflow**.

The updater uses:
- BLS Public Data API
- stable BEA official data pages
- Eurostat public Statistics API

No API key is required.

## Integrity model

The feed is deliberately conservative:
- official sources only
- no consensus forecasts
- no copied financial-news text
- no third-party market-data provider
- latest observation + previous comparable observation
- source-level diagnostics
- last-known-good values retained on parser/API failure
- `lastChecked` is separate from `lastSuccessfulDataUpdate`
- a source failure is shown as `degraded` instead of publishing guessed data

## Files

- `index.html` — full Macro Data Watch
- `widget.html` — compact homepage component
- `health.html` — source diagnostics
- `data/macro.json` — normalized feed
- `scripts/update_macro.py` — automated updater
- `.github/workflows/update-macro.yml` — six-hour GitHub Action + manual run
- `tests/test_macro.py` — deterministic production checks

## Deploy

1. Create repo `bondstats-macro-data-watch`.
2. Upload all files preserving folders.
3. Enable **Settings → Actions → General → Workflow permissions → Read and write permissions**.
4. Open **Actions → Update Macro Data Watch → Run workflow**.
5. Check `/health.html`.
6. Enable GitHub Pages from `main` / root.
7. Use `/index.html` as the full page and `/widget.html` for a compact Google Sites embed.

Official-source websites and API schemas can change. The updater therefore fails closed rather than guessing.

© 2026 BondStats Ltd. All rights reserved.

## Production verification

This final build includes:
- parser tests that execute the actual BLS, BEA and Eurostat parsing functions against deterministic fixtures;
- an atomic rollback per source group, so a partial source update is never published;
- both a scheduled workflow and a separate manual `Run workflow` action;
- tests before every commit;
- source-health reporting through `health.html`;
- verified current seed values dated 28 August 2026.

The scheduled workflow runs every six hours. Official macro data changes only on release days, so most runs will simply confirm the existing observation and update source health. If an official API/page changes format, the source is marked degraded and the last-known-good observation remains published rather than being guessed.
