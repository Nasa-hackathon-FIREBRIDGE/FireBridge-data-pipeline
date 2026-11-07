"""Reproducible local VIIRS pilot import; no network and no source-file edits."""
import argparse
import json
from pathlib import Path
from firebridge.archive import import_archive
from firebridge.catalog import PILOT_BBOX
from firebridge.config import Settings

parser=argparse.ArgumentParser()
parser.add_argument('--folder',type=Path,default=Path('/home/da-rog/Downloads/nasa hackathon data'))
args=parser.parse_args()
settings=Settings.load()
receipts=[]
for item in json.loads(Path('config/local_archives.json').read_text()):
    print('IMPORT',item['file'],flush=True)
    result=import_archive(settings,args.folder/item['file'],item['feed'],'morocco-pilot',PILOT_BBOX,item['start'],item['end'],
                          coverage_start=item['coverage_start'],coverage_end=item['coverage_end'])
    receipts.append(dict(file=item['file'],**result))
    Path('data/platform/local-archive-receipts.json').write_text(json.dumps(receipts,indent=2))
    print(json.dumps(receipts[-1]),flush=True)
