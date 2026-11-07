"""Build the offline, team-facing FIREBRIDGE walkthrough from EDA evidence."""
from __future__ import annotations

import base64
import csv
import html
import json
from pathlib import Path
from string import Template

ROOT = Path(__file__).resolve().parents[1]
REPORTS = ROOT / 'reports'
TABLES = REPORTS / 'tables'


def read_csv(name):
    with (TABLES / name).open(newline='', encoding='utf-8') as handle:
        return list(csv.DictReader(handle))


def image(name):
    data = (REPORTS / 'team_figures' / name).read_bytes()
    return 'data:image/png;base64,' + base64.b64encode(data).decode('ascii')


def build():
    validation = json.loads((TABLES / 'validation.json').read_text())
    platforms = read_csv('pilot_platform_year.csv')
    observations = read_csv('pilot_detections.csv')
    manifest = json.loads((TABLES / 'science_download_manifest.json').read_text())
    # This walkthrough describes the current access gap; fail rather than silently
    # publish stale download claims if the acquisition state changes.
    if any(row['status'] != 'requires_Earthdata_token' for row in manifest):
        raise ValueError('Science download status changed: review the team report access narrative.')
    example = observations[0]
    if example['satellite'] != 'N20' or example['confidence'] != 'n':
        raise ValueError('Worked-example platform/confidence changed: review its plain-language labels.')
    rows = []
    roles = [
        ('Aqua', 'Aqua · MODIS', 'Reference for the proposed comparison'),
        ('Terra', 'Terra · MODIS', 'Separate observation schedule'),
        ('SNPP', 'S-NPP · VIIRS', 'First source to compare with Aqua'),
        ('N20', 'NOAA-20 · VIIRS', 'Additional source; analyze separately'),
        ('N21', 'NOAA-21 · VIIRS', 'Provisional near-real-time source'),
    ]
    for key, label, role in roles:
        records = [row for row in platforms if row['satellite'] == key]
        years = sorted({row['year'] for row in records})
        span = years[0] if len(years) == 1 else years[0] + '–' + years[-1]
        count = sum(int(row['rows']) for row in records)
        rows.append(f'<tr><th scope="row">{label}</th><td>{span}</td><td class="number">{count:,}</td><td>{role}</td></tr>')
    rows.append('<tr><th scope="row">Landsat</th><td>2024–2025</td><td class="number">0</td><td>Set aside for this pilot</td></tr>')
    time = example['acq_time'].zfill(4)
    pair_rows = read_csv('positive_timestamp_pair_diagnostics.csv')
    pair = next(row for row in pair_rows if row['source'] == 'SNPP' and float(row['grid_km']) == 5 and float(row['tolerance_min']) == 30)
    aqua = next(row for row in platforms if row['satellite'] == 'Aqua' and row['year'] == '2025')
    values = {
        'raw_rows': f"{validation['input_rows']:,}",
        'archives': validation['archives'],
        'pilot_rows': f"{validation['pilot_deduplicated_valid_rows']:,}",
        'pilot_removed': validation['pilot_raw_rows'] - validation['pilot_deduplicated_valid_rows'],
        'aqua_rows': aqua['rows'], 'aqua_days': aqua['days_with_detections'],
        'pairs': pair['pairs'], 'dataset_rows': '\n'.join(rows),
        'date': html.escape(example['acq_date']), 'time': f'{time[:2]}:{time[2:]} UTC',
        'coords': f"{float(example['latitude']):.5f}°, {float(example['longitude']):.5f}°",
        'frp': html.escape(example['frp']),
        'counts_image': image('2025_sensor_counts.png'),
        'monthly_image': image('snpp_monthly_counts.png'),
    }
    output = Template(PAGE).substitute(values)
    destination = REPORTS / 'FIREBRIDGE_EDA.html'
    destination.write_text(output, encoding='utf-8')
    print(f'Wrote {destination} ({len(output):,} characters)')
    return destination


PAGE = r'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>FIREBRIDGE — Understand the data, explain the plan</title>
<style>
:root{--ink:#172e32;--muted:#4e6163;--teal:#00665f;--paper:#fbfaf6;--line:#d6ddda;--orange:#9b4b18;--wash:#eef4f1}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.65 system-ui,-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--teal);text-underline-offset:4px}a:hover{color:#003e39}a:focus-visible,summary:focus-visible{outline:3px solid var(--orange);outline-offset:5px}p{margin:0 0 1em}strong{font-weight:680}header,main,footer{max-width:1120px;margin:auto;padding-left:42px;padding-right:42px}.masthead{padding-top:28px;display:flex;justify-content:space-between;gap:16px;font-size:12px;letter-spacing:.12em;text-transform:uppercase;color:var(--muted)}.brand{color:var(--teal);font-weight:800}.intro{padding:60px 0 30px;max-width:830px}.eyebrow{font-size:13px;font-weight:700;letter-spacing:.09em;text-transform:uppercase;color:var(--teal);margin-bottom:15px}h1{font-size:clamp(35px,4.3vw,53px);line-height:1.12;letter-spacing:-.035em;max-width:780px;margin:0 0 22px;font-weight:720}.subtitle{max-width:690px;font-size:20px;color:var(--muted)}.state{font-size:14px;color:var(--muted);border-left:3px solid var(--teal);padding-left:13px;margin-top:24px}.state strong{color:var(--ink)}nav{border-block:1px solid var(--line);padding:16px 0;display:flex;flex-wrap:wrap;gap:8px 23px;font-size:14px}nav a{text-decoration:none}nav a:hover{text-decoration:underline}section{display:grid;grid-template-columns:160px minmax(0,1fr);gap:30px;padding:49px 0;border-bottom:1px solid var(--line)}.section-label{padding-top:4px;font-size:13px;line-height:1.45;color:var(--teal);font-weight:700;text-transform:uppercase;letter-spacing:.08em}.section-label span{display:block;font-size:27px;letter-spacing:-.03em;margin-bottom:8px;color:#66857e;font-weight:500}h2{font-size:28px;line-height:1.25;letter-spacing:-.025em;margin:0 0 20px}h3{font-size:19px;line-height:1.4;margin:26px 0 9px}.lead{font-size:22px;line-height:1.5;letter-spacing:-.01em}.note{font-size:15px;color:var(--muted);line-height:1.65}.takeaway{border-left:3px solid var(--orange);padding:13px 0 13px 19px;margin:25px 0;color:var(--ink)}.takeaway p:last-child{margin:0}.two-outputs{margin:24px 0;list-style:none;padding:0;border-block:1px solid var(--line)}.two-outputs li{padding:15px 0;font-size:16px}.two-outputs li+li{border-top:1px solid var(--line)}.two-outputs strong{display:inline-block;min-width:210px;color:var(--teal)}.table-wrap{overflow-x:auto;margin:22px 0 15px}table{border-collapse:collapse;width:100%;font-size:14px;line-height:1.55;text-align:left}caption{text-align:left;font-size:13px;font-weight:650;color:var(--muted);padding:0 0 12px}th,td{padding:12px 11px;border-bottom:1px solid var(--line);vertical-align:top}thead th{background:var(--wash);font-size:11px;text-transform:uppercase;letter-spacing:.06em}tbody th{font-weight:650}th:first-child,td:first-child{padding-left:10px}.number{font-variant-numeric:tabular-nums;text-align:right;white-space:nowrap}.example{background:white;border:1px solid var(--line);padding:7px 16px 14px;margin:20px 0}.example th{width:24%}.example td:nth-child(2){width:36%;font-variant-numeric:tabular-nums;font-weight:650}.example table tr:last-child>*{border:0}.example caption{padding:10px 0}.example td:last-child{color:var(--muted)}figure{margin:25px 0 35px;background:white;border:1px solid var(--line);padding:14px 15px 17px}figure img{display:block;width:100%;height:auto}figcaption{padding:5px 9px 0;font-size:14px;line-height:1.6;color:var(--muted)}figcaption strong{color:var(--ink)}.pipeline{padding:0;list-style:none;counter-reset:step;margin:23px 0}.pipeline li{position:relative;padding:0 0 23px 45px;counter-increment:step}.pipeline li:before{content:counter(step);position:absolute;left:0;top:1px;width:28px;height:28px;display:grid;place-items:center;border:1px solid #8caaa3;font-size:13px;color:var(--teal);background:var(--paper);z-index:1}.pipeline li:not(:last-child):after{content:"";position:absolute;left:14px;top:30px;bottom:0;width:1px;background:var(--line)}.pipeline strong{display:block;font-size:17px;margin-bottom:3px}.pipeline p{font-size:16px;margin:0}.plan{padding:0;list-style:none}.plan li{padding:17px 0;border-bottom:1px solid var(--line);font-size:16px}.plan li:last-child{border-bottom:0}.when{display:block;font-size:12px;font-weight:750;color:var(--teal);letter-spacing:.08em;text-transform:uppercase;margin-bottom:5px}.gap{color:var(--orange)}.roles{font-size:15px}.pitch{background:var(--wash);padding:24px 27px;margin-top:26px}.pitch h3{font-size:13px;text-transform:uppercase;letter-spacing:.07em;margin:0 0 12px;color:var(--teal)}blockquote{margin:0;font-size:17px;line-height:1.7}footer{padding-top:30px;padding-bottom:45px;font-size:14px}details{border-bottom:1px solid var(--line);padding:14px 0}summary{cursor:pointer;font-weight:650;color:var(--teal)}details p,details ul{margin:16px 0;font-size:14px}details ul{padding-left:20px}.resources{display:flex;gap:10px 23px;flex-wrap:wrap;padding:23px 0 0}.footer-note{font-size:12px;color:var(--muted);margin:17px 0 0}.skip{position:absolute;left:12px;top:-100px;background:white;padding:10px;z-index:5}.skip:focus{top:10px}
@media(max-width:760px){body{font-size:17px}header,main,footer{padding-left:22px;padding-right:22px}.masthead{font-size:10px;letter-spacing:.06em}.intro{padding-top:38px}.subtitle{font-size:18px}nav{gap:11px 19px}section{display:block;padding:33px 0}.section-label{margin-bottom:14px}.section-label span{display:inline;font-size:15px;margin-right:10px}h2{font-size:25px}.lead{font-size:20px}.two-outputs strong{display:block;margin-bottom:3px}.table-wrap table{min-width:560px}.example{padding:5px 10px 10px}.example table{font-size:12px}.example th,.example td{padding:10px 6px}.example td:nth-child(2){overflow-wrap:anywhere}.pitch{padding:21px}figure{padding:7px 7px 13px}figcaption{font-size:13px}.resources{display:grid;gap:10px}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{@page{margin:16mm}body{background:white;font-size:10pt;line-height:1.5}header,main,footer{max-width:none;padding:0}.masthead{padding-top:0}.intro{padding:24px 0 15px}h1{font-size:27pt;max-width:none}.subtitle{font-size:12pt}nav,.skip{display:none}section{display:block;padding:20px 0}.section-label{margin-bottom:8px}.section-label span{display:inline;font-size:12pt;margin-right:8px}h2{font-size:18pt;break-after:avoid}.lead{font-size:13pt}p,li{orphans:3;widows:3}.note,.pipeline p,.plan li,.two-outputs li,blockquote{font-size:10pt}table,.example table{font-size:8.5pt;min-width:0!important}.table-wrap{overflow:visible}figure{break-inside:avoid;max-width:160mm;margin:18px auto}figcaption{font-size:9pt}h3,caption{break-after:avoid}.takeaway,.pitch,.example{break-inside:avoid}.resources{font-size:9pt}a{color:inherit}footer{padding-top:20px}}
</style>
</head>
<body>
<a class="skip" href="#project">Skip to the walkthrough</a>
<header>
<div class="masthead"><span class="brand">FIREBRIDGE</span><span>Team data guide · September 2026</span></div>
<div class="intro"><p class="eyebrow">From the blueprint to the data</p><h1>Understand the data.<br>Explain what we can build.</h1><p class="subtitle">A plain-language walkthrough of our northern Morocco pilot: what we have, what it tells us, and what comes next.</p><p class="state"><strong>Current stage: data exploration.</strong> The comparison model and project outputs are still proposed.</p></div>
<nav aria-label="Walkthrough sections"><a href="#project">01 Project</a><a href="#data">02 Our data</a><a href="#row">03 Read a row</a><a href="#findings">04 Findings</a><a href="#workflow">05 Build plan</a><a href="#next">06 Team next steps</a></nav>
</header>
<main>
<section id="project"><div class="section-label"><span>01</span>The question</div><div>
<h2>The project in one minute</h2><p class="lead">When was burning unusual here — and how much of the apparent change comes from switching satellites?</p>
<p>Satellites see different-sized pixels and visit at different times. A more sensitive sensor can record more hotspots even when burning has not increased. FIREBRIDGE aims to make the record more comparable.</p>
<ul class="two-outputs"><li><strong>A comparable view</strong> Estimate activity on the Aqua reference scale in map squares about 5 km × 5 km.</li><li><strong>A detailed view</strong> Keep the original VIIRS detections for local exploration.</li></ul>
<p class="note">Our starting area is the Chefchaouen–Larache rectangle in northern Morocco. It is a study box, not a province boundary. These outputs are the blueprint’s goals; they have not been built or validated.</p>
</div></section>
<section id="data"><div class="section-label"><span>02</span>The inventory</div><div>
<h2>What data do we actually have?</h2><p>We scanned <strong>$raw_rows raw global rows in $archives archives</strong>. Inside the pilot, we have <strong>$pilot_rows detections</strong> after removing exact duplicates.</p>
<div class="table-wrap" tabindex="0" role="region" aria-label="Downloaded satellite datasets"><table><caption>Downloaded hotspot points · pilot counts include all confidence levels</caption><thead><tr><th scope="col">Satellite · sensor</th><th scope="col">Pilot years</th><th scope="col" class="number">Rows</th><th scope="col">Project role</th></tr></thead><tbody>$dataset_rows</tbody></table></div>
<p class="note">Totals span different years, so they are not a fair satellite comparison. Most supplied data cover 2023–2025; some global exports also include the next January 1. We use each row’s date.</p>
<p>We also downloaded <strong>EFFIS national statistics</strong> for context. Country totals cannot label individual pilot pixels. NASA fire masks and geolocation files are cataloged, but their downloads still require Earthdata access.</p>
</div></section>
<section id="row"><div class="section-label"><span>03</span>Reading the data</div><div>
<h2>One row is one detected pixel, at one time</h2><p>A single fire can produce many rows: across neighboring pixels, later passes, and different satellites. A hotspot count is <strong>not a count of fires or burned hectares</strong>.</p>
<div class="example"><table><caption>A real row from our pilot data</caption><tbody>
<tr><th scope="row">Satellite</th><td>N20 / VIIRS</td><td>Identify the source: NOAA-20.</td></tr>
<tr><th scope="row">Date</th><td>$date</td><td>Place it on the calendar.</td></tr>
<tr><th scope="row">Time</th><td>$time</td><td>Align satellite observations.</td></tr>
<tr><th scope="row">Location</th><td>$coords</td><td>Map latitude and longitude.</td></tr>
<tr><th scope="row">Fire power</th><td>$frp MW</td><td>FRP: radiative power at that moment.</td></tr>
<tr><th scope="row">Confidence</th><td>n → nominal</td><td>Apply this sensor’s quality rules.</td></tr>
</tbody></table></div>
<p class="note">MW means megawatts: power, not burned area. Confidence categories differ by sensor; they are not a shared probability that a fire occurred.</p>
<div class="takeaway"><p><strong>No row does not mean “no fire.”</strong> The satellite may have seen no hotspot, had a cloudy view, or provided no usable observation. The point files alone cannot tell us which.</p></div>
</div></section>
<section id="findings"><div class="section-label"><span>04</span>What we learned</div><div>
<h2>Explore patterns, then check what explains them</h2>
<figure><img src="$counts_image" alt="Pilot hotspot counts in 2025: Aqua 57, Terra 53, S-NPP 405, NOAA-20 418 and NOAA-21 387."><figcaption><strong>What it shows:</strong> different satellites report different numbers in the same year.<br><strong>For us:</strong> raw counts mix burning with sensor sensitivity, timing and usable coverage. This is not a harmonized result.</figcaption></figure>
<figure><img src="$monthly_image" alt="Monthly S-NPP pilot detection counts comparing 2024 with 2025, using one satellite throughout."><figcaption><strong>What it shows:</strong> how recorded activity varies month by month within S-NPP.<br><strong>For us:</strong> this helps select periods to inspect. Two years of detections cannot establish a long-term or causal seasonal trend.</figcaption></figure>
<p><strong>The Aqua reference is small:</strong> $aqua_rows detections on $aqua_days dates in 2025. At 5 km and within 30 minutes, the S-NPP/Aqua diagnostic finds only <strong>$pairs timestamp matches where both reported a hotspot</strong>.</p>
<p>Those matches are neither all observable pairs nor a model score. We need complete observation information and more contiguous years or area before evaluating a model. Quality checks also removed $pilot_removed exact duplicate pilot rows.</p>
</div></section>
<section id="workflow"><div class="section-label"><span>05</span>The blueprint</div><div>
<h2>How the data becomes FIREBRIDGE</h2>
<ol class="pipeline">
<li><strong>Collect detections and observation coverage</strong><p>Combine points with fire masks (clear, cloud, water or invalid) and geolocation (where every pixel lies). Masks and geolocation are still missing.</p></li>
<li><strong>Compare the same place and near-time passes</strong><p>Use common 5 km cells and only land both sensors could clearly observe. Keep insufficient observations marked unknown.</p></li>
<li><strong>Learn an Aqua-equivalent response</strong><p>Start with simple comparisons, then a simple statistical model. Keep a more complex model only if it does better on reserved data.</p></li>
<li><strong>Test beyond the training sample</strong><p>Reserve years and southern Spain. Hide Aqua during prediction, then reveal it for comparison. Aqua is an imperfect reference, not ground truth.</p></li>
<li><strong>Explain the result to users</strong><p>Show a calendar, source comparisons and supporting evidence, while keeping original VIIRS detail visible.</p></li>
</ol>
<p class="takeaway">The model asks: <strong>“Would Aqua report a retained hotspot under these supported conditions?”</strong> It does not directly answer whether a true fire incident existed.</p>
</div></section>
<section id="next"><div class="section-label"><span>06</span>Team next steps</div><div>
<h2>What we can do now, and what unlocks the rest</h2>
<ul class="plan">
<li><span class="when">Now · explore</span>Build descriptive maps and calendars separately for each satellite using the downloaded points. Use EFFIS only for national context.</li>
<li><span class="when gap">Next · complete the observations</span>Get paired masks and geolocation for a continuous week, <strong>14–20 July 2025</strong>, once Earthdata access is ready. This is an access and format check, not a representative training set. Then acquire enough complete earlier seasons.</li>
<li><span class="when">Before training · freeze the evaluation</span>The blueprint’s 2020–2021 training, 2022 development, 2023 calibration (checking and adjusting predicted probabilities) and 2024 test split is not supported by our supplied files. Acquire the needed years and freeze a suitable split before fitting.</li>
<li><span class="when">Later · add context</span>MCD12Q1 adds forest/cropland context; MCD64A1 adds burned-area timing evidence, not independent ground truth. Both remain pending. ERA5-Land weather is optional later.</li>
</ul>
<p class="roles"><strong>Suggested team ownership:</strong> data access and masks; maps and calendar; matching and evaluation; project story and evidence.</p>
<div class="pitch"><h3>A 60-second team explanation</h3><blockquote>“FIREBRIDGE aims to help us compare observed burning over time and see how much the satellite choice affects the picture. We have explored millions of global rows and found 2,923 hotspot detections in our northern Morocco pilot. These are detected pixels, not individual fires. We can already map when and where each source reports activity. Next, we need to know what each satellite could clearly see, including times with no detections. Then we can compare shared observations, learn an Aqua-equivalent response, and test it on reserved data. The result should make comparisons easier while preserving VIIRS detail. We have a clear data plan; we have not yet proved the model works.”</blockquote></div>
</div></section>
</main>
<footer>
<details><summary>Technical notes and data checks</summary><p>The pilot rectangle is 34.5–35.9° N, −6.4 to −4.5° longitude; it is not polygon-clipped to land. Counts use valid, exactly deduplicated rows, including all confidence classes. Global raw counts retain duplicates; an independent check confirmed 304 exact duplicates in the 2024 Landsat archive.</p><p>The pairing diagnostic uses daytime nominal/high detections, standard streams, a 5 km EPSG:6933 grid and nearest timestamps without reuse within a sensor pair/cell. It contains both-positive samples only. It cannot establish false-positive rates, recall or model accuracy. The present files do not provide the observation denominator needed for the blueprint’s harmonized metrics.</p><p>The worked example comes directly from <a href="tables/pilot_detections.csv">pilot_detections.csv</a>. Counts and access status come from <a href="tables/validation.json">validation.json</a>, <a href="tables/pilot_platform_year.csv">pilot_platform_year.csv</a> and <a href="tables/science_download_manifest.json">science_download_manifest.json</a>. Rebuild with <code>firebridge_env/bin/python analysis/build_team_report.py</code>.</p></details>
<details><summary>Blueprint and source definitions</summary><ul><li><a href="../FIREBRIDGE_Blueprint.md">FIREBRIDGE project blueprint</a> — proposed research design.</li><li><a href="https://www.earthdata.nasa.gov/data/tools/firms/active-fire-data-attributes-modis-viirs">NASA FIRMS field definitions</a> — units, confidence and sensor attributes.</li><li><a href="https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf">MODIS fire user guide</a> and <a href="https://www.earthdata.nasa.gov/s3fs-public/2025-06/VIIRS_C2_AF-375m_User_Guide_1.2.pdf">VIIRS fire user guide</a> — interpreting masks and observations.</li><li><a href="https://forest-fire.emergency.copernicus.eu/effis/applications/data-and-services/report_2024.xlsx">EFFIS country statistics</a> — downloaded national context.</li></ul></details>
<div class="resources" aria-label="Detailed analysis resources"><a href="FIREBRIDGE_EDA.md">Full technical report</a><a href="FIELD_DICTIONARY.md">Field dictionary</a><a href="DATA_ACCESS.md">Download status</a><a href="../notebooks/FIREBRIDGE_EDA.ipynb">Analysis notebook</a></div>
<p class="footer-note">Prepared from the completed EDA · September 2026. Charts are embedded for offline sharing; linked supporting files are separate.</p>
</footer>
</body>
</html>'''

def main():
    return build()


if __name__ == '__main__':
    main()
