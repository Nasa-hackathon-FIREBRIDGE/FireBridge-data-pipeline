# Independent scientific review

Reviewed 2026-10-10. Main pipeline: `analysis/modis_2024_2025/analyze.py`; outputs: `summary.json`, all tables, processed points, original monthly gzip files and the user's FIRMS ZIP. The independent review script and machine-readable checks are adjacent to this file.

## Verdict

**The current counts and scientific descriptive summaries pass independent reconciliation.** One concrete grid-index export issue was found, reported and fixed by the root agent. The fix was independently verified for all three regional Parquets and the pilot CSV. No remaining count error was identified in the delivered tables.

## Independent evidence

- Freshly scanned all 13 monthly gzip files; verified their SHA-256 values, raw row counts and date-window row counts against the input inventory. Raw rows total 5,217,303; exclusions are 192,267 before January 17, 2024 and 148,693 after January 17, 2025. Selected population: **4,876,343**.
- Reaggregated each native source by acquisition date/platform and matched all 734 daily platform/date rows. Both platforms have exported detections on all **367 inclusive UTC dates**. This is point-file availability, not cell coverage.
- Independently validated native `HHMM` hours 0–23/minutes 0–59, month membership, platform codes, day/night codes, integer sample values, and the **zero-based sample range 0–1353**. Selected rows have no invalid native timestamps or sample indices. Numeric selected fields are finite; processed timestamps stay within `[2024-01-17T00:00Z, 2025-01-18T00:00Z)`.
- Independently checked exact native duplicates and repeated satellite/time/location keys: none.
- Reconciled daily, monthly, platform, day/night, confidence, type, hemisphere/month, 1-degree spatial and solar-hour-bin tables to **4,876,343**, and each separately to Aqua **3,347,476** / Terra **1,528,867**.
- Checked native retained flags against confidence ≥30 and vegetation candidate flags against type=0 plus confidence ≥30. Selected vegetation candidates: **4,433,643**. Monthly denominators correctly use 15 dates in January 2024, 17 in January 2025, and the complete February–December calendar months.
- Recomputed every saved exact quantile from the full processed population, separately by platform/day/night and field. Maximum absolute floating-point difference from CSV serialization was below `1e-10`.
- Independently projected the regional points to EPSG:6933, recomputed 2/5/10 km cell indices and all positive-cell/UTC-day/solar-day counts, and matched the grid-sensitivity table.
- Freshly read the complete original FIRMS ZIP CSV, thereby checking ZIP CRC, selected January 1–17, 2025, sorted all 11 shared native fields, and matched its **202,406 rows** exactly to the independent MCD14ML source. This comparison preserves multiplicity and does not depend on row order. The mismatch export is empty.

## Issue found and resolved

Before the fix, `gx`/`gy` in saved regional rows carried the last loop's 10 km indices while the separate recurrence tables correctly used 5 km indices. Unlabeled indices could be mistaken for the blueprint's 5 km grid. The pipeline now exports `grid_x_5km` and `grid_y_5km`, and drops temporary `gx`/`gy`. Verified the current pilot CSV and every regional Parquet equal `floor(x_m/5000)`, `floor(y_m/5000)`.

## Interpretation gates for the report and presentation

1. **Positive cell-days are descriptive only.** Current regional counts combine native day and night, within each platform. Aqua's pilot candidates are 33 detections in 19 positive 5 km cells and 20 cell/UTC-day combinations; Terra's are 16 detections in 12 cells and 12 cell/UTC-day combinations. They are not afternoon-only paired observation labels, incident counts, or coverage-corrected rates. The future blueprint target requires a specified regime and observation eligibility.
2. **Geography is explicit.** Regional outputs are rectangles, not country/province polygon results. In the pilot rectangle there are 35 Aqua and 22 Terra rows; the type0/confidence≥30 candidate count is 49. The wider rectangle should not be labeled a national Morocco total. One-degree global bins have different ground area by latitude, so their row counts should not be called an equal-area fire density.
3. **The source substitution is disclosed.** MCD14ML is the official standard global location product. It lacks the FIRMS `scan`/`track` fields. January footprint quantiles apply only to 2025-01-01..17; they should not be called full-window footprint statistics. Native `sample` is an index, not a width or a direct monotonic view-angle measure: both swath edges are farther from nadir.
4. **All-platform FRP medians mix regimes and types.** Aqua's 20.6 MW and Terra's 16.3 MW describe different sampled populations. This is not evidence that Aqua measures every fire more strongly, that a region burned more area, or that one platform is more accurate. Comparisons should expose day/night and type strata. The 2,425 zero-FRP rows remain visible and are not invalid detections by definition; no negative FRP rows occur.
5. **Confidence retains its native meaning.** Low<30, nominal30–79, high≥80; native confidence0 is valid. Inferred type0 is presumed vegetation, not confirmed wildfire. A confidence threshold is not a calibrated probability or guarantee of truth.
6. **Time is recorded, not assumed.** Approximate mean solar hour is UTC+longitude/15 modulo24, with the shifted solar date saved separately. This is not civil time and has no equation-of-time adjustment. Hotspot timing distributions cannot by themselves describe all orbital coverage opportunities.
7. **Point availability is not observation support.** Exported rows occur on every global date, but points cannot supply cloud/usable-land/observation denominators or eligible negatives. Any zero on an exported point calendar means no exported retained detection under that counting rule, not clear-sky absence of fire.

## Low-impact future hardening

The pipeline counts non-finite numeric fields, invalid sample indices and nonpositive temperatures but does not include every such flag in its quarantine mask. Every corresponding current quality count is zero, so this does not alter this analysis. Before accepting new products, define which flags are fatal, preserve flagged native rows, and ensure non-finite FRP never reaches quantiles. Source file validation currently relies on explicit assertions; preserve the normal non-optimized Python execution used here.

Detailed numerical evidence: `independent_science_checks.json` (108 passed checks), `independent_science_review.log`, and `grid_export_fix_checks.json`.
