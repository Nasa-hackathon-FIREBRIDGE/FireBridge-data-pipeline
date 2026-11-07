# Understanding MODIS Terra and Aqua for FIREBRIDGE

Research checked on 2026-10-10. Target: **2024-01-17 through 2025-01-17, inclusive, worldwide**. This is 367 UTC calendar dates. January 2024 contributes 15 dates and January 2025 contributes 17; compare those partial months carefully. These notes explain interpretation and project design. Counts and file availability belong in the generated analysis report.

The complete analysis uses **13 official MCD14ML standard monthly files** downloaded from the MODIS Fire Science Team's University of Maryland archive. That native format includes a cross-track `sample` index instead of explicit `scan`/`track` sizes. The original FIRMS CSV independently matches every shared native field for January 1–17, 2025; explicit footprint-size analysis is restricted to that overlap. The field descriptions below distinguish those schemas.

## Explain one row to the team

“At this time, this satellite detected a thermal anomaly inside this pixel.” The coordinates represent the pixel center. They are not an ignition coordinate or an exact fire perimeter. A pixel can contain several fires, and one spreading or continuing fire can produce many rows. A fire smaller than a nominal 1 km pixel may be detected. Detectability depends on conditions; pixel size is not minimum fire size. [NASA FIRMS MODIS FAQ](https://forum.earthdata.nasa.gov/viewtopic.php?t=5191)

Therefore use **detection**, **hotspot**, or **fire pixel** when discussing row counts. Avoid saying “number of wildfires” or “hectares burned.” More rows can reflect more burning, more successful observations, larger footprints, repeated observations, or a different time of day. Interpreting which explanation dominates requires further evidence.

## Terra and Aqua are two sampling schedules

Both carry MODIS. The fire products use mid-infrared and thermal-infrared information, including contextual comparison with neighboring pixels. Terra and Aqua each typically provide daytime and nighttime observations at mid-latitudes. They do not continuously watch a location. [NASA MODIS fire product overview](https://modis.gsfc.nasa.gov/data/dataprod/mod14.php)

Historical nominal daytime equator crossing times were approximately 10:30 for Terra and 13:30 for Aqua. **Those are not fixed times for the requested year.** A NASA presentation at AGU in December 2024 gives June 2024 examples of approximately **09:45 for Terra** and **14:10 for Aqua**, in local time at their respective equatorial nodes. These examples are not acquisition times for every latitude or hotspot. [NASA 2024 orbital-drift presentation](https://ntrs.nasa.gov/api/citations/20250000522/downloads/AGU24_Terra_25years_MODIS_geometry_poster_GLin.pdf)

Aqua has been drifting toward later crossings after its final drag-makeup maneuver in December 2021. Terra drifts earlier; its ground sampling pattern also changes. [NASA Aqua mission status](https://aqua.nasa.gov/), [NASA Terra constellation-exit explanation](https://modis.gsfc.nasa.gov/news/individual.php?news_id=100378)

**Analysis decision:** always split Terra/Aqua and native day/night. Use the recorded UTC timestamp. Derive approximate local mean solar time as UTC plus longitude / 15 hours, retaining the shifted local date. This longitude conversion is an approximation, not civil time or a measured equator-crossing time. A distribution calculated only from detected hotspots also reflects where and when burning was detected, so it cannot by itself measure the orbit's complete sampling schedule.

## Read the columns without changing their meaning

| Field | Meaning and useful interpretation |
|---|---|
| `latitude`, `longitude` | Degrees, pixel center; check geographic validity. |
| `acq_date`, `acq_time` | Acquisition in UTC; pad `HHMM` to four digits before parsing. `0045` means 00:45. |
| `satellite`, `instrument` | Terra or Aqua; MODIS is the instrument. |
| `brightness` | Band 21/22 brightness temperature in Kelvin. |
| `bright_t31` | Band 31 brightness temperature in Kelvin. |
| `sample` | Native MCD14ML cross-track sample index, zero-based 0–1353; not a pixel dimension in km. |
| `scan`, `track` | FIRMS overlap only: pixel dimensions in km along scan and track; vary across the swath. |
| `confidence` | Native numeric detection-quality estimate, 0–100. |
| `frp` | Pixel-integrated fire radiative power in megawatts. |
| `daynight` | Native day/night algorithm flag: `D` / `N`. |
| `version` | FIRMS field; MCD14ML collection/version instead come from the source filename. Retain native provenance. |
| `type` | Inferred hotspot category in standard MODIS location data. |

Sources: [NASA FIRMS attributes](https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs), [NASA MODIS FAQ](https://forum.earthdata.nasa.gov/viewtopic.php?t=5191). The attributes page was checked against its locally cached HTML because the live page returned HTTP 403 during this session.

The two temperature columns describe measured radiance expressed as a temperature. They are **not measured flame temperature**. `brightness - bright_t31` is a sensor-specific thermal contrast feature; it is not a universal fire severity score. FRP describes the rate of radiative energy release. Geometry and observation timing affect comparisons. A sum of FRP across different days is not total energy; energy would require a defensible time integration and treatment of gaps. [NASA FIRMS explanation of temperatures and FRP](https://forum.earthdata.nasa.gov/viewtopic.php?t=4541)

`scan × track` is an approximate pixel footprint area for exploring geometry. It does not measure the area actually burning or burned. It is not an exact polygon, and a coordinate dot should not be displayed as a precise fire boundary.

## Confidence and type: two different questions

MODIS confidence classes are **low: 0 ≤ C < 30; nominal: 30 ≤ C < 80; high: 80 ≤ C ≤ 100**. Native zero confidence is a low-confidence detection, not a malformed row. Type codes are **0 presumed vegetation fire, 1 active volcano, 2 other static land source, 3 offshore**. These are inferred categories. “Presumed vegetation” does not distinguish wildfire from agricultural or prescribed burning. Type 2 includes persistent and urban thermal sources; do not treat it as verified incident classification. [MODIS C6/C6.1 guide, Tables 10 and 11](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf)

A confidence value of 80 is not a calibrated 80% probability that a wildfire happened. NASA explains that native confidence does not correspond directly to statistical Type I/II error confidence levels. [NASA FIRMS confidence discussion](https://forum.earthdata.nasa.gov/viewtopic.php?t=4541)

**Analysis decision:** preserve every valid raw row. Show all detections, then a vegetation-focused `type = 0, confidence ≥ 30` view, and a stricter `confidence ≥ 80` sensitivity view. Report exactly how many rows each rule removes. This is a proposed project inclusion rule, not a claim that the remaining rows are ground truth. Review persistent sources without automatically deleting every recurring location; recurrent agricultural burning is in FIREBRIDGE's scope.

## What a missing dot means

A short-lived fire can occur between passes. Small/cool fires, canopy, cloud, or smoke can reduce detectability; instrument outages also matter. NASA cautions that point files omit cloud and missing-observation information, and that intervals shorter than about eight days can introduce severe sampling biases. [MODIS C6/C6.1 guide, Sections 7.1.1 and 8.3](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf)

**No detection is not the same as observed absence.** An archive date containing global rows does not prove that every cell, or either platform in that cell, was observed. Keep three states separate in FIREBRIDGE: retained detection, usable observation with no retained detection, and unsupported/missing observation. CSV points provide the first state. Full swaths and their quality information are needed to distinguish the other two.

For month-to-month charts, use “recorded detections” and identify incomplete exports. Do not fill missing downloaded periods with zero. Daily charts are exploratory rather than coverage-corrected rates. Global counts mix hemispheres, climates, land uses, and varying observation geometry, so they are not a single worldwide fire season.

## How this analysis fits the blueprint

The blueprint defines an **Aqua-equivalent detection response** on a 5 km analysis grid in a supported afternoon observation regime. Aqua is an imperfect reference convention. Terra belongs to a separate morning regime. Its raw record is useful immediately; calibrated integration needs its own adapter and evaluation.

The first useful product is a trustworthy observation table and an inspectable calendar, rather than a machine-learning accuracy claim. Keep source asset, row identifier, native fields, UTC timestamp, derived time, inclusion flags and exclusion reasons. Distinguish exact duplicate exports from genuine repeated observations: two nearby detections at different times can both be legitimate.

The proposed northern Morocco rectangle is west −6.4, south 34.5, east −4.5, north 35.9. It is a study window, not an administrative boundary or national result. Apply a reviewed land/AOI polygon before regional rates. The blueprint's EPSG:6933 grid is a pilot proposal; a global and polar implementation needs a documented grid choice.

## What to do next, in order

1. **Completed in this run: the requested point-data window.** Downloaded the 13 standard MCD14ML monthly source files, selected both inclusive endpoints, preserved originals and hashes, and verified platform/date inventory. The selected population contains 4,876,343 rows, with exported detections from each platform on every requested date. The January FIRMS overlap matched 202,406 shared observations exactly. Keep the source manifests and standard-processing rule for later extensions, and record any new export gaps explicitly. NASA distinguishes standard processing from faster NRT delivery. [NASA FIRMS data-source tutorial](https://firms.modaps.eosdis.nasa.gov/content/academy/data_api/firms_api_use.html)
2. **Make the analysis reproducible.** Parse UTC correctly; check coordinates, non-finite values, schema and exact duplicates; retain native provenance. Produce comparable platform/day-night/confidence/type summaries and inspect thermal/FRP tails and footprint distributions. Treat zeros and unusual values as flags to review rather than inventing undocumented validity rules.
3. **Build observation support in the pilot.** Download Aqua `MYD14` plus compatible `MYD03`, and Terra `MOD14` plus compatible `MOD03`. Decode full masks and QA, geolocate non-fire pixels too, and calculate usable land support per cell/pass. Geolocation provides pixel locations and solar/sensor angles. Current LAADS geolocation landing pages default to Collection 7, so explicitly resolve a compatible collection for the selected Collection 6.1 fire swaths. [Aqua fire swath](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD14), [Aqua geolocation](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD03), [Terra geolocation](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MOD03)
4. **Create pilot cell/pass labels.** A positive is at least one retained Aqua detection on shared usable support; a negative requires usable observation with none. Exclude unsupported cells with a reason. Start with the blueprint's proposed 5 km, ≥80% shared usable-land and ≤30-minute Aqua–VIIRS pairing rules, then test alternatives. These thresholds are hypotheses.
5. **Evaluate a small baseline.** Begin with transparent count/FRP/geometry features and logistic regression. Use held-out time and geography. Withhold Aqua, predict its defined response using eligible VIIRS observations, then reveal Aqua and report errors. A VIIRS-positive/Aqua-negative pair is sensor disagreement, not automatically a VIIRS false alarm. Build a separate Terra adapter after the afternoon baseline is supported.
6. **Present a claim supported by the evidence.** Show native detections, observation support, calibrated output and held-out errors together. Point-only EDA cannot establish coverage-corrected trends, burned hectares, ignition counts, model performance, or fire impacts. Burned-area and incident records can later corroborate patterns; they do not follow from multiplying hotspot count by pixel area.

Project design above follows [FIREBRIDGE_Blueprint.md](../../FIREBRIDGE_Blueprint.md). The EDA should explain how the data behave and where the proposed next steps still need evidence.
