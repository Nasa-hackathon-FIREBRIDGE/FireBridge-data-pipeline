"""Load every inventoried downloaded NASA point archive, without geographic/date filtering."""
import argparse
import json
from pathlib import Path
from firebridge.lake import load_all

p=argparse.ArgumentParser(description=__doc__)
p.add_argument('--folder', type=Path, default=Path('/home/da-rog/Downloads/nasa hackathon data'))
p.add_argument('--profiles', type=Path, default=Path('data/processed/archive_profiles'))
p.add_argument('--output', type=Path, default=Path('data/platform/lake'))
p.add_argument('--modis', type=Path, default=Path('data/processed/modis_2024_2025/detections.parquet'))
a=p.parse_args()
print(json.dumps(load_all(a.folder,a.profiles,a.output,a.modis),indent=2,default=str))
