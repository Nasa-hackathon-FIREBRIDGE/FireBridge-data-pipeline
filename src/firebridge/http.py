"""Bounded HTTP with redacted errors and a PostgreSQL-shared FIRMS budget."""
from datetime import timedelta
from email.utils import parsedate_to_datetime
import httpx
from .db import connect
from .util import now


class FetchError(Exception):
    def __init__(self, code, *, retry_seconds=60, blocked=False, http_status=None):
        super().__init__(code)
        self.code=code; self.retry_seconds=retry_seconds; self.blocked=blocked; self.http_status=http_status


def firms_slot(settings):
    with connect(settings) as conn:
        conn.execute("INSERT INTO provider_budgets(id,window_start) VALUES ('firms',now()) ON CONFLICT DO NOTHING")
        row=conn.execute("SELECT * FROM provider_budgets WHERE id='firms' FOR UPDATE").fetchone()
        clock=now()
        if row['blocked_until'] and row['blocked_until']>clock:
            raise FetchError("provider_cooldown",retry_seconds=int((row['blocked_until']-clock).total_seconds())+1)
        if row['window_start']+timedelta(minutes=10)<=clock:
            conn.execute("UPDATE provider_budgets SET window_start=now(),used=1 WHERE id='firms'")
        elif row['used']>=settings.firms_budget:
            raise FetchError("local_rate_budget",retry_seconds=int((row['window_start']+timedelta(minutes=10)-clock).total_seconds())+1)
        else:
            conn.execute("UPDATE provider_budgets SET used=used+1 WHERE id='firms'")


def get(settings, url, *, params=None, headers=None, client=None, firms=False):
    if firms: firms_slot(settings)
    own=client is None
    client=client or httpx.Client(timeout=httpx.Timeout(60,connect=15),follow_redirects=False)
    try:
        with client.stream('GET',url,params=params,headers=headers) as response:
            if response.status_code!=200:
                retry=60
                value=response.headers.get('retry-after','')
                try: retry=max(1,int(value))
                except ValueError:
                    try: retry=max(1,int((parsedate_to_datetime(value)-now()).total_seconds()))
                    except (ValueError,TypeError): pass
                # FIRMS also returns HTTP 400 for a depleted transaction quota.
                # Inspect only a bounded prefix; never persist its credential-bearing URL/body.
                quota = firms and response.status_code==429
                if firms and response.status_code==400:
                    prefix=next(response.iter_bytes(chunk_size=4096),b'').lower()
                    quota=b'exceeding allowed transaction limit' in prefix
                if quota:
                    retry=max(600,retry)
                    with connect(settings) as conn:
                        conn.execute("UPDATE provider_budgets SET blocked_until=GREATEST(blocked_until,%s) WHERE id='firms'",(now()+timedelta(seconds=retry),))
                    raise FetchError('provider_cooldown',retry_seconds=retry,http_status=response.status_code)
                raise FetchError(f"http_{response.status_code}",retry_seconds=retry,
                                 blocked=response.status_code in (401,403),http_status=response.status_code)
            if int(response.headers.get('content-length','0'))>settings.max_bytes: raise FetchError('payload_too_large',blocked=True)
            data=bytearray()
            for chunk in response.iter_bytes():
                data.extend(chunk)
                if len(data)>settings.max_bytes: raise FetchError('payload_too_large',blocked=True)
            return bytes(data),dict(response.headers)
    except httpx.HTTPError:
        # HTTP exception strings can contain the MAP_KEY in the URL.
        raise FetchError('network_error') from None
    finally:
        if own: client.close()
