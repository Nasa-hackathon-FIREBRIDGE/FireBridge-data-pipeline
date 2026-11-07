"""Download bounded NASA samples when EARTHDATA_TOKEN is available.

Defaults: two context tiles + one near-time daytime Aqua/S-NPP fire/geolocation
quartet from the predeclared week. Catalog candidates are not assumed land coverage.
Credentials are read locally and never logged or written to the manifest.
"""
from pathlib import Path
from urllib.parse import urlparse
import datetime,json,os,hashlib,re
import requests
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'data/external/science';OUT.mkdir(parents=True,exist_ok=True)

def token():
    value=os.getenv('EARTHDATA_TOKEN','')
    if value:return value
    p=ROOT/'.env'
    if p.exists():
        for line in p.read_text().splitlines():
            if line.strip().startswith('EARTHDATA_TOKEN='):return line.split('=',1)[1].strip().strip('\"\'')
    return ''

def inventory():
    rows=[]
    for p in sorted((ROOT/'data/external').glob('cmr_*_granules.json')):
        product=p.name.split('_')[1]
        for e in json.loads(p.read_text())['feed']['entry']:
            links=[l['href'] for l in e.get('links',[]) if l.get('href','').startswith('https://') and urlparse(l['href']).path.endswith(('.nc','.hdf')) and not l.get('inherited',False)]
            if not links:continue
            u=links[0];name=urlparse(u).path.rsplit('/',1)[-1]
            match=re.search(r'\.A(\d{7})\.(\d{4})\.',name)
            rows.append({'product':product,'granule_id':e.get('producer_granule_id',e['title']),'concept_id':e['id'],
                         'filename':name,'url':u,'acquisition_key':'.'.join(match.groups()) if match else None,
                         'time_start':e.get('time_start'),'time_end':e.get('time_end'),'size_MB_catalog':float(e.get('granule_size',0)),
                         'metadata_source':p.name,'links':e.get('links',[]),'collection_concept_id':e.get('collection_concept_id')})
    return rows

def choose(rows):
    selected=[r for r in rows if r['product'] in ['MCD12Q1','MCD64A1']]
    aqua=[r for r in rows if r['product']=='MYD14' and r['acquisition_key'] and 10<=int(r['acquisition_key'].split('.')[1][:2])<=17]
    viirs=[r for r in rows if r['product']=='VNP14IMG' and r['acquisition_key'] and 10<=int(r['acquisition_key'].split('.')[1][:2])<=17]
    options=[]
    for a in aqua:
        for b in viirs:
            at=datetime.datetime.strptime(a['acquisition_key'],'%Y%j.%H%M');bt=datetime.datetime.strptime(b['acquisition_key'],'%Y%j.%H%M')
            gap=abs((at-bt).total_seconds())/60
            if gap<=60:options.append((gap,a['acquisition_key'],a,b))
    if options:
        _,_,a,b=min(options,key=lambda x:(x[0],x[1]));selected +=[a,b]
        for fire,geo in [(a,'MYD03'),(b,'VNP03IMG')]:
            companions=[r for r in rows if r['product']==geo and r['acquisition_key']==fire['acquisition_key']]
            if len(companions)==1:selected+=companions
    return selected

def main():
    rows=inventory();selected=choose(rows)
    (ROOT/'reports/tables/science_granule_inventory.json').write_text(json.dumps(rows,indent=2))
    (ROOT/'reports/tables/science_sample_plan.json').write_text(json.dumps(selected,indent=2))
    credential=token();manifest=[]
    for r in selected:
        dest=OUT/r['filename'];record={k:v for k,v in r.items() if k!='links'}
        if not credential and not dest.exists():record['status']='requires_Earthdata_token';manifest.append(record);continue
        if not urlparse(r['url']).hostname.endswith('.nasa.gov'):raise ValueError('Unexpected credential destination')
        try:
            if not dest.exists():
                if r['size_MB_catalog']>220:raise ValueError('Individual file exceeds 220 MB sample limit')
                with requests.get(r['url'],headers={'Authorization':'Bearer '+credential},stream=True,timeout=(20,90)) as response:
                    record['http_status']=response.status_code
                    if response.status_code!=200:raise RuntimeError(f'HTTP {response.status_code}')
                    temp=dest.with_suffix(dest.suffix+'.partial');total=0
                    with temp.open('wb') as f:
                        for block in response.iter_content(1024*1024):
                            total+=len(block)
                            if total>240_000_000:raise RuntimeError('Bounded sample size exceeded')
                            f.write(block)
                    with temp.open('rb') as f:magic=f.read(8)
                    if not (magic.startswith(b'\x0e\x03\x13\x01') or magic==b'\x89HDF\r\n\x1a\n'):raise RuntimeError('Response is not HDF4/HDF5 science data')
                    temp.replace(dest)
            h=hashlib.sha256()
            with dest.open('rb') as f:
                for b in iter(lambda:f.read(1024*1024),b''):h.update(b)
            record.update(status='downloaded',bytes=dest.stat().st_size,sha256=h.hexdigest(),retrieved_utc=datetime.datetime.now(datetime.timezone.utc).isoformat())
            print('DOWNLOADED',dest.name,dest.stat().st_size,flush=True)
        except Exception as e:record.update(status='failed',error=type(e).__name__+': '+str(e)[:100]);print('FAILED',dest.name,record['error'],flush=True)
        manifest.append(record)
        (ROOT/'reports/tables/science_download_manifest.json').write_text(json.dumps(manifest,indent=2))
    (ROOT/'reports/tables/science_download_manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Selected',len(selected),'files;',round(sum(x['size_MB_catalog'] for x in selected),1),'catalog MB; token configured:',bool(credential),flush=True)

if __name__=='__main__':main()
