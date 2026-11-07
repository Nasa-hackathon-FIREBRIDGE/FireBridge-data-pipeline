"""Approved publisher RSS/Atom metadata. It is a partial discovery feed, not an incident census."""
from dataclasses import replace
from datetime import datetime
from email.utils import parsedate_to_datetime
import json
import os
from urllib.parse import urlparse
import xml.etree.ElementTree as ET
from .db import connect
from .http import get,FetchError
from .ingest import assert_lease
from .reports import import_reports
from .store import Store
from .util import utc


def parse_feed(body,publisher):
    if b'<!DOCTYPE' in body.upper() or b'<!ENTITY' in body.upper():raise ValueError('XML entities are not permitted')
    root=ET.fromstring(body)
    atom='{http://www.w3.org/2005/Atom}'
    if root.tag=='rss':entries=root.findall('./channel/item');kind='rss'
    elif root.tag==atom+'feed':entries=root.findall(atom+'entry');kind='atom'
    else:raise ValueError('Unexpected RSS/Atom root')
    if len(entries)>1000:raise ValueError('Feed item limit exceeded')
    result=[]
    for entry in entries:
        if kind=='rss':
            title=entry.findtext('title','');url=entry.findtext('link','');date=entry.findtext('pubDate','')
        else:
            title=entry.findtext(atom+'title','');date=entry.findtext(atom+'published','') or entry.findtext(atom+'updated','')
            link=next((x for x in entry.findall(atom+'link') if x.get('rel','alternate')=='alternate'),None)
            url=link.get('href','') if link is not None else ''
        if not title or urlparse(url).scheme!='https':continue
        published=None
        if date:
            try:
                value=parsedate_to_datetime(date) if kind=='rss' else datetime.fromisoformat(date.replace('Z','+00:00'))
                if value.tzinfo is not None:published=utc(value).isoformat()
            except (ValueError,TypeError):pass
        result.append(dict(canonical_url=url,title=title[:1000],publisher=publisher,published_at=published,
          publication_precision='timestamp' if published else 'unknown',language='und',source_lineage='unknown',
          review_status='unreviewed',events=[]))
    # A feed can repeat a link within one response; the last entry is its current metadata.
    return list({r['canonical_url']:r for r in result}.values())


def fetch_news(settings,request,task=None,client=None):
    url=request['url'];parsed=urlparse(url)
    allowed={h.strip().lower() for h in os.getenv('FIREBRIDGE_NEWS_ALLOWED_HOSTS','').split(',') if h.strip()}
    if parsed.scheme!='https' or parsed.hostname not in allowed or parsed.username or parsed.password or parsed.port not in (None,443):
        raise FetchError('news_host_not_approved',blocked=True)
    body,_=get(replace(settings,max_bytes=min(settings.max_bytes,2*1024*1024)),url,client=client)
    raw=Store(settings.data_dir).put([body],'.xml')
    try:records=parse_feed(body,request['publisher'])
    except (ValueError,ET.ParseError):raise FetchError('invalid_news_feed',blocked=True) from None
    if not records:return {'reports':0,'coverage':'partial_feed','raw_uri':str(raw.path)}
    structured=Store(settings.data_dir).json(records)
    result=import_reports(settings,structured.path,request['scope_key'],origin=url,task=task)
    return dict(result,coverage='partial_feed',raw_uri=str(raw.path),spatial_association='unreviewed')
