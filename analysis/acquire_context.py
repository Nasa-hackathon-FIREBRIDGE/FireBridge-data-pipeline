"""Public metadata discovery and small ORNL MODIS subsets. No credentials stored.

The center sample is illustrative (20 x 20 km requested), not an AOI aggregate.
CMR results are candidates only: actual footprints and paired geolocation need QA.
"""
from pathlib import Path
from concurrent.futures import ThreadPoolExecutor
from urllib.request import urlopen, Request
from urllib.parse import urlencode
import json, hashlib, datetime, time

ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/external'
OUT.mkdir(parents=True,exist_ok=True)
MANIFEST=[]

def fetch(name,url,kind='metadata',limit=30_000_000):
    p=OUT/name
    entry={'name':name,'url':url,'kind':kind,'retrieved_utc':datetime.datetime.now(datetime.timezone.utc).isoformat()}
    try:
        if p.exists():data=p.read_bytes();entry['cached']=True
        else:
            with urlopen(Request(url,headers={'User-Agent':'FIREBRIDGE-EDA/1.0'}),timeout=60) as r:
                entry['http_status']=r.status;data=r.read(limit+1)
            if len(data)>limit:raise ValueError('Bounded sample size exceeded')
            p.write_bytes(data)
        entry.update(status='downloaded',bytes=len(data),sha256=hashlib.sha256(data).hexdigest())
        print('DOWNLOADED',name,len(data),flush=True)
        return data
    except Exception as e:
        entry.update(status='unavailable',error=str(e)[:300]);print('UNAVAILABLE',name,str(e)[:120],flush=True)
        return None
    finally:MANIFEST.append(entry)

def discover(product):
    api='https://cmr.earthdata.nasa.gov/search/'
    raw=fetch(f'cmr_{product}_collections.json',api+'collections.json?'+urlencode({'short_name':product,'page_size':50}))
    if not raw:return
    candidates=json.loads(raw)['feed']['entry']
    versions={'MYD14':['061'],'MYD03':['61','6.1'],'VNP14IMG':['002'],'VNP03IMG':['2'],
              'VJ114IMG':['002'],'VJ103IMG':['2.1'],'MOD14':['061'],'MCD12Q1':['061'],'MCD64A1':['061']}
    chosen=[c for c in candidates if c.get('version_id') in versions[product] and 'NRT' not in c.get('version_id','')]
    for c in chosen[:2]:
        temporal='2025-07-14T00:00:00Z,2025-07-20T23:59:59Z'
        if product=='MCD12Q1':temporal='2024-01-01T00:00:00Z,2024-12-31T23:59:59Z'
        params={'collection_concept_id':c['id'],'bounding_box':'-6.4,34.5,-4.5,35.9','temporal':temporal,'page_size':2000,'sort_key':'start_date'}
        fetch(f'cmr_{product}_{c["id"]}_granules.json',api+'granules.json?'+urlencode(params))

def ornl(product,start,end):
    base=f'https://modis.ornl.gov/rst/api/v1/{product}/'
    dates=fetch(f'ornl_{product}_dates.json',base+'dates?'+urlencode({'latitude':35.2,'longitude':-5.45}))
    fetch(f'ornl_{product}_bands.json',base+'bands')
    if not dates:return
    available=[d for d in json.loads(dates)['dates'] if start<=d['calendar_date']<=end]
    if not available:
        print('NO DATES',product,start,end,flush=True);return
    selected=available[:1]
    params={'latitude':35.2,'longitude':-5.45,'startDate':selected[0]['modis_date'],'endDate':selected[-1]['modis_date'],'kmAboveBelow':10,'kmLeftRight':10}
    fetch(f'ornl_{product}_sample.json',base+'subset?'+urlencode(params),'science_subset')

def main():
    products=['MYD14','MYD03','VNP14IMG','VNP03IMG','VJ114IMG','VJ103IMG','MOD14','MCD12Q1','MCD64A1']
    with ThreadPoolExecutor(max_workers=3) as pool:list(pool.map(discover,products))
    ornl('MCD12Q1','2024-01-01','2024-12-31')
    ornl('MCD64A1','2025-07-01','2025-07-31')
    docs={
      'firms_readme.txt':'https://firms.modaps.eosdis.nasa.gov/download/Readme.txt',
      'firms_attributes.html':'https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs',
      'viirs_c2_guide.pdf':'https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf',
      'modis_c61_guide.pdf':'https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf',
      'effis_data_services.html':'https://forest-fire.emergency.copernicus.eu/applications/data-and-services',
      'cds_api_access.html':'https://cds.climate.copernicus.eu/how-to-api',
      'ornl_webservice.html':'https://modis.ornl.gov/data/modis_webservice.html',
      'landsat_faq.html':'https://forum.earthdata.nasa.gov/viewtopic.php?t=5197',
      'effis_country_totals_2024.xlsx':'https://forest-fire.emergency.copernicus.eu/effis/applications/data-and-services/report_2024.xlsx'}
    for name,url in docs.items():fetch(name,url,'documentation')
    (ROOT/'reports/tables/download_manifest.json').write_text(json.dumps(MANIFEST,indent=2))

if __name__=='__main__':main()
