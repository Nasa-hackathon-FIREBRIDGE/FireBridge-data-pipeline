"""Stream every local FIRMS archive; retain exact regional rows and global summaries.

No input is modified. Global row duplicates are screened by 64-bit pandas hashes
(not asserted collision-free). Regional duplicate verification uses full columns.
"""
from pathlib import Path
from collections import Counter
import argparse, hashlib, json, time, zipfile, zlib
import numpy as np
import pandas as pd

ROOT = Path(__file__).resolve().parents[1]
REGIONS = {'pilot': [-6.4, 34.5, -4.5, 35.9],
           'morocco_context_rectangle': [-13.5, 27, -0.9, 36.1],
           'southern_spain_rectangle': [-7.5, 36, -1, 38.5]}
NUMERIC = ['latitude', 'longitude', 'brightness', 'bright_t31', 'frp', 'scan', 'track']
CATEGORIES = ['satellite','instrument','confidence','version','daynight','type']

def sha256(path):
    h = hashlib.sha256()
    with open(path,'rb') as f:
        for b in iter(lambda:f.read(8*1024*1024),b''): h.update(b)
    return h.hexdigest()

def save_json(path, obj):
    path.write_text(json.dumps(obj, indent=2, default=lambda x: x.item() if hasattr(x,'item') else str(x)))

def profile(path, out, chunk_size):
    t = time.monotonic()
    cache = out / path.stem
    cache.mkdir(parents=True, exist_ok=True)
    stat = path.stat()
    signature = {'bytes':stat.st_size,'mtime_ns':stat.st_mtime_ns}
    if (cache/'profile.json').exists():
        old = json.loads((cache/'profile.json').read_text())
        if old.get('signature') == signature:
            print('CACHED',path.name,flush=True)
            return old
    print('START',path.name,flush=True)
    info = dict(archive=path.name, path=str(path), signature=signature,
                sha256=sha256(path), rows=0, missing={}, categories={}, numeric={},
                invalid=Counter(), regions=Counter(), region_bounds=REGIONS)
    hashes=[]; regional=[]; daily=[]; spatial=[]; sample=None
    rng=np.random.default_rng(20260926)
    with zipfile.ZipFile(path) as z:
        members=[m for m in z.infolist() if m.filename.endswith('.csv')]
        if len(members)!=1: raise ValueError(f'Expected one CSV in {path}')
        member=members[0]
        info.update(member=member.filename,uncompressed_bytes=member.file_size,crc32=f'{member.CRC:08x}',
                    stream='NRT' if 'fire_nrt_' in member.filename else 'standard')
        with z.open(member) as f:
            for chunk_id,raw in enumerate(pd.read_csv(f,dtype=str,chunksize=chunk_size)):
                columns=list(raw.columns)
                hashes.append(pd.util.hash_pandas_object(raw,index=False).to_numpy())
                raw['source_row']=np.arange(info['rows']+2,info['rows']+2+len(raw))
                info['rows']+=len(raw)
                for c in columns:
                    info['missing'][c]=info['missing'].get(c,0)+int(raw[c].isna().sum())
                for c in CATEGORIES:
                    if c not in raw:continue
                    dest=info['categories'].setdefault(c,Counter())
                    dest.update(raw[c].fillna('<missing>').value_counts().to_dict())
                df=raw.copy()
                for c in NUMERIC:
                    if c not in df: continue
                    x=pd.to_numeric(df[c],errors='coerce');df[c]=x
                    finite=x[np.isfinite(x)]
                    info['invalid'][c+'_non_numeric']=info['invalid'].get(c+'_non_numeric',0)+int((raw[c].notna()&x.isna()).sum())
                    info['invalid'][c+'_non_finite']=info['invalid'].get(c+'_non_finite',0)+int((x.notna()&~np.isfinite(x)).sum())
                    d=info['numeric'].setdefault(c,{'n':0,'sum':0.,'min':None,'max':None,'zero':0,'negative':0})
                    if len(finite):
                        d['n']+=len(finite);d['sum']+=float(finite.sum());d['zero']+=int((finite==0).sum());d['negative']+=int((finite<0).sum())
                        d['min']=float(finite.min()) if d['min'] is None else min(d['min'],float(finite.min()))
                        d['max']=float(finite.max()) if d['max'] is None else max(d['max'],float(finite.max()))
                date=pd.to_datetime(df.acq_date,format='%Y-%m-%d',errors='coerce')
                tm=df.acq_time.fillna('').str.zfill(4)
                hh=pd.to_numeric(tm.str[:2],errors='coerce');mm=pd.to_numeric(tm.str[2:],errors='coerce')
                valid_time=tm.str.fullmatch(r'\d{4}')&hh.between(0,23)&mm.between(0,59)
                valid_coords=df.latitude.between(-90,90)&df.longitude.between(-180,180)
                info['invalid'].update({'coordinates':int((~valid_coords).sum()),'dates':int(date.isna().sum()),
                                        'times':int((~valid_time).sum()),'daynight':int((~df.daynight.isin(['D','N'])).sum())})
                valid_date=date.dropna()
                if len(valid_date):
                    lo=valid_date.min().strftime('%Y-%m-%d');hi=valid_date.max().strftime('%Y-%m-%d')
                    info['date_min']=min(info.get('date_min',lo),lo); info['date_max']=max(info.get('date_max',hi),hi)
                keys=['acq_date','satellite','daynight']
                dc=df.groupby(keys,dropna=False).size().rename('rows').reset_index();daily.append(dc)
                s=df.loc[valid_coords,['latitude','longitude']].copy()
                s['lat_bin']=np.floor(s.latitude).astype(int);s['lon_bin']=np.floor(s.longitude).astype(int)
                spatial.append(s.groupby(['lat_bin','lon_bin']).size().rename('rows').reset_index())
                union=pd.Series(False,index=df.index)
                for region,(w,so,e,n) in REGIONS.items():
                    hit=df.longitude.between(w,e)&df.latitude.between(so,n)
                    info['regions'][region]+=int(hit.sum());union|=hit
                if union.any():
                    reg=df.loc[union].copy();reg['archive']=path.name;reg['member']=member.filename;reg['stream']=info['stream']
                    regional.append(reg)
                # Uniform random-priority reservoir across the entire file, not first-N rows.
                priority=rng.random(len(df)); take=np.argpartition(priority,min(20000,len(df))-1)[:20000]
                pick=df.iloc[take].copy();pick['_priority']=priority[take]
                sample=pick if sample is None else pd.concat([sample,pick],ignore_index=True)
                sample=sample.nsmallest(20000,'_priority')
                if chunk_id%10==0:print('PROGRESS',path.name,info['rows'],flush=True)
        info['zip_crc_verified']=True  # ZipExtFile checks CRC on fully reading the member.
    h=np.concatenate(hashes);h.sort()
    info['duplicate_row_hash_excess']=int((h[1:]==h[:-1]).sum())
    del h,hashes
    for c,d in info['numeric'].items():
        d['mean']=d['sum']/d['n'] if d['n'] else None
        qs=sample[c].quantile([.01,.25,.5,.75,.95,.99]).to_dict()
        d['sample_quantiles']={str(k):float(v) for k,v in qs.items()}
    info['quantile_sample_rows']=len(sample)
    info['schema']=columns
    daily_df=pd.concat(daily).groupby(['acq_date','satellite','daynight'],dropna=False)['rows'].sum().reset_index()
    daily_df.to_parquet(cache/'daily.parquet',index=False)
    pd.concat(spatial).groupby(['lat_bin','lon_bin'])['rows'].sum().reset_index().to_parquet(cache/'spatial.parquet',index=False)
    sample.drop(columns='_priority').to_parquet(cache/'global_sample.parquet',index=False)
    if regional:pd.concat(regional,ignore_index=True).to_parquet(cache/'regional.parquet',index=False)
    info['days_with_any_global_detection']=int(daily_df.acq_date.nunique())
    info['elapsed_seconds']=round(time.monotonic()-t,2)
    save_json(cache/'profile.json',info)
    print('DONE',path.name,info['rows'],'regional',dict(info['regions']),'seconds',info['elapsed_seconds'],flush=True)
    return info

def main():
    parser=argparse.ArgumentParser();parser.add_argument('--input',type=Path,default=Path('/home/da-rog/Downloads/nasa hackathon data'))
    parser.add_argument('--chunk-size',type=int,default=200000)
    args=parser.parse_args();out=ROOT/'data/processed/archive_profiles';out.mkdir(parents=True,exist_ok=True)
    profiles=[profile(p,out,args.chunk_size) for p in sorted(args.input.glob('*.zip'))]
    save_json(ROOT/'reports/tables/archive_profiles.json',profiles)
    # Extracted CSVs are inventoried separately and never ingested a second time.
    copies=[]
    for p in args.input.rglob('*.csv'):
        crc=0
        with p.open('rb') as f:
            for b in iter(lambda:f.read(8*1024*1024),b''):crc=zlib.crc32(b,crc)
        matches=[x['archive'] for x in profiles if x['member']==p.name and x['uncompressed_bytes']==p.stat().st_size and x['crc32']==f'{crc:08x}']
        copies.append({'path':str(p),'bytes':p.stat().st_size,'crc32':f'{crc:08x}','matching_archives':matches,'ingested':False})
    save_json(ROOT/'reports/tables/extracted_copies.json',copies)
    frames=[pd.read_parquet(p) for p in out.glob('*/regional.parquet')]
    regional=pd.concat(frames,ignore_index=True)
    regional.to_parquet(ROOT/'data/processed/regional_detections_raw.parquet',index=False)
    print('ALL ARCHIVES COMPLETE',sum(p['rows'] for p in profiles),'rows',flush=True)

if __name__=='__main__':main()
