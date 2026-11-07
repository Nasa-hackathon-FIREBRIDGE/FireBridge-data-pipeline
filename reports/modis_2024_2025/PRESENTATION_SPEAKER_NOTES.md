# MODIS Terra and Aqua presentation notes

## 1. MODIS Terra and Aqua

This presentation explains the global MODIS point data, then applies the findings to the northern Morocco pilot in the FIREBRIDGE blueprint. The window includes both endpoint dates. Read the charts as recorded satellite detections. This EDA does not establish wildfire incident counts, burned hectares or model accuracy.

Local evidence: reports/modis_2024_2025/summary.json and FIREBRIDGE_Blueprint.md.

## 2. The analysis covers 367 UTC dates

The inputs comprise 13 standard monthly files from the MODIS Fire Science Team. Exact date filtering gives 4,876,343 input rows. Native exact-row deduplication and quarantine produce 4,876,343 analysis rows. We independently compare 202,406 January 1–17 2025 rows to the user's FIRMS archive across every shared native field. 202,406 rows match. Full export coverage means the monthly archives are available for the window. Actual cloud-free observation coverage remains unknown from points.

Local evidence: reports/modis_2024_2025/tables/input_inventory.csv

## 3. One row is one thermal detection

Explain this as one thermal detection at a satellite acquisition time. Several rows can come from one ongoing fire. The location marks a pixel center. It does not establish the ignition point or perimeter. Coordinates and UTC time are the primary join keys. Brightness is a band temperature and FRP measures instantaneous radiative power within the observed pixel.

Source: https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html
Local evidence: reports/modis_2024_2025/tables/pilot_detections.csv

## 4. Terra and Aqua sample different times

Terra and Aqua carry MODIS but sample the Earth at different times. Their detection counts can differ because fire activity evolves between observations and because viewing, cloud and illumination conditions differ. Keep platform and day/night information throughout the analysis. The blueprint selects Aqua as the reference convention and gives Terra a separate observation regime. Historical nominal times should not replace the actual acquisition timestamps in 2024 and 2025.

Source: https://modis.gsfc.nasa.gov/data/dataprod/mod14.php
Local evidence: reports/modis_2024_2025/tables/platform_summary.csv

## 5. Data validity and observation coverage

Distinguish table validity from observation completeness. A valid row can still represent a questionable thermal detection. A complete monthly point archive also cannot prove that every location had an unobscured observation. The archive carries detections, while full fire masks contain the observation support needed for valid absence labels. Deduplicate only under a stated key and keep immutable source files.
Negative FRP values remain review flags and do not enter FRP quantiles. Zero FRP is reported separately. The January overlap audit checks every shared native field as a multiset, so it does not rely on row order.

Local evidence: reports/modis_2024_2025/tables/quality_checks.csv, reports/modis_2024_2025/tables/january_overlap_differences.csv

## 6. Global recorded activity peaks in Aug 24

The first and last January periods have different lengths, so compare detections per included calendar day alongside counts. These rates still describe detections, not a coverage-adjusted fire rate. One year gives a seasonal pattern for this window, not a long-term trend. Global totals combine many regional fire calendars.

Local evidence: reports/modis_2024_2025/tables/monthly.csv

## 7. Northern and southern patterns differ

This chart groups latitude at or above zero as Northern and below zero as Southern. It compares recorded detection patterns and mixes many climates and land uses inside each hemisphere. It does not imply a single fire season for either hemisphere. One-degree spatial bins and the detailed global map in the report provide a closer geographic view. One-degree bins differ in area with latitude, so their raw counts cannot establish geographic fire intensity.

Local evidence: reports/modis_2024_2025/tables/hemisphere_monthly.csv, reports/modis_2024_2025/tables/global_1degree_bins.csv

## 8. Confidence changes which rows we retain

Native confidence is a sensor algorithm quality score. It does not provide a calibrated probability that a wildfire happened. The analysis uses numeric cutoffs of below 30, 30 through 79 and 80 through 100. Keeping confidence at least 30 provides the initial retained layer, while all rows and high-confidence rows provide sensitivity comparisons. The cutoff trades detection retention against questionable detections and requires evaluation.

Source: https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf
Local evidence: reports/modis_2024_2025/tables/confidence.csv

## 9. FRP has a long upper tail

Use the median and high percentiles because the distribution can have a long upper tail. FRP is measured in megawatts and expresses radiative power at the acquisition time. Summing samples from different passes does not calculate fire energy without time integration and observation corrections. A high FRP does not identify burned hectares or incident severity by itself.

Source: https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html
Local evidence: reports/modis_2024_2025/tables/platform_summary.csv

## 10. Daytime detection times show separate regimes

Approximate local solar time equals UTC hours plus longitude divided by 15, wrapped to 24 hours. This supports a global comparison of sampling regimes but is not local civil time. Use the native day/night flag as the algorithm illumination classification. Summaries of detected fire timestamps are conditional on detections and do not describe all orbital passes or establish observation coverage.

Local evidence: reports/modis_2024_2025/tables/solar_hour_bins.csv, reports/modis_2024_2025/tables/platform_daynight_summary.csv

## 11. Pixel footprints vary across the swath

MODIS pixels have a nominal scale near one kilometre at nadir and expand toward the scan edge. FIRMS reports scan and track dimensions. The UMD monthly archive reports a sample index but omits these dimensions. Do not fill missing footprint dimensions with one kilometre and call them measurements. Later pairing should use compatible geolocation and sensor angles.

Source: https://firms.modaps.eosdis.nasa.gov/descriptions/FIRMS_MODIS_Firehotspots.html
Local evidence: reports/modis_2024_2025/tables/january_footprint_summary.csv

## 12. Thermal anomalies have inferred source types

The inferred type is useful for reviewing recurring thermal sources. It is an algorithm assignment, not independently verified land use. Type zero indicates a presumed vegetation fire and can include agricultural burning. Recurrence can reflect repeated observations of a sustained burn, agricultural practices or an industrial source. Keep recurrence as a review signal and document any exclusion rule.

Source: https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf
Local evidence: reports/modis_2024_2025/tables/type.csv

## 13. The Morocco pilot contains 57 detections

The pilot is the blueprint study rectangle from longitude -6.4 to -4.5 and latitude 34.5 to 35.9. It is not a Morocco national boundary or administrative region. A country-scale conclusion requires an explicit boundary. A small number of detections may be insufficient for learning or stable evaluation. Expand the chosen time window or region before making accuracy claims.
The monthly bars show recorded detections. A zero bar only means no exported hotspot in this rectangle for that month and platform. It does not indicate complete clear-sky coverage or absence of all burning.

Local evidence: reports/modis_2024_2025/tables/regional_summary.csv, reports/modis_2024_2025/tables/pilot_monthly.csv, reports/modis_2024_2025/tables/regional_grid_sensitivity.csv

## 14. The FIREBRIDGE response

FIREBRIDGE aims to estimate whether a supported Aqua observation would report at least one retained detection in a five kilometre cell. Aqua is a reference convention with its own limitations. Terra needs a separate adapter. The native detection layer remains visible so users can inspect the original evidence. The current EDA prepares that layer but does not establish the matched opportunity table.

Project source: FIREBRIDGE_Blueprint.md, sections on the scientific target and matched opportunity table.

## 15. Observation masks make absence labels possible

Point tables cannot distinguish a clear land observation with no detection from cloud, missing data or unobserved land. Obtain MYD14 and compatible MYD03 to define Aqua observation support. Use MOD14 and MOD03 for Terra. Decode the fire mask and quality flags, geolocate all relevant pixels, compute usable land fractions and store exclusion reasons before creating any zero labels.

Source: https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD14
Compatible geolocation source: https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD03
Project source: FIREBRIDGE_Blueprint.md.

## 16. The next deliverable is a supported pilot table

The next deliverable should be a small reproducible observation-support pilot. Choose a season and a manageable area, retrieve matched science granules, verify readers and product versions, then build an eligible cell and pass table. Freeze a baseline before ML. If 2024 is the final test period in the blueprint, this exploratory analysis must not become a reason to tune the final evaluation outcomes.

Project source: FIREBRIDGE_Blueprint.md, acquisition, pairing and evaluation design.