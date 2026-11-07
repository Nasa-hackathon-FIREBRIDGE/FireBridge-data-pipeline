"""Print full-history progress without accessing NASA or starting any process."""
import json
from pathlib import Path

root=Path(__file__).resolve().parents[1]/'data/platform/lake/history'
progress=root/'progress.json'
if not progress.exists():
    print('Full-history download has not started. Run ./start_local.sh when ready.')
    raise SystemExit(0)
report=json.loads(progress.read_text())
total=report['planned_windows']
done=report['completed_windows']
print('Recorded state:',report['state'])
print('Last update (UTC):',report['updated_at'])
print(f'Completed date windows: {done:,} / {total:,}'+(f' ({100*done/total:.1f}%)' if total else ''))
print(f"Downloaded source rows: {report['downloaded_source_rows']:,}")
print(f"Raw gzip + Parquet: {report['retained_bytes']/1024**3:.2f} GiB")
print(f"Free disk at last update: {report['free_disk_bytes']/1024**3:.2f} GiB (8 GiB reserve)")
for field in ('current_request','error_code','retry_seconds'):
    if field in report:print(field+':',report[field])
print('This is the last saved checkpoint, not a live process-health check. Check Airflow for task state.')
print('Airflow: http://localhost:8080/dags/firebridge_full_history_download')
print('Data: http://localhost:4213 — history.main')
