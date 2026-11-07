**FIREBRIDGE — A consistent fire history across changing satellites**

**Recommendation.** Build a web application that turns MODIS and VIIRS observations into a documented, comparable calendar of satellite-observed burning activity. Demonstrate it in northern Morocco, then test the method on a held-out Mediterranean region. Make the correction inspectable: users should see the original observations, the calibrated record, and the periods in which comparison is unsupported.

This is a proposed research design, not a validated algorithm or an operational fire-warning service. No observations, fitted models, or measured performance results are included in this pack. The accompanying JSON files specify acquisition, features, tables, experiments, and delivery tasks. All thresholds below are starting design choices to test, not NASA requirements.

**01 · The exact challenge and the scope to protect**

The published challenge summary asks for a web application that harmonizes active-fire records into a burning-activity calendar for a selected area. It includes both wildfires and agricultural burning. Historical patterns, unusual activity, and periods deserving attention are central to the brief. [Official challenge](https://www.spaceappschallenge.org/2026/challenges/harmonization-of-modis-and-viirs-hot-spots/)

As of this blueprint, detailed statements and required resources are scheduled for October 28. Reconcile this design with those requirements when released. The event is November 14–15, 2026; the published project-submission window runs from Saturday 09:00 to Sunday 23:59 local time. Local presentation deadlines can be earlier. The participant FAQ says teams may not begin challenge work before the hackathon. Treat this document as research and a proposed approach; reserve implementation, model fitting, and submission deliverables for the authorized event window, and check the organizer's preparation rules. [Event](https://www.spaceappschallenge.org/2026/) · [Participant FAQ](https://www.spaceappschallenge.org/resources/participant-faqs/)

The prototype must deliver five things: an area selector; a calendar; a reproducible method for comparison; evidence that the method improves a defined baseline; and a visible statement of data coverage. A national prediction system, emergency dispatch tool, smoke simulator, and climate-attribution study are separate projects.

**02 · Why this matters in Morocco and internationally**

Morocco is a defensible pilot. A July 30, 2026 report carrying MAP reporting quotes ANEF's director on approximately 340 fires and 2,150 affected hectares since the beginning of that year. This is a dated partial-year update, not a complete 2026 total. [ANEF update reported by H24/MAP](https://h24info.ma/maroc/feux-de-foret-au-maroc-baisse-de-pres-de-31-des-superficies-brulees-par-rapport-a-la-moyenne-annuelle-anef/)

A separate official Moroccan portal bulletin from August 2025 identified elevated fire danger in several northern provinces, including Chefchaouen and Larache. It also shows that ANEF already uses scientific fire-danger models. The product opportunity is therefore a transparent historical-comparison layer supporting existing expertise. The 2025 bulletin is not evidence of today's danger level. [Moroccan government bulletin](https://www.maroc.ma/fr/actualites/lanef-publie-son-bulletin-de-risque-des-incendies-de-forets-pour-la-periode-allant-du-17-au-20-aout)

Begin with the Chefchaouen–Larache corridor and neighboring forest/cropland mosaics. The proposed download rectangle is west −6.4°, south 34.5°, east −4.5°, north 35.9°. It is a computational study window, not a province boundary. Clip it to a reviewed land/AOI polygon before reporting regional statistics. Do not call the pilot a validated national map.

Global relevance comes from the common observation problem: changing instruments, sensitivity, viewing geometry, and sampling can change detection counts. NASA's August 7, 2026 notice says Suomi NPP science-product delivery is scheduled to cease November 1, 2026 at 13:00 UTC, subject to change, and directs users toward NOAA-20/21. Preserve S-NPP's archive for historical overlap; design any later refresh around available successor products. [NASA transition notice](https://www.earthdata.nasa.gov/data/alerts-outages/suomi-npp-data-product-delivery-cease-november-1-2026)

Use southern Spain as a geographic holdout if accessible labels and sufficient paired observations exist. This tests Mediterranean transfer. A global claim needs additional biomes, fire regimes, and independent evaluation; one successful transfer is not worldwide validation.

**03 · The distinctive product idea**

The user question is: “When was burning unusual here, and how much of the apparent difference depends on the satellite record?”

FIREBRIDGE answers through three linked views:

| View | What the user does | What makes it useful |
|---|---|---|
| Fire calendar | Select an AOI, compare years and seasonal windows | Common units, observed coverage, and historical context appear together |
| Satellite comparison | Switch between individual sensors and the calibrated metric | The correction can be inspected instead of hidden behind a single score |
| Evidence panel | Open one cell or week | Shows source passes, quality flags, valid area, model version, uncertainty, and exclusions |

The strongest demonstration is a **withheld-satellite experiment**. In a year where both sensors observed the same area, conceal Aqua observations from the prediction pipeline. Predict the defined Aqua-equivalent response from VIIRS, then reveal the held-out Aqua record. Show successes and failures. The audience sees what the model learned and how it was tested.

A second distinctive feature is an uncertainty map that distinguishes “low activity with good observations” from “insufficient observations.” These states should never share the same color. Add a download of the evidence behind any calendar cell.

This is a distinctive proposed combination, not a claim that no previous research has attempted sensor harmonization. The contribution must be supported by the eventual experiment and product, not by calling the model unprecedented.

**04 · Define the measurement before building a model**

A hotspot is a satellite detection associated with a pixel and acquisition time. It is not automatically a distinct fire incident, a burned-area measurement, an ignition, or a fire perimeter. A fire can generate many detections; a detected thermal anomaly can have another origin. MODIS fire observations have nominal 1 km resolution and VIIRS I-band fire observations nominal 375 m resolution; actual footprint and detectability vary. [MODIS product](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD14) · [VIIRS product](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP14IMG)

Use two explicitly named outputs:

1. **Comparable activity:** an Aqua-MODIS-equivalent detection response at 5 km cell scale within a specified afternoon observation regime. This is the primary historical comparison.
2. **VIIRS detail:** original 375 m nominal detections, retaining small-fire information in the years available. This is a detail layer, not reconstructed historical imagery.

The primary response is deliberately conservative. It asks whether the reference sensor would report at least one retained hotspot in a cell under supported paired-observation conditions. It does not recover the true number of fires missed by every sensor. Aqua is an imperfect reference convention, not ground truth.

Using a MODIS reference preserves an interpretable link to the longer record and avoids inventing fine-scale locations in early years. The tradeoff is reduced sensitivity to small burns in the comparable layer. Preserve VIIRS detail so the user can see that information rather than discard it.

Start with Aqua and S-NPP because their historical afternoon observations can provide suitable near-time pairs. Verify actual timestamps; do not assume a fixed orbital time, particularly in later years. Terra has a different observation regime and requires a separate adapter and evaluation. Its raw record can be displayed before its calibrated contribution is supported.

**05 · Data sources and access plan**

| Priority | Dataset / entry point | Fields or information needed | Role and access note |
|---|---|---|---|
| Required | [FIRMS archive](https://firms.modaps.eosdis.nasa.gov/download/) | Coordinates, acquisition date/time, satellite, confidence, brightness fields, FRP, scan/track, version | Convenient historical detection tables; use standard processing for the retrospective analysis; Earthdata login may be needed |
| Required | [FIRMS active-fire downloads](https://firms.modaps.eosdis.nasa.gov/active_fire/) | Recent detection tables and archive guidance | Source discovery and optional provisional layer; keep NRT separate |
| Required | [MYD14 Aqua fire swaths](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD14) | Fire mask, quality flags, fire-pixel fields, acquisition metadata | Reference detections and observation eligibility |
| Required | [MYD03 geolocation](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MYD03) | Pixel locations, solar/sensor angles, companion granule information | Geolocate the full mask, including locations without detected fire; explicitly resolve a collection compatible with the fire product |
| Required | [VNP14IMG S-NPP fire swaths](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP14IMG) | VIIRS fire mask, quality and detection information | Historical calibration source |
| Required | [VNP03IMG geolocation](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VNP03IMG) | Image-band pixel geometry and viewing metadata | Geolocate and assess non-detection opportunities |
| Next | [VJ114IMG NOAA-20 fire swaths](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VJ114IMG) and [VJ103IMG geolocation](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/VJ103IMG) | Same conceptual fields, platform-specific schemas | Train and validate a successor-platform adapter; availability must be checked |
| Next | [MOD14 Terra fire swaths](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MOD14) | Terra observations and masks | Separate morning-regime analysis; do not pool blindly with afternoon data |
| Useful | [MCD12Q1 land cover](https://ladsweb.modaps.eosdis.nasa.gov/missions-and-measurements/products/MCD12Q1) | Annual cover classes and quality, summarized as fractions | Stratify forest, cropland, shrubland and other surfaces; this does not identify ignition cause |
| Evaluation | [MCD64A1 burned area](https://developers.google.com/earth-engine/datasets/catalog/MODIS_061_MCD64A1) | Burn date, uncertainty, QA, first/last reliable day | Corroborate timing and broad spatial patterns; not an independent label because its algorithm uses MODIS active-fire observations |
| Evaluation | [EFFIS](https://forest-fire.emergency.copernicus.eu/) | Event reports, available perimeter/statistical products | Check coverage and source lineage; some products also use satellite fire information; access may require a data request |
| Optional | [ERA5-Land](https://cds.climate.copernicus.eu/datasets/reanalysis-era5-land?tab=overview) | Temperature, dew point, wind, rainfall and soil variables | Context for unusual seasons; hourly reanalysis at native approximately 9 km, distributed on 0.1° grid; not a live weather forecast |
| Optional | Verified local incident reports | Date ranges, location uncertainty, origin, report reference | Independent corroboration when actually available; ANEF public summaries are not automatically a downloadable incident-level dataset |

The [NASA FIRMS FAQ](https://www.earthdata.nasa.gov/data/tools/firms/faq) links the current [VIIRS Collection 2 user guide](https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf) and [MODIS C6/C6.1 user guide](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf). Use those definitions when implementing mask and QA decoders. The VIIRS guide link was verified through NASA's FAQ; its complete PDF content was not retrieved for this blueprint. Do not hard-code an unverified bit schema.

FIRMS archive guidance places Terra data from late 2000, Aqua from mid-2002, and S-NPP from January 2012. Plan a full-year Aqua display beginning in 2003. Do not assume all products, platforms, or processing streams have the same start date. Public FIRMS pages differ on the NOAA-20 start date; query the chosen archive/source and record its actual inventory. A NOAA-21 NRT source is documented in the API; do not assume an equivalent standard archive is exposed by the same API.

**06 · Acquire a bounded, reproducible dataset**

Start with a manifest listing AOI, product short name, collection, processing stream, time bounds, expected granules, file URLs, retrieval time, byte size, checksum, and license/citation reference. Discover files before downloading. Measure the size of a one-week sample rather than guessing the total download.

Use three acquisition tiers:

| Tier | Proposed extent | Purpose |
|---|---|---|
| Smoke test | One AOI and a small contiguous window containing available positive and negative opportunities | Prove file access, full-mask parsing, time pairing, and an end-to-end calendar |
| Hackathon core | Selected complete seasons in 2020–2023; 2024 reserved for final temporal evaluation | Compare baseline and ML with a feasible swath volume; retain negative periods and label the limited seasonal coverage |
| Expanded research | Available annual overlap from 2012–2025, plus reference record from 2003 onward | Test interannual stability and create a longer historical calendar |

If the selected core has too few independent fire episodes, broaden years or the training region. Count positive spatial/temporal blocks, not merely millions of neighboring pixels. An event-only sample is insufficient for calibrated occurrence rates.

For bulk historical detections, prefer archived files. For smaller requests, the [FIRMS Area API](https://firms.modaps.eosdis.nasa.gov/api/area/) documents a MAP_KEY, source code, bounding box, date, and day range. At verification, its documented range is 1–5 days per request, with a transaction budget. Query availability and chunk accordingly; do not depend on an old example using a larger range. Documented standard sources include MODIS_SP, VIIRS_SNPP_SP, and VIIRS_NOAA20_SP. API schemas and availability are rechecked at implementation.

Keep credentials in local secrets/environment configuration, outside the repository and public browser bundle. No login, key request, observation download, or data-use agreement has been completed on the user's behalf in this pack.

**07 · Canonical data model**

The companion data_contracts.json contains planning contracts for these tables:

| Table | Grain / key | Essential contents |
|---|---|---|
| sources | One source specification | Provider, product, collection, stream, citation, access route |
| assets | One physical input file | Product and granule identifiers, checksum, retrieval/version metadata |
| detections | One native detection | Platform, UTC acquisition, coordinates, native confidence, FRP, brightness and footprint metadata |
| grid_cells | One analysis cell | Grid definition, geometry, AOI overlap area, land area |
| observations | One cell × platform × pass | Observed, usable, cloud and invalid fractions; eligibility; source granules; retained fire count |
| matched_pairs | One cell × matched source/reference pass pair | Time difference, shared usable support, target, eligibility reason, split group |
| features | One eligible pair or inference opportunity | Only predictors available from the source observation and approved context |
| predictions | One cell × selected opportunity | Reference-equivalent probability, model identity, support status, provenance |
| calendar | One AOI/cell × reporting period × metric | Numerator, denominator, activity, coverage, uncertainty, observed/inferred share |
| evaluations | One model × experiment × slice | Metrics, sample size, positive count, block count, uncertainty, baseline comparison |

Every output should trace back to immutable assets. Store raw confidence values and their type: MODIS's numeric field and VIIRS's category field are not a universal probability scale. Separate sensor confidence from uncertainty of the learned harmonization model.

Do not let the convenience CSV and the corresponding swath create two independent copies of the same observation. Choose one canonical record and use the other for cross-checks or enrichment. Join on platform, granule/acquisition and spatial identity; preserve disagreements as QA exceptions.

**08 · End-to-end pipeline**

~~~mermaid
flowchart TD
    A[Hotspot archives] --> C[Canonical observations]
    B[Fire masks and geolocation] --> C
    C --> D[Matched observation pairs]
    D --> E[Blocked training and evaluation]
    C --> F[Reference record]
    E --> G[Calibrated VIIRS record]
    F --> H[Calendar and evidence]
    G --> H
    B --> H
~~~

Stage 1 — Inventory and ingest. Download AOI-intersecting granules and detections, retry transient failures with bounded backoff, verify checksums, and quarantine incomplete files. A missing file is an ingestion gap, not an observation of no fire. Preserve the original bytes and metadata.

Stage 2 — Decode and normalize. Combine acquisition date and zero-padded time in UTC. Keep native day/night flags; derive approximate local solar time from longitude for comparison, and use Africa/Casablanca only for user-facing civil time. Normalize units without changing their meaning. Reject invalid coordinates, unrecognized mask codes, and unsupported product collections. Reading MODIS HDF4 and VIIRS files may require different readers; xarray alone does not guarantee HDF4 support. Verify a small file first and use GDAL/pyhdf or an appropriate backend when needed.

Stage 3 — Build observation support. Decode fire-product mask/QA categories into usable land, cloud/obscured, invalid/unprocessed, and water. Geolocate every relevant pixel, not only the fire-pixel table. Reproject to an equal-area grid and compute area fractions. A proposed 5 km grid in EPSG:6933 suits this Morocco pilot; a worldwide/polar product needs a documented grid extension. Deduplicate overlap inside one pass and document footprint approximations at swath edges.

Stage 4 — Apply consistent inclusion rules. Start with documented nominal/high detection classes, then run an all-confidence sensitivity experiment. Use each product's definition rather than an invented common score. Keep raw rows. Mark persistent thermal sources for review, using product type/source flags where available; do not automatically delete every recurring hotspot because recurrent agricultural burning is within scope.

Stage 5 — Pair observations. Select same-cell Aqua–VIIRS observations within an initial 30-minute tolerance, similar local-time/daylight regime, and sufficient shared usable land. Test 15 and 60 minutes. Match passes without using whether a fire was detected. Use a deterministic nearest-time pairing with no reuse inside a sensor-pair series. Larger tolerances introduce actual fire evolution into the calibration error.

Stage 6 — Build labels and features. Use full-mask eligible opportunities to create both positive and negative reference labels. Derive source features on shared usable support during training. Keep target-only geometry, target detection attributes, pairing time gap, split group, and reference coverage out of the predictor matrix unless an explicit later serving design can supply them. They can remain eligibility and audit fields.

Stage 7 — Train, calibrate and evaluate. Freeze spatial and temporal splits before inspecting model scores. Fit preprocessing only on training data. Select hyperparameters on development blocks, probability calibration on a disjoint calibration block, and evaluate once on untouched test blocks.

Stage 8 — Materialize the calendar. Select at most one documented representative observation per cell/local day for each harmonized series. Prefer a valid reference pass; otherwise use a supported calibrated source according to a fixed priority. Do not maximize hotspot count when choosing a pass. Compute weekly/monthly views and retain missing periods.

Stage 9 — Serve cached outputs. The map reads precomputed tables or tiles; it does not download or process swaths during a presentation. An optional later refresh writes NRT outputs into a clearly separate provisional stream. When standard products arrive, recompute affected partitions under a new recorded data version.

**09 · Matching, negatives, and the common-support problem**

The most important training table is the matched opportunity table. Proposed initial rules are: a 5 km cell; daytime afternoon regime; pass difference no more than 30 minutes; and at least 80% of cell land usable in the intersection of both observations. These are design hypotheses. Evaluate 2/5/10 km cells and 60/80/90% usable-area gates to see whether conclusions depend on them.

Within an eligible pair, target y = 1 when the Aqua reference has at least one retained hotspot on the shared usable support, and y = 0 when it has none. Zero means “no retained reference detection under these conditions.” A cell obscured or missing in either required mask is excluded with a reason. A VIIRS-positive/Aqua-negative pair is a valid example of sensor disagreement, not automatically a false alarm.

Train using source features restricted to the same shared area. At inference, only source coverage is available. Require high usable source coverage, check that feature distributions and viewing conditions resemble training, and label the transfer assumption. The absence of reference coverage at inference cannot be solved by merely filling a column. A stricter near-complete-coverage experiment is essential: if performance changes substantially, do not publish broad continuity claims.

Do not create negatives by sampling random absent FIRMS coordinates. Point detections alone do not supply local observation coverage. NASA's missing-data service can identify full platform-day gaps, but cannot replace a local cloud/validity mask. [FIRMS FAQ](https://www.earthdata.nasa.gov/data/tools/firms/faq)

**10 · Feature engineering**

Keep the first model small enough to audit. Compute the following from the VIIRS source pass unless explicitly marked otherwise:

| Feature group | Proposed features | Rationale and caveat |
|---|---|---|
| Detection structure | hotspot count, log1p(count), binary detection flag | Measures source response; several pixels are not several incidents |
| Spatial spread | occupied analysis subcells, point/footprint dispersion | Distinguishes a concentrated group from dispersed activity; derived extent is not burned area |
| Radiative signal | maximum and sum of valid per-pass FRP, log1p transforms, missing/saturation flags | Supplies signal strength; never sum different passes as if simultaneous, or label FRP as energy |
| Confidence composition | fractions low/nominal/high; indicator of missing confidence | Preserves source quality distribution; not directly comparable numerical certainty |
| Thermal channels | source brightness summaries and differences where defined | Sensor-specific features; do not treat MODIS and VIIRS band temperatures as identical channels |
| Viewing conditions | median and high-percentile scan/track size, source sensor zenith where available | Captures detection/footprint conditions; detection-only geometry is missing when no hotspot exists |
| Observation support | usable land fraction, cloud fraction, invalid fraction, available pixel area | Prevents absence of usable observations becoming zero fire |
| Timing | local solar time and day/night flag; optional cyclical day-of-year | Sampling varies with time; seasonal features can damp unusual events, so test without them |
| Surface context | forest, cropland and shrubland fractions with land-cover year/QA | Allows stratified relationships; land cover is not fire cause or a perfect historical record |
| Platform | S-NPP or NOAA-20 identity, with separately checked adapters | VIIRS is an instrument family, not a guarantee of identical platform behavior |

Use zero hotspot count only for a usable observation. For no detected hotspot, count is zero but per-detection brightness and footprint summaries are null with a missingness indicator. Derive all-pixel viewing geometry from the geolocation product where possible. Do not fill absent brightness with a physical temperature of zero.

Exclude raw calendar year, target Aqua FRP/count/confidence, post-event burned-area labels, future weather, and region identifiers that simply memorize locations. Latitude/longitude should be excluded from the first model or evaluated with a strict spatial ablation. Every normalization, land-cover join, and imputation rule needs a version.

Weather and vegetation stress are optional context features for a later anomaly-explanation module. They are not necessary to make the first harmonizer work. Separate the scientific question “what did the sensors observe?” from the later question “why was this period unusual?”

**11 · The ML method to build first**

Train a separate source-to-reference mapping for each supported VIIRS platform:

P(reference detection = 1 | source-pass features, eligible paired-observation regime).

This estimates an observation response, not the probability of a true fire anywhere in the cell. The latter needs a different observation model and additional evidence.

Implement a model ladder:

| Model | Inputs and output | Why it belongs |
|---|---|---|
| B0: unadjusted common-grid baseline | Source any-detection indicator on matched opportunities | Shows what simple spatial aggregation accomplishes |
| B1: logistic regression | Count/FRP, coverage and simple geometry terms | Interpretable calibration baseline; low development cost |
| B2: histogram gradient boosting | Same approved features plus nonlinear interactions | Recommended ML candidate; handles threshold and interaction effects without image-scale training |
| B3: small MLP | Exactly the same tabular features and split | Optional deep-learning benchmark if there are enough independent examples |

For B1, fit standardized numeric transforms only on training data. For B2, begin with shallow trees, regularization, and a modest search; for example 15–31 leaves, learning rate 0.05–0.1, 100–300 iterations, and a conservative minimum leaf size. These are search seeds, not selected hyperparameters. Disable a library's automatic random validation split when it conflicts with the explicit blocked split. Select iterations using the designated development data. [Scikit-learn ensemble documentation](https://scikit-learn.org/stable/modules/ensemble.html)

Use log loss for probabilistic training and sample weights if negatives were subsampled. Preserve natural prevalence in calibration/test data. Uncorrected class weighting or oversampling can distort probability estimates. Start without them if the bounded dataset fits; if sampling is needed, keep inclusion probabilities and evaluate using the original distribution.

Fit sigmoid or isotonic calibration using independent calibration blocks; use sigmoid when sample support is limited. Isotonic requires enough examples to avoid a fragile staircase. Report reliability plots alongside Brier score and log loss; Brier score alone does not isolate calibration quality. [Probability-calibration documentation](https://scikit-learn.org/stable/modules/calibration.html)

Deploy B2 only if it improves meaningful holdout behavior over B1. If it does not, a well-explained baseline with evidence is the stronger submission. No claimed accuracy or improvement exists until the experiment is run.

**12 · Deep learning and advanced research, with an explicit purpose**

A small MLP is the most realistic DL extension: standardized continuous features, one-hot platform/context values, missingness indicators, hidden layers of 64 and 32 units, ReLU, modest dropout, and one output logit. Train with binary cross-entropy and independent early stopping/calibration. Test it against the identical boosted-tree benchmark; a neural network is not automatically more suitable for this table. [PyTorch loss documentation](https://docs.pytorch.org/docs/2.14/generated/torch.nn.BCEWithLogitsLoss.html)

A later image-based model could encode thermal-radiance patches and masks from near-simultaneous source observations. It would require additional calibrated-radiance products, band-aware preprocessing, co-registration, cloud/saturation handling, considerably more storage, and a geographically broad training corpus. An encoder could predict a reference detection map on coarse support, trained only where labels are observable. This is a research extension, not a necessary weekend dependency. Do not apply a generic image super-resolution model and present generated 375 m historic hotspots as observed evidence.

A more scientific long-term extension is a hierarchical latent-observation model: latent burning state Z, sensor-specific detection sensitivity q_s, false-alarm component f_s, and observed response Y_s. For example, P(Y_s=1 | Z) = q_s Z + f_s(1−Z), with appropriate context and temporal dependence. Two imperfect sensors do not uniquely identify all these quantities without constraints, priors, repeated observations, or independent labels. A latent model can therefore make assumptions explicit, but does not create missing ground truth.

A temporal neural model may later summarize sequences or estimate missing periods, but any imputed activity must stay a separate model layer and must be tested using masked, held-out windows. Never silently replace unobserved calendar periods with predictions.

An optional language model can turn computed statistics and citations into Arabic/French/English explanations. The numerical engine supplies every number. The text layer cannot invent causal explanations, decide emergency actions, or function as the harmonizer. A deterministic explanation template is sufficient for the MVP.

**13 · Calendar mathematics and uncertainty**

Let z(g,d) be the retained Aqua indicator when the reference observation is usable, or the calibrated probability from one selected supported VIIRS pass otherwise. Let v(g,d)=1 only when the observation and method are eligible; let a(g) be the land area of cell g inside the AOI.

Define comparable activity over period W as:

H(W) = sum[a(g) × v(g,d) × z(g,d)] / sum[a(g) × v(g,d)].

Define observation coverage as:

C(W) = sum[a(g) × v(g,d)] / (number of reporting days × sum[a(g)]).

Display H as a reference-equivalent active-cell response among eligible observations. It is dimensionless; it is not hectares burned, the fraction of land physically burning, the number of incidents, or an all-weather fire rate. Equal-area weighting concerns the aggregation support, not conversion of a hotspot into burned area.

The score is conditional on usable observations. Cloud absence is not random, and sensor scheduling changes can still bias comparisons. Always compare coverage distributions, local times, geometry, and land-cover mix. Add a common-support comparison restricting two selected periods to compatible cell/observation strata; if the conclusion reverses, show it. Coverage normalization alone does not solve all selection bias.

Use a fixed selection policy to prevent additional satellites from automatically increasing activity. Do not average many duplicate detections or calculate 1−product(1−p) across dependent passes and call it daily fire probability. Retain counts of candidate passes and the chosen pass ID for audit.

For a seasonal calendar, compare the same month or week-of-year across the available reference period, excluding the evaluated year. With only a few seasons, show distributions and sample counts; avoid claims about long-term season shifts. With sufficient years, estimate percentiles or a robust deviation from a seasonal median. Handle zero median absolute deviation explicitly instead of dividing by a tiny arbitrary constant. Require adequate observations and years before labeling an anomaly.

Separate three uncertainty dimensions: observation coverage; model transfer error; and sampling variability of the historical baseline. Use spatial/temporal block bootstrap for aggregate intervals, resampling independent regional/time blocks rather than individual neighboring detections. Include model refitting when estimating training uncertainty, or explicitly label an interval as conditional on the fixed model. A bootstrap interval does not cover all sensor bias or missing-fire uncertainty.

The first version can show coverage and held-out aggregate residual bands if a reliable bootstrap is too expensive. Label these as empirical error ranges, not universal 95% guarantees.

**14 · Validation that makes the project credible**

Freeze the split manifest and a baseline before tuning. Proposed core split: 2020–2021 training, 2022 development, 2023 probability calibration, and 2024 untouched final temporal test. Use the same predeclared seasonal window in each year, or complete years if feasible. Exact acquisition boundaries must be chosen after inventory but before outcome inspection. If a split has too few positive independent blocks, widen the acquisition period or simplify the model rather than reporting an unstable calibration.

Also run a spatial holdout: reserve separated Moroccan blocks or a province-sized area, and keep a southern-Spain study window out of all tuning for the transfer experiment. Use roughly 25–50 km spatial blocks with an appropriate buffer and group multi-day fire episodes across adjacent cells. These block sizes are proposals to test. A random row split is not credible because nearby observations of the same event leak across sets.

| Experiment | Main question | Report |
|---|---|---|
| Temporal holdout | Does the mapping transfer to a new season/year? | Brier, log loss, PR-AUC, reliability, prevalence and sample counts |
| Geographic holdout | Does it work away from fitted locations? | Same metrics by region and land-cover group |
| Withheld-satellite replay | Can VIIRS reproduce the reference response when Aqua is hidden? | Weekly/monthly MAE and bias against the held-out reference |
| Platform transfer | Is a NOAA-20 adapter supported? | Separate platform results; no pooled headline hiding failure |
| Synthetic instrument switch | Does a mixed source series create an artificial discontinuity? | Compare all-reference truth with a series switched on a predeclared date inside the overlap |
| Coverage sensitivity | Is performance dependent on partially visible cells? | Refit/evaluate under stricter shared-coverage thresholds |
| Time/grid sensitivity | Are conclusions robust to matching and support choices? | Compare 15/30/60 minutes and 2/5/10 km grids |
| Feature ablation | What is each feature family contributing? | Remove season, land cover, FRP, geometry or coverage in turn |
| Event corroboration | Does the record align with documented burning? | Temporal/spatial agreement with independently sourced reports, with uncertainty |

The synthetic switch experiment does not prove a real historical increase is artificial. It tests a controlled change of observation source while the reference remains available. Never enforce smoothness across sensor introduction dates as the principal loss: a real change in burning could occur at the same time.

Report error on the same response and same eligible opportunities for every model. Raw hotspot counts and active-cell probabilities have different units; their errors cannot be compared directly. PR-AUC is useful for sparse positives, but prevalence must accompany it. A model predicting “no detection” everywhere may have high accuracy and be useless.

Suggested release gates: ML improves aggregate error over logistic calibration on untouched data; important strata have adequate samples; probabilities are reasonably calibrated; results survive practical sensitivity tests; and no holdout receives training/preprocessing leakage. If evidence is weak, publish the simpler model, qualify the unsupported slice, or retain source-specific views.

**15 · What the final application looks like**

The opening screen presents northern Morocco, an AOI selector, a year range, and a concise statement of the selected metric. A calendar uses years as rows and weeks/months as columns. Activity intensity uses color; insufficient coverage uses hatching/neutral gray; unavailable model support uses a distinct state. Tooltips report values, denominator, valid days, source composition and provenance.

Below the calendar, a time-series panel compares original source responses on a common unit and the harmonized response. Raw pixel counts remain accessible on their own axis/view. Users should not see incomparable count and probability curves overlaid without explanation.

Clicking a week opens the map with native detections, the 5 km analysis grid, and observation coverage. Clicking a cell shows Aqua/S-NPP/NOAA-20 timestamps, confidence categories, selected pass, exclusions, model version and empirical error information. An “Inspect the comparison” control opens the withheld-satellite replay.

An evidence card can say: “This period has more reference-equivalent activity than comparable periods in the selected baseline. Observation coverage is adequate/limited. The estimate uses observed reference data and/or calibrated source data.” Numbers are inserted only after calculation. Avoid automatic claims that climate change, negligence or agricultural burning caused a particular anomaly.

Allow export of calendar statistics, per-cell provenance and a concise methods note. Include French/Arabic interface text for Morocco and English for the global presentation; support right-to-left layout if Arabic is included. Use keyboard-accessible controls and an accessible color palette. Do not spend the first hours on a globe animation.

**16 · Technical architecture and working method**

Use Python for ingestion and analysis, Arrow/Parquet for tables, GeoParquet for geometries, and DuckDB for bounded queries. Use appropriate HDF/netCDF readers for swaths, and GeoPandas/Rasterio or equivalent tools where compatible. Store raster masks/tiles with explicit CRS, nodata, units, and resampling metadata. Nearest-neighbor/area-aware handling is needed for categorical masks; bilinear interpolation of category codes is invalid.

Use scikit-learn for the first two statistical models; PyTorch is an optional benchmark dependency. Record package versions in a lockfile at implementation rather than assuming today's documentation version is installed. A FastAPI backend can expose cached datasets to a React/MapLibre interface. For a small demo, static precomputed JSON/tiles can remove the server dependency. Tool selection is an implementation proposal, not a requirement from NASA.

Plan these routes or equivalent local data interfaces: area metadata; calendar by AOI and period; per-cell observations; model comparison; provenance export. The response always includes metric identifier, grid version, data version, model version, coverage, and status. A machine-readable unsupported result is better than returning an apparently valid zero.

Suggested modules are acquisition, product decoding, geolocation, QA, pairing, features, model training, evaluation, calendar aggregation, export, and UI. Give one person ownership of the canonical schema. Every pipeline step reads immutable inputs and writes a versioned output partition; rerunning it must not duplicate rows.

Partition detections by source/year/month and observation tables by AOI/year. Cache the derived mask fractions rather than re-opening every swath for every feature experiment. Keep a small run manifest tying the data inventory, config, code commit, model artifact and outputs together. Save the holdout manifest before model fitting.

A laptop with 16 GB RAM is a reasonable initial engineering target for bounded derived tables, but actual swath volume must be measured. Process granules incrementally and aggregate to cells immediately. No GPU is required for the recommended baseline/boosted-tree plan. Global raw swath processing is explicitly outside the weekend budget.

**17 · Hackathon execution schedule**

Use elapsed hours from your local start, then adjust to the organizer's earlier presentation/submission deadline. Work in shifts and keep a working demo throughout; this schedule does not assume anyone works continuously without rest.

| Window | Main work | Concrete exit condition |
|---|---|---|
| 0–3 h | Reconcile full challenge statement, inventory one window, freeze schema and metric | One real hotspot file and corresponding masks decode successfully |
| 3–8 h | Normalize, build valid opportunities, pair passes, create initial calendar | Trace one calendar cell back to raw files; missing differs from zero |
| 8–14 h | Logistic baseline and blocked evaluation; UI develops in parallel using real derived schema | Baseline report and a functional AOI/calendar screen |
| 14–21 h | Boosted-tree candidate, probability calibration, held-out replay | Evidence of improvement or a decision to keep the baseline |
| 21–27 h | Integrate map, evidence drawer, coverage display and exports | Complete user journey works from cached data |
| 27–32 h | Geographic/coverage sensitivity; successor adapter only if core is complete | Honest test report, supported scope, resolved critical defects |
| 32–35 h | Record demo, prepare concise narrative and methods, review source attribution | Reproducible offline demonstration and submission draft |
| 35 h onward | Submit before local deadline; retain time for upload/review problems | Confirmed submission and preserved artifacts |

For four people, use data/QA, model/evaluation, frontend, and product/integration roles. For two people, combine data with ML and frontend with integration, and cut weather, DL, successor adapters and localization beyond the main presentation language. For a solo project, prioritize a source-aware calendar plus one verified calibration experiment.

**18 · Scope gates and fallbacks**

| Problem | Response |
|---|---|
| Mask/geolocation decoding is not working by the first integration gate | Reduce the AOI/time window and seek a documented gridded-mask route; if coverage remains unavailable, deliver source-specific descriptive calendars and clearly say normalization is incomplete |
| Too few independent positives in Morocco | Expand training to a justified Mediterranean region; keep Morocco as a visible evaluation/pilot; do not inflate sample size with adjacent pixels |
| Time-matched pairs are scarce | Inspect overpass drift and actual timestamps; do not widen the tolerance solely to improve scores; consider a separately defined coarser regional/week target with its own validation |
| ML does not beat logistic calibration | Use logistic calibration and show why it was chosen |
| Transfer fails in Spain or a land-cover slice | Publish the supported geography and show the failure; do not label the product globally validated |
| NOAA-20 adapter is not ready | Keep the historical S-NPP experiment; label successor continuity as planned |
| Download or live API fails during presentation | Use cached, dated inputs and precomputed outputs with visible provenance |
| Full challenge statement changes required outputs | Preserve the data/QA work but adapt deliverables; the official statement controls |

A plausible fallback is valuable, but a detection-only calendar is not full harmonization. State that limitation clearly rather than presenting a source selector as a completed scientific solution.

**19 · Demo narrative and claims**

Suggested 90-second sequence: 15 seconds on the observation problem; 20 seconds on the Moroccan calendar and coverage; 30 seconds concealing/revealing the reference record in the withheld-satellite test; 15 seconds on measured error and a failure case; 10 seconds on next-region transfer and the evidence export. Adjust timing to the official submission format once published.

Suggested project description: “FIREBRIDGE connects changing satellite fire records into a transparent history of burning activity. Our Morocco pilot combines NASA active-fire observations with observation-quality masks, calibrates a defined common-scale response, and lets users inspect the evidence behind each calendar cell.” This is an original proposed description; add performance numbers only after measurement.

Claims that could become supportable after testing include improved agreement with a held-out reference, better continuity in a controlled source-switch experiment, and documented transfer to a second region. Claims not supported by this design include counting every fire, estimating hectares burned from hotspot counts, forecasting tomorrow's ignition, causal attribution of trends, or guaranteeing saved lives.

**20 · After the hackathon**

First, secure independent incident-level evaluation and expert feedback. Next, extend the NOAA-20/21 adapters, revisit coverage selection bias and orbital-time drift, evaluate night/morning regimes separately, and build broader biome benchmarks. Only then explore latent-state modeling, radiance-patch DL, or operational integrations. Maintain a model/data card and publicly reproducible evaluation where source licenses allow.

Water-catchment consequences are a possible Morocco extension after validated burn-severity, terrain and watershed data are added. They cannot be inferred responsibly from hotspot counts alone. The initial project remains stronger when it solves one observation problem well.

**21 · What is prepared in the accompanying pack**

The pack includes this blueprint, a linked data-source catalog, proposed source inventory requests, table contracts, a feature dictionary, a pipeline DAG, an experiment plan, a build backlog, a methods checklist, a sample output contract containing null values, and a file manifest. These are planning artifacts. Nulls are intentional: there are no fabricated satellite observations, invented confidence intervals or claimed model results.

The next concrete implementation milestone is one small, real, fully traceable pair of source/reference swaths that produces both positive and valid negative cell observations. Once that works, the rest of the pipeline has a reliable foundation.
