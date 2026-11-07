"""Normalize the downloaded EFFIS workbook without treating blanks as zeros."""
from pathlib import Path
import json,re,zipfile,xml.etree.ElementTree as ET
import pandas as pd
import matplotlib
matplotlib.use('Agg')
import matplotlib.pyplot as plt
ROOT=Path(__file__).resolve().parents[1]

def main():
    from build_eda import parse_effis
    sheets=parse_effis();rows=[]
    with zipfile.ZipFile(ROOT/'data/external/effis_country_totals_2024.xlsx') as z:
        ns={'m':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
        names=[e.get('name') for e in ET.fromstring(z.read('xl/workbook.xml')).findall('m:sheets/m:sheet',ns)]
    for sheet,name,metric in zip(sheets,names,['burnt_area_ha','reported_forest_fires']):
        headers={re.sub(r'\d','',k):v for k,v in sheet['rows'][0].items()}
        for row in sheet['rows'][1:]:
            cells={re.sub(r'\d','',k):v for k,v in row.items()}
            if not str(cells.get('A','')).isdigit():continue
            for col,country in headers.items():
                if col=='A':continue
                raw=str(cells.get(col,''));clean=re.sub(r'\s','',raw).replace(',','')
                value=float(clean) if re.fullmatch(r'\d+(\.\d+)?',clean) else None
                rows.append({'year':int(cells['A']),'country':country,'metric':metric,'value':value,'raw_value':raw,'source_sheet':name})
    d=pd.DataFrame(rows);d.to_csv(ROOT/'reports/tables/effis_country_totals.csv',index=False)
    selection=d[d.country.isin(['MAR','ESP'])].pivot(index=['country','year'],columns='metric',values='value').reset_index()
    selection.to_csv(ROOT/'reports/tables/effis_morocco_spain.csv',index=False)
    fig,axes=plt.subplots(2,2,figsize=(13,7),sharex=True)
    for i,country in enumerate(['MAR','ESP']):
        g=selection[selection.country==country]
        for j,metric in enumerate(['burnt_area_ha','reported_forest_fires']):
            ax=axes[i,j];ax.plot(g.year,g[metric],color='#277b80');ax.set(title=f'{country}: '+metric.replace('_',' '),xlabel='Year',ylabel='Hectares' if j==0 else 'Reported forest fires')
    fig.suptitle('EFFIS country reports: context at national scale, not pixel-level labels')
    fig.tight_layout();fig.savefig(ROOT/'reports/figures/10_effis_context.png',dpi=170,bbox_inches='tight');plt.close(fig)
    summary=d.groupby(['country','metric']).agg(nonmissing_years=('value','count'),first_year=('year','min'),last_year=('year','max')).reset_index()
    summary.to_csv(ROOT/'reports/tables/effis_coverage.csv',index=False)
    print(selection[selection.year>=2020].to_string(index=False))

if __name__=='__main__':main()
