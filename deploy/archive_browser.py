"""Local DuckDB UI with a read-only archive catalog and separate notebook state."""
import os
from pathlib import Path
import signal
import threading
import duckdb

lake=Path(os.environ.get('FIREBRIDGE_LAKE_DIR','data/platform/lake')).resolve()
state=Path(os.environ.get('FIREBRIDGE_UI_STATE','data/local-ui')).resolve()
(state/'.duckdb/extension_data').mkdir(parents=True,exist_ok=True)
(state/'extensions').mkdir(exist_ok=True)
if not (lake/'catalog.duckdb').is_file():
    raise RuntimeError('Load the archive catalog before starting the archive browser')
os.chdir(lake)
conn=duckdb.connect(str(state/'notebooks.duckdb'),config={
    'home_directory':str(state),'extension_directory':str(state/'extensions'),
    'threads':2,'memory_limit':'2GB','temp_directory':str(state/'tmp'),
    'max_temp_directory_size':'1GB'})
conn.install_extension('ui')
conn.load_extension('ui')
conn.execute("ATTACH 'catalog.duckdb' AS nasa (READ_ONLY)")
if (lake/'history/catalog.duckdb').is_file():
    conn.execute("ATTACH 'history/catalog.duckdb' AS history (READ_ONLY)")
conn.execute('SET ui_local_port=4213')
conn.execute('CALL start_ui_server()')
print('Archive SQL browser: http://localhost:4213 — nasa.main (existing files), history.main (new full history when initialized)',flush=True)
stop=threading.Event()
for signum in (signal.SIGTERM,signal.SIGINT):
    signal.signal(signum,lambda *_:stop.set())
stop.wait()
conn.execute('CALL stop_ui_server()')
conn.close()
