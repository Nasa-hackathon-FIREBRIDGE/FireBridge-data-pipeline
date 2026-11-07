"""Restore an application dump into a new disposable DB, verify objects, then remove only that DB."""
import argparse
import hashlib
import json
from pathlib import Path
import re
import subprocess
from uuid import uuid4

parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--backup-root',required=True,type=Path)
args=parser.parse_args()
root=args.backup_root.resolve()
stamp=(root/'LATEST').read_text().strip()
if not re.fullmatch(r'\d{8}T\d{6}Z',stamp):raise ValueError('Invalid backup timestamp')
for line in (root/'dumps'/f'{stamp}.sha256').read_text().splitlines():
    expected,name=line.split(maxsplit=1)
    if '/' in name or not name.startswith(stamp):raise ValueError('Invalid backup manifest')
    with (root/'dumps'/name).open('rb') as f:
        if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Backup checksum mismatch')
db='firebridge_restore_test_'+uuid4().hex[:12]
stack=['sh','scripts/stack.sh','exec','-T','db']
def command(*cmd,**kw):return subprocess.run(stack+list(cmd),check=True,**kw)
def query(sql):
    return command('psql','-X','-U','firebridge','-d',db,'-v','ON_ERROR_STOP=1','-At','-c',sql,capture_output=True,text=True).stdout.strip()
command('createdb','-U','firebridge',db)
try:
    with (root/'dumps'/f'{stamp}-firebridge.dump').open('rb') as f:
        command('pg_restore','-U','firebridge','-d',db,'--no-owner','--no-privileges','--exit-on-error',stdin=f)
    counts=json.loads(query("""SELECT json_build_object('detections',(SELECT count(*) FROM firebridge.detections),
      'source_releases',(SELECT count(*) FROM serving.releases),
      'analytics_versions',(SELECT count(*) FROM serving.latest_analytics))"""))
    paths=query("""SELECT storage_uri FROM firebridge.assets UNION SELECT storage_uri FROM firebridge.data_partitions
      UNION SELECT manifest_uri FROM firebridge.data_releases UNION
      SELECT artifacts_uri FROM firebridge.analytics_builds WHERE artifacts_uri IS NOT NULL""").splitlines()
    for uri in paths:
        path=(root/uri).resolve()
        if not path.is_relative_to(root/'objects') or not path.is_file():raise ValueError('Missing or invalid restored object')
        expected=path.stem
        with path.open('rb') as f:
            if hashlib.file_digest(f,'sha256').hexdigest()!=expected:raise ValueError('Restored object checksum mismatch')
    print(json.dumps({'restore':'passed','database':db,'verified_objects':len(paths),'counts':counts},indent=2))
finally:
    assert db.startswith('firebridge_restore_test_')
    command('dropdb','-U','firebridge','--force',db)
