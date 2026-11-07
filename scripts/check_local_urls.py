"""Wait for the three local pages; print no connection credentials."""
import time
from urllib.request import urlopen
for url in ('http://127.0.0.1:8080/api/v2/monitor/health','http://127.0.0.1:8082/','http://127.0.0.1:4213/'):
    deadline=time.monotonic()+60
    while True:
        try:
            with urlopen(url,timeout=10) as response:
                if response.status==200:break
        except Exception:
            if time.monotonic()>deadline:raise RuntimeError('Local page did not become ready: '+url) from None
            time.sleep(2)
    print('Ready: '+url,flush=True)
