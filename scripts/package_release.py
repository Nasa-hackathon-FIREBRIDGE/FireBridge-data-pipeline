"""Create a source deployment bundle using an allowlist; never package .env or data."""
from datetime import datetime,timezone
from pathlib import Path
import tarfile

root=Path(__file__).resolve().parents[1]
output=root/'dist'
output.mkdir(exist_ok=True)
name=output/('firebridge-'+datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')+'.tar.gz')
files=['README.md','FIREBRIDGE_Blueprint.md','pyproject.toml','requirements-data.lock',
       'Dockerfile','compose.yaml','compose.airflow.yaml','compose.local.yaml','compose.contabo.yaml','compose.release.yaml','start_local.sh','stop_local.sh','history_status.sh','.dockerignore','.env.example','.gitignore']
if (root/'LICENSE').exists():files.append('LICENSE')
directories=['src','dags','dbt','deploy','scripts','tests','config','docs/data','docs/architecture','.github']
with tarfile.open(name,'w:gz') as bundle:
    for entry in files:
        bundle.add(root/entry,arcname=entry,recursive=False)
    for entry in directories:
        for path in sorted((root/entry).rglob('*')):
            if not path.is_file() or path.is_symlink():continue
            if path.relative_to(root).as_posix() in ('deploy/server-profile','deploy/release-image'):continue
            if set(path.parts)&{'__pycache__','target','logs','.pytest_cache'}:continue
            if path.name.startswith('.env') or path.name=='.user.yml':continue
            bundle.add(path,arcname=str(path.relative_to(root)),recursive=False)
print(name)
