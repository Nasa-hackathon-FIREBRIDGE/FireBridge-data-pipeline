# FIREBRIDGE data pipelines and exploration

**GitHub Actions and deployment:** [CICD_A_TO_Z.md](docs/data/CICD_A_TO_Z.md) explains the complete GitHub → tests → GHCR image → Contabo release pipeline, repository settings, private access, and recovery.

**Contabo VPS setup:** follow [CONTABO_SETUP.md](docs/data/CONTABO_SETUP.md) for security, SSH access, firewall rules, recovery, and the 6 vCPU / 12 GB deployment profile before starting the project on the new server.

**Run everything locally:** `./start_local.sh` starts Airflow, the existing database, local archive import, two SQL browsers, and a resumable **full-history NASA FIRMS download** for all project satellite groups. Use `./start_local.sh --skip-download` to launch without starting that download. See [FULL_HISTORY.md](docs/data/FULL_HISTORY.md) for date coverage and download progress, and [LOCAL_RUN.md](docs/data/LOCAL_RUN.md) for the local services. The full history is acquired into Parquet/DuckDB; PostgreSQL serves the existing validated project scopes.

**After downloading:** [HISTORY_SERVING.md](docs/data/HISTORY_SERVING.md) describes
the offline audit, isolated real-data storage benchmark, and bounded resumable
PostgreSQL publication. On a deployed server, `sh scripts/prepare_history.sh`
runs the audit and benchmark through Airflow without starting more downloads.

**Airflow + dbt deployment:** follow [the Hetzner VPS setup guide](docs/data/DEPLOYMENT.md), then [the analytical model guide](docs/data/ANALYTICS.md). The stack includes scheduled ingestion, manual historical imports, tested analytical builds, immutable publication, private Airflow access, backup scripts and recovery checks. The Node.js team continues to own the application API. Live provider subscriptions are enabled deliberately after validation.

The implemented Python data layer is documented in [docs/data/README.md](docs/data/README.md). Start with the [operations guide](docs/data/OPERATIONS.md) and give the [database handoff](docs/data/NODE_HANDOFF.md) to the **Node.js backend team**. This repository owns PostgreSQL/PostGIS, historical ingestion, validation, durable scheduling and versioned publication. It does not implement the HTTP API. Recurring provider subscriptions remain disabled; the full-history download is a separate explicit startup action.

The [project architecture guide](docs/architecture/README.md) describes the proposed web application and AI explanation service. The expanded [data-platform design](docs/architecture/DATA_PLATFORM.md) covers database relationships, historical imports, near-real-time updates, corrections and immutable releases. It includes [all tables and columns](docs/architecture/DATABASE.md), [pipeline procedures and proposed schedules](docs/architecture/PIPELINES.md), [28 detailed API endpoint contracts](docs/architecture/API.md), [verified source interfaces](docs/architecture/SOURCES.md) and the [PostgreSQL/PostGIS schema](docs/architecture/schema.sql). These are the original design documents. Executable migrations and ingestion code now live in `src/firebridge`; the current implementation and its remaining scientific work are described in `docs/data`. The database has been initialized; provider polling remains disabled.

The current analysis covers **MODIS Terra and Aqua worldwide, January 17, 2024–January 17, 2025 inclusive**. It uses 13 newly downloaded official standard monthly files and contains **4,876,343 detections** across 367 UTC dates. It also examines the northern Morocco study rectangle from the blueprint.

Start with the [simple MODIS team walkthrough](reports/modis_2024_2025/MODIS_EDA.html). Present the [editable PowerPoint](reports/modis_2024_2025/MODIS_Terra_Aqua_2024_2025_Presentation.pptx) or [PDF slides](reports/modis_2024_2025/MODIS_Terra_Aqua_2024_2025_Presentation.pdf). The PowerPoint includes speaker notes. Use the [executed MODIS notebook](notebooks/MODIS_Terra_Aqua_2024_2025.ipynb) to inspect the calculations, or the [detailed Markdown report](reports/modis_2024_2025/MODIS_EDA.md) for linked evidence and next steps.

The [raw source guide](data/external/modis_2024_2025/README.md) documents acquisition and the MCD14ML schema. [Summary](reports/modis_2024_2025/summary.json), [tables](reports/modis_2024_2025/tables/), and [scientific figures](reports/modis_2024_2025/figures/) support the analysis. The original FIRMS January 2025 archive independently matches all 202,406 overlapping records; its rows are not ingested a second time.

## Reproduce the MODIS analysis

Use the project Python 3.12 environment. The downloader uses the public MODIS Fire Science Team archive documented in NASA's guide; these point files do not require a personal Earthdata token.

```bash
firebridge_env/bin/python analysis/acquire_modis_monthly.py --download
firebridge_env/bin/python analysis/modis_2024_2025/analyze.py
MPLCONFIGDIR=/tmp/firebridge-mpl firebridge_env/bin/python analysis/modis_2024_2025/figures.py
firebridge_env/bin/python analysis/modis_2024_2025/build_report.py
firebridge_env/bin/python analysis/modis_2024_2025/notebook.py
```

Processed detections are in `data/processed/modis_2024_2025/detections.parquet`, with source filename/row, native fields and derived inclusion/time flags. Pilot tables label the 5 km EPSG:6933 grid explicitly. All raw monthly files, SHA-256 checksums and acquisition validation remain in `data/external/modis_2024_2025/`. New monthly files have cross-track sample index 0–1353 and no explicit scan/track widths; footprint statistics are limited to the January 2025 FIRMS overlap.

The HTML is self-contained for offline sharing. Data files must accompany the notebook if you move it. Native chart data in the slides are editable; the builder is under `analysis/modis_2024_2025/presentation/` and requires the bundled presentation runtime described there.

Point detections support an observed-hotspot calendar. Full fire masks, quality flags and compatible geolocation are still needed for eligible negative observations and the blueprint's harmonization model. The pilot has 57 detections, 49 under the proposed type-0/confidence ≥30 rule; broaden independent training years or area before model evaluation. One annual cycle does not establish climatology or unusual-season thresholds.

## Earlier exploration of the mixed downloads

Start with the [simple team walkthrough](reports/FIREBRIDGE_EDA.html): what the data means, what we found, and how we will use it in FIREBRIDGE. For the full technical evidence, read the [detailed report](reports/FIREBRIDGE_EDA.md) or open the [executed notebook](notebooks/FIREBRIDGE_EDA.ipynb) in VS Code using `firebridge_env/bin/python`.

- [Field dictionary](reports/FIELD_DICTIONARY.md): meanings, units, and sensor differences.
- [Data access](reports/DATA_ACCESS.md): downloaded datasets and remaining inputs.
- `reports/figures/`: scientific plots; `reports/tables/`: supporting CSV/JSON evidence.
- `data/processed/pilot_detections.parquet`: small working dataset for northern Morocco.
- `data/processed/regional_detections.parquet`: pilot plus broader context rectangles, exactly deduplicated.

Raw files stay in `/home/da-rog/Downloads/nasa hackathon data`. The pipeline streams ZIP members without extracting the global CSVs. The already extracted CSV is inventoried, not ingested twice.

## Reproduce

```bash
# Existing project environment, or recreate using Python 3.12 and this lockfile:
firebridge_env/bin/python -m pip install -r requirements-lock.txt
firebridge_env/bin/python analysis/profile_archives.py
firebridge_env/bin/python analysis/effis_context.py
firebridge_env/bin/python analysis/build_eda.py
firebridge_env/bin/python analysis/write_access.py
firebridge_env/bin/python analysis/finalize_report.py
firebridge_env/bin/python analysis/make_notebook.py
```

To use another raw folder, pass `--input '/path/to/folder'` to the profile script. Its current schema adapters target the ten supplied archives. New products require field validation before ingestion. To force a full recomputation after changing profiler logic, move the corresponding per-archive cache directories out of `data/processed/archive_profiles/`.

## Missing science files

`python3 analysis/acquire_context.py` discovers a bounded one-week window, fetches public documentation and the EFFIS workbook, and records failures. `firebridge_env/bin/python analysis/download_science.py` selects and downloads a small set of NASA science files when a locally configured `EARTHDATA_TOKEN` is available in `.env` or the process environment. Credentials never enter reports and `.env` is ignored by Git.

These are research and EDA artifacts. No harmonization model or deployed hackathon application is included. Point detections alone do not establish valid negative observations or observation coverage.
