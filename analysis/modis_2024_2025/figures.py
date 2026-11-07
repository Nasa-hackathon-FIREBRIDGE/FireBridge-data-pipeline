"""Standalone scientific figures for the exact MODIS analysis window."""
from pathlib import Path
import json
import numpy as np
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
from matplotlib.colors import LogNorm
from matplotlib.patches import Polygon, Rectangle
from matplotlib.ticker import FuncFormatter

ROOT=Path(__file__).resolve().parents[2]
OUT=ROOT/'reports/modis_2024_2025'
T=OUT/'tables'; F=OUT/'figures'; P=ROOT/'data/processed/modis_2024_2025'
COLORS={'Terra':'#AE671C','Aqua':'#087F8C'}
plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'axes.titlesize':17,
    'axes.labelsize':12,'figure.facecolor':'#FFFFFF','axes.spines.top':False,'axes.spines.right':False,
    'savefig.facecolor':'#FFFFFF'})
MANIFEST=[]

def read(name):return pd.read_csv(T/f'{name}.csv')
def save(fig,name,title,caption,tables):
    fig.savefig(F/name,dpi=170,bbox_inches='tight')
    fig.savefig(F/name.replace('.png','.pdf'),bbox_inches='tight')
    plt.close(fig)
    MANIFEST.append({'file':name,'title':title,'caption':caption,'tables':tables})

def basemap(ax):
    p=ROOT/'data/external/modis_2024_2025/ne_110m_admin_0_countries.geojson'
    if not p.exists():return
    for f in json.loads(p.read_text())['features']:
        geom=f['geometry'];parts=geom['coordinates']
        if geom['type']=='Polygon':parts=[parts]
        for poly in parts:
            ax.add_patch(Polygon(poly[0],facecolor='#EFEFEA',edgecolor='#8A918D',linewidth=.35,zorder=0))

def main():
    F.mkdir(parents=True,exist_ok=True)
    m=read('monthly');months=sorted(m.month.unique());x=np.arange(len(months))
    labels=[pd.Timestamp(s).strftime('%b\n%Y') if i in [0,12] else pd.Timestamp(s).strftime('%b') for i,s in enumerate(months)]
    fig,ax=plt.subplots(figsize=(11.5,5))
    for sat in ['Terra','Aqua']:
        g=m[m.satellite.eq(sat)].set_index('month').loc[months]
        ax.plot(x,g.detections_per_requested_calendar_day,marker='o',label=sat,color=COLORS[sat],lw=2.5)
    ax.set(xticks=x,xticklabels=labels,ylabel='Recorded detections / requested calendar day',title='Global detections peak in August in this window')
    ax.yaxis.set_major_formatter(FuncFormatter(lambda y,_:f'{y:,.0f}'))
    ax.grid(axis='y',alpha=.18);ax.legend(frameon=False)
    fig.subplots_adjust(bottom=.24)
    fig.text(.1,.015,'January 2024: 15 dates • January 2025: 17 dates • Point counts are not coverage-corrected fire rates',fontsize=10,color='#58616A')
    save(fig,'01_monthly_rates.png','Monthly recorded detection rates',
        'Exact counts divided by dates in the requested window; January endpoints are partial. These are exported detections per calendar day, not incidents or coverage-corrected occurrence rates.',['monthly.csv'])
    s=read('global_1degree_bins').groupby(['lon_bin','lat_bin']).rows.sum().reset_index()
    grid=np.zeros((180,360));grid[s.lat_bin.to_numpy()+90,s.lon_bin.to_numpy()+180]=s.rows
    fig,ax=plt.subplots(figsize=(12,5.5));basemap(ax)
    im=ax.imshow(np.ma.masked_equal(grid,0),extent=[-180,180,-90,90],origin='lower',
        cmap='inferno',norm=LogNorm(vmin=1,vmax=grid.max()),interpolation='nearest',aspect='auto',zorder=1)
    ax.set(xlim=(-180,180),ylim=(-65,85),xlabel='Longitude (degrees)',ylabel='Latitude (degrees)',title='Recorded Terra + Aqua detections worldwide')
    ax.add_patch(Rectangle((-6.4,34.5),1.9,1.4,fill=False,edgecolor='#20B4D1',lw=1.5,zorder=3))
    ax.annotate('FIREBRIDGE pilot',xy=(-5.4,35.4),xytext=(-49,51),arrowprops={'arrowstyle':'->','color':'#08678C'},fontsize=10,color='#08678C')
    fig.colorbar(im,ax=ax,shrink=.75,pad=.02,label='Detections in 1° × 1° bin (log scale)')
    save(fig,'02_global_map.png','Global detection geography',
        'All 4,876,343 detections aggregated exactly. Degree bins have unequal physical areas; color measures recorded counts, not fire risk or burned area. Natural Earth outlines provide coarse context only.',['global_1degree_bins.csv'])
    conf=read('confidence');fig,ax=plt.subplots(figsize=(9,4.5));base=np.zeros(2)
    for cls,color in [('low','#D2D5D7'),('nominal','#69A7AE'),('high','#174454')]:
        vals=np.array([conf.loc[conf.satellite.eq(s)&conf.confidence_class.eq(cls),'rows'].sum() for s in ['Terra','Aqua']])
        totals=np.array([conf.loc[conf.satellite.eq(s),'rows'].sum() for s in ['Terra','Aqua']]);pct=100*vals/totals
        ax.barh(['Terra','Aqua'],pct,left=base,color=color,label=cls.capitalize())
        for i,v in enumerate(pct):
            if v>7:ax.text(base[i]+v/2,i,f'{v:.1f}%',ha='center',va='center',color='white' if cls=='high' else '#153040',fontsize=12)
        base+=pct
    ax.set(xlim=(0,100),xlabel='Share of exported detections (%)',title='Most detections have nominal confidence')
    ax.legend(ncol=3,frameon=False,loc='upper center',bbox_to_anchor=(.5,-.16))
    save(fig,'03_confidence.png','Native confidence classes',
        'Low <30; nominal 30–79; high ≥80. Native confidence is not a calibrated probability of wildfire. All classes remain in the raw and EDA dataset.',['confidence.csv'])
    d=pd.read_parquet(P/'detections.parquet',columns=['satellite','frp'])
    fig,ax=plt.subplots(figsize=(10,4.5));edges=np.geomspace(.1,15000,90)
    for sat in ['Terra','Aqua']:
        vals=d.loc[d.satellite.eq(sat)&d.frp.gt(0),'frp']
        hist,_=np.histogram(vals,bins=edges)
        ax.stairs(hist/len(vals)*100,edges,label=sat,color=COLORS[sat],lw=2)
    ax.set_xscale('log');ax.set(xlabel='Fire radiative power (MW, logarithmic scale)',ylabel='Positive-FRP detections per bin (%)',title='FRP has a long tail; the median is below the mean')
    ax.legend(frameon=False);ax.grid(alpha=.16)
    save(fig,'04_frp_distribution.png','FRP distribution',
        'Exact histogram over positive FRP; 2,425 zero-FRP rows are flagged separately and retained. FRP is instantaneous radiative power per detected pixel, not burned hectares or total energy.',['platform_summary.csv','exact_quantiles.csv'])
    timing=read('solar_hour_bins');fig,ax=plt.subplots(figsize=(11,4.5))
    for sat in ['Terra','Aqua']:
        for dn in ['D','N']:
            g=timing[timing.satellite.eq(sat)&timing.daynight.eq(dn)].set_index('solar_hour_bin')['rows'].reindex(range(24),fill_value=0)
            ax.plot(np.arange(24)+.5,g/g.sum()*100,color=COLORS[sat],linestyle='-' if dn=='D' else '--',
                label=f'{sat} {"day" if dn=="D" else "night"}',lw=2)
    ax.set(xticks=range(0,25,2),xlim=(0,24),xlabel='Approximate local mean solar hour',ylabel='Share within platform + day/night (%)',title='Terra and Aqua sample different parts of the day')
    ax.grid(alpha=.16);ax.legend(frameon=False,ncol=2)
    save(fig,'05_solar_time.png','Observed hotspot timing',
        'UTC + longitude/15 modulo 24, without equation-of-time correction. Distribution is conditional on exported hotspots; it is not a full orbit coverage schedule.',['solar_hour_bins.csv','platform_daynight_summary.csv'])
    hemi=read('hemisphere_monthly').groupby(['month','hemisphere']).rows.sum().reset_index()
    denominators=m.drop_duplicates('month').set_index('month').days_in_requested_window
    fig,ax=plt.subplots(figsize=(11,4.5))
    for hem,color in [('Northern','#446C89'),('Southern','#965B80')]:
        g=hemi[hemi.hemisphere.eq(hem)].set_index('month').reindex(months)
        ax.plot(x,g.rows/denominators.loc[months],marker='o',label=hem,color=color,lw=2.3)
    ax.set(xticks=x,xticklabels=labels,ylabel='Recorded detections / requested calendar day',title='The global total combines different regional seasons')
    ax.legend(frameon=False);ax.grid(axis='y',alpha=.16)
    save(fig,'06_hemisphere_seasons.png','Hemisphere contributions',
        'Both platforms combined, split at latitude 0°. These broad descriptive groups do not isolate climate, land use, observation coverage or causal drivers.',['hemisphere_monthly.csv','monthly.csv'])
    pilot=pd.read_parquet(P/'pilot.parquet');fig,ax=plt.subplots(figsize=(11,4.5))
    for i,sat in enumerate(['Terra','Aqua']):
        counts=pilot[pilot.satellite.eq(sat)&pilot.vegetation_retained].groupby('month',observed=True).size().reindex(months,fill_value=0)
        ax.bar(x+(i-.5)*.34,counts,width=.34,color=COLORS[sat],label=sat)
    ax.set(xticks=x,xticklabels=labels,ylabel='Type 0 detections with confidence ≥30',title='Northern Morocco pilot: a small candidate dataset')
    ax.legend(frameon=False);ax.grid(axis='y',alpha=.16)
    save(fig,'07_pilot_calendar.png','Pilot monthly point calendar',
        'Blueprint rectangle: west −6.4°, south 34.5°, east −4.5°, north 35.9°. A zero means no exported retained point, not an eligible negative observation. Only 49 candidate detections remain after type/confidence filtering.',['pilot_detections.csv','regional_summary.csv'])
    fig,ax=plt.subplots(figsize=(8,6));basemap(ax)
    for sat in ['Terra','Aqua']:
        g=pilot[pilot.satellite.eq(sat)]
        ax.scatter(g.longitude,g.latitude,label=f'{sat}: {len(g)} detections',s=40,color=COLORS[sat],alpha=.7,edgecolor='white',lw=.4,zorder=2)
    ax.add_patch(Rectangle((-6.4,34.5),1.9,1.4,fill=False,edgecolor='#17354A',lw=1.5,zorder=3))
    ax.set(xlim=(-7, -3.8),ylim=(34,36.3),xlabel='Longitude (degrees)',ylabel='Latitude (degrees)',title='Blueprint pilot rectangle, all native detections')
    ax.legend(frameon=False);ax.set_aspect(1/np.cos(np.deg2rad(35)))
    save(fig,'08_pilot_map.png','Pilot point locations',
        '57 detections in the entire requested period. The rectangle is a study window; it includes no reviewed land mask or administrative clip. Symbols are pixel centers, not fire boundaries.',['pilot_detections.csv'])
    footprint=pd.read_parquet(P/'firms_january_overlap.parquet',columns=['satellite','scan','track'])
    fig,axs=plt.subplots(1,2,figsize=(11,4.5))
    for sat in ['Terra','Aqua']:
        g=footprint[footprint.satellite.eq(sat)]
        for ax,field in zip(axs,['scan','track']):
            vals=g[field];edges=np.arange(.95,4.96,.1) if field=='scan' else np.arange(.95,2.16,.1)
            hist,_=np.histogram(vals,bins=edges)
            ax.stairs(hist/len(vals)*100,edges,color=COLORS[sat],lw=2,label=sat)
            ax.set(xlabel=f'{field.capitalize()} dimension (km)',ylabel='Detections per bin (%)');ax.grid(alpha=.16)
    axs[0].legend(frameon=False);fig.suptitle('Actual pixel sizes vary across the swath',fontsize=17)
    save(fig,'09_footprint_january.png','January footprint distributions',
        'FIRMS overlap January 1–17, 2025 only, 202,406 rows. Full-year MCD14ML instead provides sample index 0–1353; explicit scan/track are absent. Pixel footprint is not burning/burned area.',['january_footprint_summary.csv','january_overlap_differences.csv'])
    sens=read('confidence_sensitivity');fig,ax=plt.subplots(figsize=(8,4.5))
    for sat in ['Terra','Aqua']:
        g=sens[sens.satellite.eq(sat)]
        ax.plot(g.confidence_threshold,100*g.kept_fraction,marker='o',color=COLORS[sat],label=sat,lw=2.5)
    ax.set(xticks=[0,30,50,80,90],ylim=(0,105),xlabel='Minimum native confidence',ylabel='All-type detections retained (%)',title='A stricter confidence rule changes the calendar')
    ax.legend(frameon=False);ax.grid(alpha=.16)
    save(fig,'10_confidence_sensitivity.png','Confidence threshold sensitivity',
        'Thresholds are analysis choices. A stricter filter removes many exported detections and does not turn the retained sample into verified wildfire ground truth.',['confidence_sensitivity.csv'])
    sample=pd.read_parquet(P/'scatter_sample.parquet');fig,axs=plt.subplots(1,2,figsize=(11,4.5),sharey=True)
    for ax,sat in zip(axs,['Terra','Aqua']):
        g=sample[sample.satellite.eq(sat)&sample.frp.gt(0)]
        ax.scatter(g.brightness,g.frp,s=3,alpha=.15,color=COLORS[sat],rasterized=True)
        ax.set(yscale='log',xlabel='Band 21/22 brightness temperature (K)',title=sat)
        ax.grid(alpha=.14)
    axs[0].set_ylabel('FRP (MW, log scale)');fig.suptitle('Thermal signal and FRP are related detector outputs',fontsize=17)
    save(fig,'11_thermal_frp.png','Thermal signal scatter',
        'Uniform reproducible 40,000-row sample for visualization, seed 20241017. Correlation tables use the full type-0 population, split by native day/night; relationships are not causal evidence or flame temperatures.',['type0_spearman.csv'])
    (OUT/'figure_manifest.json').write_text(json.dumps(MANIFEST,indent=2))
    print(f'Wrote {len(MANIFEST)} scientific figures',flush=True)

if __name__=='__main__':main()
