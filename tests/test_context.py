import json
import pytest
import httpx
from firebridge.db import connect
from firebridge.news import parse_feed
from firebridge.reports import import_reports
from firebridge.science import discover
from firebridge.http import FetchError


def test_news_dates_and_uncertainty():
    xml=b'''<rss><channel><item><title>Fire report</title><link>https://example.test/fire</link>
      <pubDate>Wed, 17 Jan 2024 14:00:00 +0100</pubDate></item></channel></rss>'''
    rows=parse_feed(xml,'Fixture publisher')
    assert rows[0]['published_at']=='2024-01-17T13:00:00+00:00'
    assert rows[0]['review_status']=='unreviewed' and rows[0]['events']==[]
    with pytest.raises(ValueError):parse_feed(b'<!DOCTYPE x [<!ENTITY xx "x">]><rss/>','Fixture')


@pytest.mark.integration
def test_report_correction_keeps_old_release(database,scope,tmp_path):
    path=tmp_path/'reports.json'
    record=dict(canonical_url='https://example.test/fire/'+scope,title='Fixture',publisher='Fixture',
     published_at='2024-01-20T10:00:00Z',publication_precision='timestamp',source_lineage='official_incident',
     review_status='reviewed',reviewed_by='test-reviewer',events=[dict(event_start='2024-01-17',event_end_exclusive='2024-01-18',
     date_precision='day',claim_summary='Fixture claim',location={'type':'Point','coordinates':[-5,35]},location_precision='approximate')])
    path.write_text(json.dumps([record]));a=import_reports(database,path,scope)
    record['title']='Corrected fixture';path.write_text(json.dumps([record]));b=import_reports(database,path,scope)
    with connect(database) as conn:
        old=conn.execute('SELECT title FROM serving.reports WHERE release_id=%s',(a['releases']['reports'],)).fetchone()
        new=conn.execute('SELECT title FROM serving.reports WHERE release_id=%s',(b['releases']['reports'],)).fetchone()
        assert old['title']=='Fixture' and new['title']=='Corrected fixture'
        event=conn.execute('SELECT event_start FROM serving.reported_events e JOIN serving.reports r ON r.id=e.report_id WHERE r.release_id=%s',(b['releases']['reports'],)).fetchone()
        assert str(event['event_start'])=='2024-01-17'


@pytest.mark.integration
def test_cmr_discovery_does_not_claim_masks_ready(database,scope):
    request=dict(collection_concept_id='C123-FIXTURE',scope_key=scope,bbox=[-6,34,-4,36],start='2024-01-17',end_exclusive='2024-01-18')
    entry=dict(id='G123-FIXTURE',time_start='2024-01-17T12:00:00Z',time_end='2024-01-17T12:05:00Z',updated='2024-01-18T00:00:00Z')
    with httpx.Client(transport=httpx.MockTransport(lambda r:httpx.Response(200,json={'feed':{'entry':[entry]}}))) as c:
        result=discover(database,request,client=c)
    assert result['catalogued']==1 and not result['masks_ready']
