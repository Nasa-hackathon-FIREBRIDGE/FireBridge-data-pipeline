"""Initialize only mount roots; never recursively change ownership of existing data."""
import os
from pathlib import Path
uid=int(os.environ['AIRFLOW_UID'])
if uid<=0: raise ValueError('Airflow runtime UID must be non-root')
for name in ('/data','/imports','/opt/airflow/logs'):
    path=Path(name)
    path.mkdir(parents=True,exist_ok=True)
    os.chown(path,uid,0)
    os.chmod(path,0o770)
for name in ('/data/lake','/data/lake/history'):
    path=Path(name)
    if not path.exists():
        path.mkdir();os.chown(path,uid,0);os.chmod(path,0o770)
print('Mount roots initialized; existing nested data unchanged.')
