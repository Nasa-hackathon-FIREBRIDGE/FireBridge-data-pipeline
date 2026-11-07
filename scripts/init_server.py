"""Append missing private deployment settings; preserve existing DB/provider credentials."""
import base64
import os
from pathlib import Path
import secrets
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
for directory in ('data/platform','data/imports','data/platform-validation','data/imports-validation'):
    (root/directory).mkdir(parents=True,exist_ok=True)
subprocess.run([sys.executable,str(root/'scripts/init_local.py')],check=True)
target=root/'.env'
existing={line.split('=',1)[0] for line in target.read_text().splitlines() if '=' in line and not line.startswith('#')}
values={
 'AIRFLOW_UID':str(os.getuid() or 50000),
 'AIRFLOW_DB_PASSWORD':secrets.token_hex(24),
 'AIRFLOW_FERNET_KEY':base64.urlsafe_b64encode(secrets.token_bytes(32)).decode(),
 'AIRFLOW_JWT_SECRET':secrets.token_hex(32),
 'AIRFLOW_API_SECRET':secrets.token_hex(32),
 'AIRFLOW_ADMIN_USER':'admin',
 'AIRFLOW_ADMIN_PASSWORD':secrets.token_hex(24),
 'AIRFLOW_UI_PORT':'8080',
 'FIREBRIDGE_DBT_PASSWORD':secrets.token_hex(24),
}
with target.open('a') as f:
    f.write('\n# Private Airflow and dbt deployment settings\n')
    for key,value in values.items():
        if key not in existing:f.write(f'{key}={value}\n')
target.chmod(0o600)
print('Private server settings prepared; no credentials displayed or replaced.')
