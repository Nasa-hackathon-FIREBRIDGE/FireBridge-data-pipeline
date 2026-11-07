"""Prepare local mounts without changing private credentials or downloaded files."""
import argparse
import json
from pathlib import Path
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--archives',type=Path,help='Directory containing the original downloaded ZIP archives')
parser.add_argument('--skip-download',action='store_true',help='Start local exploration without starting the full-history download')
args=parser.parse_args()
subprocess.run([sys.executable,str(root/'scripts/init_server.py')],check=True)
envfile=root/'.env'
lines=envfile.read_text().splitlines()
existing={line.split('=',1)[0]:line.split('=',1)[1].strip().strip('"\'') for line in lines if '=' in line and not line.startswith('#')}
if not args.skip_download and not existing.get('FIRMS_MAP_KEY'):
    raise SystemExit('Full-history download needs FIRMS_MAP_KEY in private .env. Set it locally, or run ./start_local.sh --skip-download.')
folder=(args.archives or Path(existing.get('FIREBRIDGE_ARCHIVE_DIR',str(Path.home()/'Downloads/nasa hackathon data')))).resolve()
if not folder.is_dir():raise SystemExit('Archive directory not found. Run: sh start_local.sh --archives /path/to/downloads')
profiles=list((root/'data/processed/archive_profiles').glob('*/profile.json'))
if not profiles:raise SystemExit('Missing archive inventory under data/processed/archive_profiles; this launcher needs the local EDA data.')
missing=[json.loads(p.read_text())['archive'] for p in profiles if not (folder/json.loads(p.read_text())['archive']).is_file()]
if missing:raise SystemExit('Missing inventoried archives: '+', '.join(missing))
if not (root/'data/processed/modis_2024_2025/detections.parquet').is_file():raise SystemExit('Missing audited MODIS study Parquet')
if '\n' in str(folder) or '"' in str(folder) or '$' in str(folder):raise SystemExit('Archive directory contains unsupported .env characters')
lines=[line for line in lines if not line.startswith('FIREBRIDGE_ARCHIVE_DIR=')]
lines.append('FIREBRIDGE_ARCHIVE_DIR="'+str(folder)+'"')
envfile.write_text('\n'.join(lines)+'\n')
envfile.chmod(0o600)
for name in ('data/platform/lake','data/local-ui/extensions','data/local-ui/.duckdb/extension_data'):
    (root/name).mkdir(parents=True,exist_ok=True)
print(f'Local input check passed: {len(profiles)} ZIP archives plus the audited MODIS selection.')
