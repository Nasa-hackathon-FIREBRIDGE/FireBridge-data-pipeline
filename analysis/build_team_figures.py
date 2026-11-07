"""Two simple descriptive charts for the team walkthrough, from verified EDA tables."""
from pathlib import Path
import pandas as pd
import numpy as np
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]
OUT=ROOT/'reports/team_figures';OUT.mkdir(exist_ok=True)

def main():
    plt.rcParams.update({'font.family':'DejaVu Sans','font.size':12,'axes.spines.top':False,'axes.spines.right':False,'axes.spines.left':False,'axes.edgecolor':'#d5dedb','text.color':'#203833','axes.labelcolor':'#203833','xtick.color':'#526660','ytick.color':'#203833'})
    data=pd.read_csv(ROOT/'reports/tables/pilot_platform_year.csv')
    names={'Aqua':'Aqua · MODIS','Terra':'Terra · MODIS','SNPP':'S-NPP · VIIRS','N20':'NOAA-20 · VIIRS','N21':'NOAA-21 · VIIRS (provisional)'}
    order=['Aqua','Terra','SNPP','N20','N21']
    values=data[data.year==2025].set_index('satellite').loc[order,'rows']
    fig,ax=plt.subplots(figsize=(9.2,3.6));fig.patch.set_facecolor('#ffffff');ax.set_facecolor('#ffffff')
    bars=ax.barh([names[s] for s in order],values,color=['#bb6643','#bb6643','#237e75','#237e75','#779c96'],height=.58)
    ax.invert_yaxis();ax.set_xlim(0,480);ax.set_xlabel('Hotspot detection rows in the pilot, 2025');ax.grid(axis='x',alpha=.18);ax.set_axisbelow(True);ax.tick_params(axis='y',length=0,pad=12)
    for b,v in zip(bars,values):ax.text(v+7,b.get_y()+b.get_height()/2,str(v),va='center',weight='bold')
    fig.tight_layout();fig.savefig(OUT/'2025_sensor_counts.png',dpi=160,bbox_inches='tight');plt.close(fig)
    d=pd.read_csv(ROOT/'reports/tables/pilot_monthly.csv');d=d[d.satellite.eq('SNPP')]
    fig,ax=plt.subplots(figsize=(9.2,3.6));x=np.arange(12);width=.34
    for i,(year,color) in enumerate([(2024,'#b5c9c3'),(2025,'#237e75')]):
        g=d[d.year.eq(year)].set_index('month').rows.reindex(range(1,13),fill_value=0)
        ax.bar(x+(i-.5)*width,g,width,label=str(year),color=color)
    ax.set_xticks(x,['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec']);ax.set_ylabel('Hotspot detection rows');ax.grid(axis='y',alpha=.18);ax.set_axisbelow(True);ax.legend(frameon=False,ncols=2,loc='upper left');ax.tick_params(axis='both',length=0)
    fig.tight_layout();fig.savefig(OUT/'snpp_monthly_counts.png',dpi=160,bbox_inches='tight');plt.close(fig)
    print('Team figures built from pilot_platform_year.csv and pilot_monthly.csv')

if __name__=='__main__':main()
