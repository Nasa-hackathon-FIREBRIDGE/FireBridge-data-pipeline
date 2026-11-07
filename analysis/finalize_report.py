"""Attach measured findings and supplemental context; export standalone offline HTML."""
from pathlib import Path
import base64,json,re,hashlib,datetime
import pandas as pd
import markdown
ROOT=Path(__file__).resolve().parents[1];R=ROOT/'reports';T=R/'tables'

def main():
    p=R/'FIREBRIDGE_EDA.md';s=p.read_text()
    quality=pd.read_csv(T/'quality_checks.csv');nonzero=quality[quality.rows>0]
    inv=pd.read_csv(T/'inventory.csv');pilot=pd.read_parquet(ROOT/'data/processed/pilot_detections.parquet')
    summary=pd.read_csv(T/'pilot_platform_year.csv')
    pairs=pd.read_csv(T/'positive_timestamp_pair_diagnostics.csv');p5=pairs[(pairs.grid_km==5)&(pairs.tolerance_min==30)]
    profiles=json.loads((T/'archive_profiles.json').read_text())
    validation=json.loads((T/'validation.json').read_text())
    # Record categorical domain validation across the exact full-file histograms.
    domain=[]
    for profile in profiles:
        cats=profile['categories'];family='landsat' if '_LS_' in profile['archive'] else ('modis' if '_M-C61_' in profile['archive'] else 'viirs')
        for val,n in cats['confidence'].items():
            ok=(val in ['L','M','H']) if family=='landsat' else ((val in ['l','n','h']) if family=='viirs' else (val.isdigit() and 0<=float(val)<=100))
            if not ok:domain.append({'archive':profile['archive'],'field':'confidence','value':val,'rows':n})
        for val,n in cats.get('type',{}).items():
            if val not in ['0','1','2','3']:domain.append({'archive':profile['archive'],'field':'type','value':val,'rows':n})
    pd.DataFrame(domain,columns=['archive','field','value','rows']).to_csv(T/'category_domain_exceptions.csv',index=False)
    counts=pilot.groupby(['satellite','year']).size().unstack(fill_value=0)
    details='\n'.join(f'- **{row.source} → Aqua, 5 km / 30 minutes:** {int(row.pairs)} matched both-positive timestamp groups (not eligible observation pairs).' for row in p5.itertuples())
    confidence=pilot.groupby('satellite').retained.agg(['size','sum']);confidence['retained_percent']=100*confidence['sum']/confidence['size']
    keytext=f'''## Measured findings from this run

- **{validation['input_rows']:,} raw rows** scanned across ten archives; **{len(pilot):,}** valid, exactly deduplicated pilot rows.
- **Annual exports overlap calendar boundaries.** Use the recorded acquisition year, not a guessed filename year. Regional deduplication removed {validation['regional_exact_duplicate_excess']:,} repeated full rows from the union of study rectangles.
- **Landsat contributes zero rows** in the pilot and southern-Spain rectangles.
- **Data gaps block the planned experiment.** The substantive Aqua record supplied here is 2025; the blueprint's earlier reference years and full observation masks are missing.
- **{len(nonzero)} nonzero global missing/format-check results** and **{len(domain)} categorical-domain exceptions** were found. The detailed tables remain authoritative; missing whole columns are reported separately as schema differences.
{details}

Pilot counts by actual UTC year:

{counts.to_markdown()}

Retaining nominal/high confidence gives:

{confidence.reset_index().to_markdown(index=False,floatfmt='.1f')}

**The reference sample is small:** only 57 Aqua detections on 27 UTC dates are supplied inside the pilot for 2025. The 5 km / 30 minute check finds only four S-NPP/Aqua both-positive timestamp matches. This is insufficient evidence for the proposed model evaluation; broaden continuous time or geography after acquiring masks, and count independent episodes before training. It does not establish how many valid paired negative opportunities exist.

These are detection sample sizes, not counts of independent episodes. Days/cells/passes of one episode remain statistically dependent.

'''
    # Idempotent: remove earlier generated insert if rerun.
    s=re.sub(r'## Measured findings from this run\n.*?(?=## 1\.)','',s,flags=re.S)
    s=s.replace('## 1. What you downloaded',keytext+'## 1. What you downloaded')
    effis=pd.read_csv(T/'effis_morocco_spain.csv');recent=effis[effis.year>=2020]
    extra=f'''## Added EFFIS dataset: what it contributes

![EFFIS national context](figures/10_effis_context.png)

{recent.to_markdown(index=False,floatfmt='.2f')}

The real downloaded workbook adds national reported forest-fire counts and burned-area totals. It contains year rows 1980–2024, with country-specific missing values. Morocco values begin later than Spain values. The Morocco 2022 burned-area peak is visible in this source, but these national aggregates cannot validate pixel-scale observations in the northern pilot. Forest-fire reporting definitions also differ from FIRMS, which includes agricultural burning and other thermal anomalies. No regional/national count ratio is interpreted as sensor accuracy. Source: [EFFIS country totals](https://forest-fire.emergency.copernicus.eu/effis/applications/data-and-services/report_2024.xlsx).

'''
    s=re.sub(r'## Added EFFIS dataset: what it contributes\n.*?(?=## 7\.)','',s,flags=re.S)
    s=s.replace('## 7. Recommended data decisions',extra+'## 7. Recommended data decisions')
    p.write_text(s)
    # Keep the detailed Markdown as evidence, and the HTML as a concise team walkthrough.
    from build_team_figures import main as build_team_figures
    from build_team_report import main as build_team_report
    build_team_figures()
    build_team_report()
    manifest=[]
    for path in sorted(R.glob('figures/*.png')):
        manifest.append({'path':str(path.relative_to(ROOT)),'bytes':path.stat().st_size,'sha256':hashlib.sha256(path.read_bytes()).hexdigest()})
    (T/'figure_manifest.json').write_text(json.dumps(manifest,indent=2))
    print('Offline team report written:',(R/'FIREBRIDGE_EDA.html').stat().st_size,'bytes')

if __name__=='__main__':main()
