"""Build a plain-language, offline HTML and detailed Markdown MODIS walkthrough.

Every reported statistic comes from the full-window analyzer's summary/tables.
Scientific plots are embedded in HTML for sharing without a network connection.
Run after analyze.py and the scientific figure builder have completed.
"""
from __future__ import annotations

import base64
import csv
from html import escape
import json
import math
from pathlib import Path
import re

ROOT = Path(__file__).resolve().parents[2]
OUT = ROOT / "reports/modis_2024_2025"
TABLES = OUT / "tables"
FIGURES = OUT / "figures"


def records(name):
    with (TABLES / f"{name}.csv").open(newline="") as stream:
        return list(csv.DictReader(stream))


def num(value):
    return float(value) if value not in (None, "", "nan") else math.nan


def count(value):
    return f"{int(float(value)):,}"


def decimal(value, places=1):
    x = num(value)
    return f"{x:,.{places}f}" if math.isfinite(x) else "unavailable"


def pct(a, b):
    return f"{100*num(a)/num(b):.1f}%" if num(b) else "unavailable"


def clock_hour(value):
    minutes = round(num(value)*60) % (24*60)
    return f"{minutes//60:02d}:{minutes%60:02d}"


def markup(text):
    """Small trusted-author Markdown subset; escape all generated data first."""
    text = escape(str(text))
    text = re.sub(r"\[([^\]]+)\]\(([^)]+)\)", r'<a href="\2">\1</a>', text)
    text = re.sub(r"\*\*([^*]+)\*\*", r"<strong>\1</strong>", text)
    text = re.sub(r"`([^`]+)`", r"<code>\1</code>", text)
    return text


class Report:
    def __init__(self):
        self.html = []
        self.md = []
        self.contents = []
        self.figure_count = 0
        self.table_count = 0

    def section(self, slug, title):
        if self.contents:
            self.html.append("</section>")
        index = len(self.contents)+1
        self.contents.append((slug,title))
        self.html.append(f'<section id="{slug}" aria-labelledby="heading-{slug}"><p class="step">{index:02d}</p><h2 id="heading-{slug}">{escape(title)}</h2>')
        self.md.append(f"\n## {index}. {title}\n")

    def paragraph(self, text, lead=False):
        self.html.append(f'<p{chr(32)+"class=\"lead\"" if lead else ""}>{markup(text)}</p>')
        self.md.append(text+"\n")

    def note(self, text, title="Remember"):
        self.html.append(f'<aside class="note"><strong>{escape(title)}</strong><p>{markup(text)}</p></aside>')
        self.md.append(f"> **{title}.** {text}\n")

    def table(self, headers, rows, caption=None):
        self.table_count += 1
        hint_id = f"table-scroll-hint-{self.table_count}"
        self.html.append(f'<p class="table-scroll-hint" id="{hint_id}">Swipe or scroll to see all columns.</p><div class="table-wrap" tabindex="0" aria-describedby="{hint_id}"><table>')
        if caption:
            self.html.append(f"<caption>{escape(caption)}</caption>")
            self.md.append(f"**{caption}**\n")
        self.html.append("<thead><tr>"+"".join(f"<th scope=\"col\">{escape(h)}</th>" for h in headers)+"</tr></thead><tbody>")
        for row in rows:
            self.html.append("<tr>"+"".join(f"<td>{markup(c)}</td>" for c in row)+"</tr>")
        self.html.append("</tbody></table></div>")
        self.md.append("| "+" | ".join(headers)+" |\n| "+" | ".join("---" for _ in headers)+" |")
        self.md.extend("| "+" | ".join(str(v).replace("|","/") for v in row)+" |" for row in rows)
        self.md.append("")

    def figure(self, filename, alt, caption, collapsed_title=None):
        path = FIGURES / filename
        if not path.exists():
            raise FileNotFoundError(f"Required scientific figure is missing: {path}")
        self.figure_count += 1
        data = base64.b64encode(path.read_bytes()).decode("ascii")
        if collapsed_title:
            self.html.append(f'<details><summary>{escape(collapsed_title)}</summary><div class="detail-body">')
        self.html.append(f'<figure><img src="data:image/png;base64,{data}" alt="{escape(alt,quote=True)}" loading="lazy" width="1600"><figcaption><span>Figure {self.figure_count}.</span> {markup(caption)}</figcaption></figure>')
        self.html[-1] = self.html[-1].replace('<figcaption>',f'<button type="button" class="figure-open" data-figure-number="{self.figure_count}" aria-controls="figure-viewer" aria-haspopup="dialog">Open figure at full size</button><figcaption>')
        if collapsed_title:
            self.html.append('</div></details>')
        self.md.append(f"![{alt}](figures/{filename})\n\nFigure {self.figure_count}. {caption}\n")

    def bullets(self, items, ordered=False):
        tag = "ol" if ordered else "ul"
        self.html.append(f"<{tag}>"+"".join(f"<li>{markup(item)}</li>" for item in items)+f"</{tag}>")
        self.md.extend(f"{i+1}. {item}" if ordered else f"- {item}" for i,item in enumerate(items))
        self.md.append("")

    def details(self, title, content):
        self.html.append(f'<details><summary>{escape(title)}</summary><div class="detail-body">'+"".join(f"<p>{markup(p)}</p>" for p in content)+"</div></details>")
        self.md.append(f"### {title}\n")
        self.md.extend(p+"\n" for p in content)


STYLE = """
:root{--ink:#142b3b;--muted:#4a5b65;--paper:#fbfaf6;--line:#d9ddd7;--terra:#956124;--aqua:#087a79;--wash:#eef3f0;--accent:#c7a273}
*{box-sizing:border-box}html{scroll-behavior:smooth;scroll-padding-top:24px}body{margin:0;background:var(--paper);color:var(--ink);font:18px/1.65 -apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif}a{color:var(--aqua);text-underline-offset:4px}a:hover{color:var(--ink)}a:focus-visible,summary:focus-visible,.table-wrap:focus-visible{outline:3px solid var(--terra);outline-offset:5px}h1,h2,h3,p,ul,ol,figure{margin-top:0}h1{font-size:clamp(36px,5vw,62px);line-height:1.09;letter-spacing:-.055em;max-width:750px;margin-bottom:24px}h2{font-size:clamp(27px,3vw,37px);line-height:1.18;letter-spacing:-.032em;margin-bottom:24px}h3{font-size:21px;line-height:1.35}p{margin-bottom:21px}strong{font-weight:650}.shell{max-width:1280px;margin:auto;display:grid;grid-template-columns:225px minmax(0,880px);gap:75px;padding:55px 42px 90px}.rail{position:sticky;top:30px;align-self:start;font-size:14px;line-height:1.45}.brand{font-size:15px;font-weight:750;letter-spacing:.13em}.rail-label{margin-top:48px;color:var(--muted);font-size:12px;text-transform:uppercase;letter-spacing:.1em}.rail ol{padding:0;list-style:none}.rail li{border-bottom:1px solid var(--line);padding:11px 0}.rail a{color:var(--muted);text-decoration:none}.rail a:hover{color:var(--ink)}.rail .number{color:var(--terra);font-size:12px;margin-right:9px;font-variant-numeric:tabular-nums}.rail-bottom{margin-top:26px;font-size:13px;color:var(--muted)}main{min-width:0}.eyebrow{font-size:13px;letter-spacing:.12em;text-transform:uppercase;font-weight:700;color:var(--muted);margin-bottom:22px}.subtitle{font-size:21px;max-width:690px;line-height:1.55}.dates{font-size:14px;color:var(--muted);border-top:1px solid var(--line);border-bottom:1px solid var(--line);padding:15px 0;margin:30px 0}.hero{padding-bottom:32px}.hero-total{font-size:32px;font-weight:700;letter-spacing:-.025em;margin:0 0 10px}.hero-total small{font-size:18px;font-weight:400;letter-spacing:0}.platform-strip{display:flex;gap:36px;flex-wrap:wrap;font-size:18px}.terra{color:var(--terra)}.aqua{color:var(--aqua)}section{padding:48px 0 27px;border-top:1px solid var(--line)}.step{color:var(--terra);font-size:14px;font-weight:700;letter-spacing:.14em;margin-bottom:11px}.lead{font-size:21px;line-height:1.6}.note{border-left:3px solid var(--terra);padding:16px 23px;background:#f1eee5;margin:28px 0}.note>strong{font-size:15px}.note p{margin:8px 0 0}figure{margin:32px 0 28px}figure img{display:block;width:100%;height:auto;background:white;border:1px solid var(--line)}figcaption{font-size:15px;line-height:1.6;color:var(--muted);padding-top:12px}figcaption span{font-weight:700;color:var(--ink)}.table-wrap{overflow-x:auto;margin:27px 0}table{border-collapse:collapse;width:100%;font-size:16px;line-height:1.5}caption{text-align:left;font-weight:650;margin-bottom:12px}th{font-weight:650;border-bottom:2px solid var(--ink);text-align:left;padding:12px 14px 12px 0;vertical-align:bottom}td{border-bottom:1px solid var(--line);padding:13px 14px 13px 0;vertical-align:top}td:first-child{font-weight:500}code{font-size:.88em;background:#edf0eb;padding:2px 5px;overflow-wrap:anywhere}li{padding:0 0 12px 5px}li::marker{color:var(--terra)}details{border-top:1px solid var(--line);border-bottom:1px solid var(--line);margin:27px 0;background:transparent}summary{cursor:pointer;font-weight:600;padding:16px 0;font-size:16px}details[open] summary{border-bottom:1px solid var(--line)}.detail-body{padding:22px 0 4px;font-size:16px}.pitch{border-top:3px solid var(--aqua);margin:35px 0 0;padding:25px 0;font-size:22px;line-height:1.6}.pitch-label{font-size:13px;text-transform:uppercase;letter-spacing:.12em;font-weight:650;color:var(--aqua);margin-bottom:13px}.footer{font-size:14px;color:var(--muted);padding-top:35px;border-top:1px solid var(--line)}.skip{position:absolute;top:-60px;left:15px;background:white;padding:10px;z-index:5}.skip:focus{top:10px}
@media(max-width:1050px){.shell{grid-template-columns:180px minmax(0,1fr);gap:35px;padding:40px 30px}.rail{font-size:13px}}
.figure-open{font-family:inherit;font-size:14px;font-weight:600;line-height:1.5}
.table-scroll-hint,.mobile-contents{display:none}.figure-open{appearance:none;background:transparent;border:0;padding:8px 0 0;color:var(--aqua);font:600 14px/1.5 inherit;cursor:pointer;text-decoration:underline;text-underline-offset:4px}.figure-open:hover{color:var(--ink)}.figure-open:focus-visible,.viewer-close:focus-visible,.figure-viewport:focus-visible{outline:3px solid var(--terra);outline-offset:4px}.artifact-links{font-size:15px;line-height:1.7;margin:23px 0 0}.figure-viewer{width:min(96vw,1600px);max-width:96vw;height:92vh;max-height:92vh;margin:auto;padding:20px;background:var(--paper);color:var(--ink);border:1px solid var(--line);box-shadow:0 12px 80px #142b3b40}.figure-viewer::backdrop{background:#142b3bcc}.viewer-head{display:flex;align-items:center;justify-content:space-between;gap:20px}.viewer-title{font-size:20px;margin:0}.viewer-close{background:white;border:1px solid var(--line);padding:9px 16px;color:var(--ink);font:inherit;font-size:16px;cursor:pointer}.viewer-close:hover{border-color:var(--ink)}.viewer-help{font-size:14px;color:var(--muted);margin:14px 0 18px}.figure-viewport{height:calc(100% - 110px);overflow:auto;background:white}.figure-viewport img{display:block;width:auto;height:auto;max-width:none;max-height:none}
@media(max-width:760px){.shell{display:block;padding:28px 22px 60px}.rail{position:static}.rail .brand{margin-bottom:0}.rail-label,.rail ol,.rail-bottom{display:none}.mobile-contents{display:block;margin:0 0 30px}.mobile-contents nav{padding:10px 0}.mobile-contents ol{padding-left:22px;margin:10px 0 0;font-size:15px}.mobile-contents li{padding:5px 0}.mobile-contents .number{display:none}.table-scroll-hint{display:block;font-size:13px;line-height:1.5;color:var(--muted);margin:26px 0 7px}.table-scroll-hint+.table-wrap{margin-top:0}main{margin-top:24px}body{font-size:17px}.subtitle,.lead{font-size:19px}.hero-total{font-size:28px}.platform-strip{gap:14px 24px;font-size:17px}section{padding-top:35px}table{font-size:14px;min-width:480px}.note{padding:15px 18px}figcaption{font-size:14px}.pitch{font-size:20px}.figure-viewer{padding:14px}.viewer-title{font-size:17px}.viewer-help{font-size:13px}.viewer-close{padding:7px 12px;font-size:14px}.figure-viewport{height:calc(100% - 130px)}}
@media(prefers-reduced-motion:reduce){html{scroll-behavior:auto}}
@media print{body{background:white;font-size:11pt;line-height:1.5;color:#142b3b}.shell{display:block;padding:0;max-width:none}.rail,.skip,.mobile-contents,.table-scroll-hint,.figure-open,.figure-viewer{display:none}h1{font-size:30pt}h2{font-size:20pt}section{padding-top:25px}.hero{padding-bottom:15px}.lead,.subtitle{font-size:13pt}figure{break-inside:avoid}figure img{max-height:180mm;object-fit:contain}.note,table,.pitch{break-inside:avoid}table{font-size:10pt}.table-wrap{overflow:visible}details{display:block}details:not([open])>.detail-body{display:block}summary{font-size:11pt}a{color:inherit}figcaption,.footer{font-size:9pt}.hero-total{font-size:23pt}.platform-strip{font-size:12pt}h2,h3,.step{break-after:avoid}.dates{font-size:10pt}}
"""


FIGURE_VIEWER = """
<dialog id="figure-viewer" class="figure-viewer" aria-labelledby="viewer-title" aria-describedby="viewer-help">
  <div class="viewer-head"><h2 id="viewer-title" class="viewer-title">Figure at full size</h2><button type="button" class="viewer-close" autofocus>Close</button></div>
  <p id="viewer-help" class="viewer-help">The original chart is shown at full resolution. Scroll horizontally or vertically to inspect it. Press Escape or Close to return.</p>
  <div class="figure-viewport" tabindex="0" aria-label="Full-size chart; scroll to inspect its labels"></div>
</dialog>
<script>
(() => {
  const viewer = document.getElementById('figure-viewer');
  const viewport = viewer.querySelector('.figure-viewport');
  let opener = null;
  document.querySelectorAll('.figure-open').forEach(button => {
    button.addEventListener('click', () => {
      opener = button;
      const original = button.closest('figure').querySelector('img');
      const enlarged = original.cloneNode(false);
      enlarged.removeAttribute('width');
      enlarged.removeAttribute('loading');
      viewport.replaceChildren(enlarged);
      document.getElementById('viewer-title').textContent = 'Figure ' + button.dataset.figureNumber + ' · full size';
      viewer.showModal();
      viewport.scrollTop = 0;
      viewport.scrollLeft = 0;
    });
  });
  viewer.querySelector('.viewer-close').addEventListener('click', () => viewer.close());
  viewer.addEventListener('click', event => { if (event.target === viewer) viewer.close(); });
  viewer.addEventListener('close', () => {
    viewport.replaceChildren();
    if (opener) opener.focus({preventScroll: true});
  });
})();
</script>
"""


def build():
    summary = json.loads((OUT / "summary.json").read_text())
    platforms = {p["satellite"]:p for p in summary["platforms"]}
    monthly = records("monthly")
    quality = summary["quality"]
    regions = {(r["region"],r["satellite"]):r for r in summary["regions"]}
    baseline = sum(p["retained_conf30_rows"] for p in platforms.values())
    vegetation = sum(p["type0_conf30_rows"] for p in platforms.values())
    total = summary["analysis_rows"]
    audit = summary["january_overlap_audit"]
    dictionary = [
        ["Date + time", "When MODIS measured the pixel", "UTC; `0039` means 00:39"],
        ["Latitude + longitude", "Center of the detected pixel", "Decimal degrees"],
        ["Satellite", "Which observing platform", "Terra (`T`) or Aqua (`A`)"],
        ["T21 + T31", "Two thermal brightness temperatures", "Kelvin; not flame temperature"],
        ["FRP", "Radiative power from that fire pixel", "Megawatts (MW); a rate, not energy"],
        ["Confidence", "Native detection-quality score", "0–100; not a calibrated wildfire probability"],
        ["Type", "Inferred source category", "0 presumed vegetation; 1 volcano; 2 static land; 3 offshore"],
        ["Day/night + sample", "Algorithm regime and cross-track pixel index", "D / N; zero-based sample 0–1353"],
    ]
    pilot_rows = records("pilot_detections")
    exemplar = next((r for r in pilot_rows if num(r["type"]) == 0 and num(r["confidence"]) >= 30),None)
    if exemplar is None:
        # A real observation is available even if the regional candidate layer is empty.
        exemplar = records("frp_extremes")[0]
    example_time = exemplar["acq_time"].zfill(4)
    monthly_total = {}
    for row in monthly:
        monthly_total[row["month"]] = monthly_total.get(row["month"],0) + num(row["rows"])
    busiest_month = max(monthly_total,key=monthly_total.get)
    sensitivities = records("confidence_sensitivity")
    high_rows = sum(num(r["rows"]) for r in sensitivities if num(r["confidence_threshold"]) == 80)
    frp_neg = quality["negative_frp"]
    zero_frp = quality["zero_frp"]

    r = Report()
    r.section("dataset", "Start with the dataset")
    r.paragraph(f"We now have the full worldwide record requested: **{count(total)} MODIS detections** from **17 January 2024 through 17 January 2025**, including both end dates. Terra and Aqua are kept separate throughout the analysis.",lead=True)
    r.paragraph("The source is the standard, science-quality **MCD14ML Collection 6.1, version 03** product. We downloaded 13 monthly files from the official University of Maryland MODIS Fire Science Team archive and selected the requested dates. The files were read completely and checked; raw originals and their checksums are preserved.")
    r.note("There are **367 UTC calendar dates** in this window. January 2024 includes only 17–31 January (15 dates); January 2025 includes only 1–17 January (17 dates). Monthly comparisons below account for these partial months.","The date window")
    r.table(["Platform","Recorded detections","Share of the selected record"],[[sat,count(platforms[sat]["rows"]),pct(platforms[sat]["rows"],total)] for sat in ("Terra","Aqua")])
    r.figure("02_global_map.png","Global map of recorded MODIS Terra and Aqua detections combined in one-degree bins.","The map combines both platforms in **1° × 1° bins**, with color on a logarithmic scale. Dense areas contain more exported detections. Degree bins have unequal physical areas; this map does not measure risk or burned area.")
    r.details("Source files, processing and reproducibility",[
        "The [input inventory](tables/input_inventory.csv) lists every monthly file, bytes, SHA-256 checksum and rows included/excluded by the date filter. The [download manifest](../../data/external/modis_2024_2025/acquisition_manifest.json) records the provider URLs. These are standard historical products; no near-real-time data were merged into the record.",
        "Read the [full machine-readable summary](summary.json), [validation results](validation.json), [raw-schema guide](../../data/external/modis_2024_2025/README.md), and [scientific interpretation notes](SCIENCE_NOTES.md). All main counts and quantiles use the full selected population. A reproducible sample is used only for visual scatter plots.",
    ])

    r.section("one-row", "Understand one real observation")
    r.paragraph(f"On **{exemplar['acq_date']} at {example_time[:2]}:{example_time[2:]} UTC**, **{exemplar['satellite']}** recorded a thermal anomaly centered at **{decimal(exemplar['latitude'],4)}°, {decimal(exemplar['longitude'],4)}°**. The row reports **{decimal(exemplar['frp'])} MW FRP**, confidence **{count(exemplar['confidence'])}**, and inferred type **{count(exemplar['type'])}**. This is an actual row from the selected data.",lead=True)
    r.note("Tell the team: **“At this time, this satellite detected a hot pixel at this location.”** One ongoing fire can generate many pixels and many later observations. Several fires can also occur inside one pixel. A hotspot row is not an incident count, an ignition coordinate, or a perimeter.","What a row means")
    r.table(["Field","Question it answers","How to read it"],dictionary,"The 12 native columns, grouped for readability")
    r.paragraph("The nominal MODIS fire-pixel scale is about 1 km directly below the satellite (**nadir**), and grows toward the edge of the strip observed during one pass (the **swath**). That is the observation footprint; a smaller fire may be detectable. The coordinates locate the pixel center, so a map dot should not imply a precise fire boundary.")
    r.details("Data dictionary and units",[
        "The native source names are `YYYYMMDD HHMM sat lat lon T21 T31 sample FRP conf type dn`. The processed table gives them clearer names and adds derived UTC timestamps, inclusion flags, source filenames and source row numbers. Native `sample` is zero-based, 0–1353.",
        "The original monthly product has no explicit `scan` or `track` columns. They are available only in the separate January 2025 FIRMS overlap used for a limited footprint audit. The native guide calls T21 the band-21 brightness-temperature field; FIRMS describes its exported brightness channel as band 21/22. Both are brightness temperatures expressed in Kelvin, not measured flame temperature.",
    ])

    r.section("platforms", "Compare the two sampling schedules")
    aqua_ratio = num(platforms["Aqua"]["rows"])/num(platforms["Terra"]["rows"])
    r.paragraph(f"Aqua recorded **{decimal(aqua_ratio,2)} times** as many detections as Terra in this window. This describes the downloaded observations. It does not establish that Aqua is {decimal(aqua_ratio,2)} times more accurate or that either satellite sees every fire.",lead=True)
    r.table(["Platform","Daytime detections","Nighttime detections","Daytime share"],[[sat,count(platforms[sat]["day_rows"]),count(platforms[sat]["night_rows"]),pct(platforms[sat]["day_rows"],platforms[sat]["rows"])] for sat in ("Terra","Aqua")])
    r.paragraph("Both platforms carry MODIS, but observe places at different times. Fires can grow, cool or stop between observations. Cloud, viewing geometry, background temperature and successful observation opportunities also change. This point dataset cannot determine how much of the difference each cause explains.")
    r.note("The blueprint uses **Aqua as the afternoon reference convention** for harmonization with VIIRS. Aqua remains an imperfect observation. Terra provides a separate morning regime and needs its own adapter and evaluation before calibrated integration.","Decision for FIREBRIDGE")

    r.section("quality", "Check whether the record is usable")
    r.paragraph("The quality audit checks all selected rows, rather than a sample: dates, coordinates, missing values, numeric values, platform labels, native categories, exact duplicates and the January overlap with your existing FIRMS download.",lead=True)
    checks_table = [
        ["Rows selected from raw files",count(summary["target_raw_rows"]),"Exact UTC date filter"],
        ["Exact duplicate excess",count(quality["exact_duplicate_excess"]),"Removed from the analysis view; raw files retained"],
        ["Quarantined rows",count(quality["quarantined_rows"]),"Invalid essential fields excluded with a record"],
        ["Negative FRP",count(frp_neg),"Excluded from FRP summaries; kept as a quality flag"],
        ["Zero FRP",count(zero_frp),"Reported separately; not automatically deleted"],
        ["Dates with any global detection",count(summary["global_dates_with_any_exported_detection"])+" / 367","Exported detections somewhere worldwide"],
    ]
    r.table(["Audit","Result","Meaning / treatment"],checks_table)
    structural = {k:v for k,v in quality.items() if k.startswith(("missing_","nonfinite_","invalid_")) or k=="nonpositive_temperature"}
    problems = {k:v for k,v in structural.items() if v}
    if problems:
        r.paragraph("Nonzero structural checks: "+"; ".join(f"`{k}`: {count(v)}" for k,v in problems.items())+". Review these exceptions before model preparation.")
    else:
        r.paragraph("There are **no missing native fields, non-finite numeric values, invalid timestamps/coordinates, invalid platform/category values, invalid sample indices, or nonpositive thermal temperatures** in this selected record.")
    r.paragraph(f"As an independent check, we compared the new UMD record with your earlier FIRMS CSV for **1–17 January 2025**. **{count(audit['matched_rows_all_shared_native_fields'])} observations match on every shared native field**; UMD-only rows: **{count(audit['umd_unmatched_rows'])}**; FIRMS-only rows: **{count(audit['firms_unmatched_rows'])}**. The FIRMS file was used for this audit, so its rows are not counted a second time.")
    r.note("A calendar day with exported points somewhere on Earth does not prove a usable observation in a particular cell. A regional zero means **no exported detection**, and cannot yet become a clear-sky “no fire” label.","The main unresolved gap")
    r.details("Inspect the audit evidence",[
        "Open the [complete quality table](tables/quality_checks.csv), [exact duplicates](tables/exact_duplicates.csv), [quarantine](tables/quarantine.csv), and [January overlap audit](january_overlap_audit.json). [Repeated location/time keys](tables/location_time_key_review.csv) are retained for review; nearby observations at different times can legitimately describe the same continuing fire.",
        "Downloaded global dates support inventory checks. Per-cell valid observation support remains unavailable from the point files. Full masks, **quality flags (QA)** and matching geolocation are still needed to distinguish no retained detection from cloud, missing or unsupported observation.",
    ])

    r.section("seasonality", "Follow the year, with the right denominator")
    r.paragraph(f"The busiest calendar month by total detections is **{busiest_month}**, with **{count(monthly_total[busiest_month])}** rows across both platforms. The chart compares detections **per requested calendar day**, so the partial January periods are not mistaken for complete months.",lead=True)
    r.figure("01_monthly_rates.png","Monthly recorded detections per requested calendar day for Terra and Aqua, identifying partial January periods.","January 2024 represents **15 dates**, January 2025 **17 dates**. Dividing by calendar dates fixes that unequal duration; it does **not** correct for cloud, missing observations or unequal usable land coverage.")
    r.figure("06_hemisphere_seasons.png","MODIS detections separated by Northern and Southern Hemisphere over the selected months.","Global counts combine regions with different fire seasons, land uses and observation conditions. Separating hemispheres is a first step toward regional interpretation.",collapsed_title="Explore how the two hemispheres contribute")
    r.paragraph("Use these patterns to choose demonstration periods and investigate where activity concentrates. Describe them as **recorded detection patterns**. Climate explanations, causes of burning and coverage-corrected changes require additional evidence.")
    r.note("This window contains **one annual cycle**. It can describe this year, but cannot establish a long-term climatology, a trend, or whether a season was unusually active. Those questions need several comparable years and observation support.","One year is a starting record")
    r.details("Exact seasonal tables",[
        "The [monthly table](tables/monthly.csv) includes the date denominator, partial-month flag, all-detection count, baseline count and vegetation-focused count. The [daily table](tables/daily.csv) preserves every date and platform with `valid_observation_coverage = unknown_from_points`. The [hemisphere table](tables/hemisphere_monthly.csv) separates broad seasonal regimes.",
    ])

    r.section("signal", "Read confidence and radiative power")
    r.paragraph("Confidence describes the algorithm's detection-quality score. FRP describes radiative power at the observed time. They help filter and characterize observations, but answer different questions.",lead=True)
    r.table(["View","Rows kept","Share of valid detections"],[
        ["All valid detections",count(total),"100%"],
        ["Nominal / high: confidence ≥30",count(baseline),pct(baseline,total)],
        ["Vegetation-focused: type 0 + confidence ≥30",count(vegetation),pct(vegetation,total)],
        ["High confidence only: confidence ≥80, all types",count(high_rows),pct(high_rows,total)],
    ])
    r.figure("03_confidence.png","Distribution of native MODIS confidence classes separately for Terra and Aqua.","Confidence classes are **low 0–29**, **nominal 30–79**, **high 80–100**. All native classes remain in the EDA record.")
    types = records("type")
    type_labels = {0:"Presumed vegetation fire",1:"Active volcano",2:"Other static land source",3:"Offshore"}
    r.table(["Inferred type","Terra","Aqua"],[[f"{code}: {label}"]+[count(sum(num(t["rows"]) for t in types if t["satellite"]==sat and num(t["type"])==code)) for sat in ("Terra","Aqua")] for code,label in type_labels.items()])
    r.paragraph("Type 0 does not distinguish wildfire from agricultural or prescribed burning. Keep the inferred categories available for review instead of calling every row a wildfire.")
    r.figure("04_frp_distribution.png","Positive-FRP distributions separately for Terra and Aqua, on a logarithmic horizontal scale.",f"This histogram shows **positive FRP** on a logarithmic scale. All **{count(zero_frp)} zero-FRP rows** remain in the record and the nonnegative-FRP summaries below. Negative FRP rows in this selected window: **{count(frp_neg)}**. Very high observations deserve investigation rather than automatic deletion.")
    r.table(["Platform","Median FRP","95th percentile","Maximum"],[[sat,decimal(platforms[sat]["median_frp_MW"])+" MW",decimal(platforms[sat]["p95_frp_MW"])+" MW",decimal(platforms[sat]["max_frp_MW"])+" MW"] for sat in ("Terra","Aqua")])
    r.note("Confidence 80 is **not an 80% probability of a wildfire**. FRP in MW is **not burned hectares or total energy**. Summing FRP over different passes or days does not produce energy without defensible time integration and gap treatment.","How to explain the limits")
    r.paragraph(f"The FRP means are **{decimal(platforms['Terra']['mean_frp_MW'])} MW for Terra** and **{decimal(platforms['Aqua']['mean_frp_MW'])} MW for Aqua**, above their medians. A relatively small high-power tail pulls up the average. Use medians and percentiles alongside the mean when describing a typical recorded pixel.")
    r.details("Sensitivity and thermal relationships",[
        "The proposed baseline keeps nominal/high MODIS detections, confidence ≥30, while preserving every raw class. A vegetation candidate layer also requires type 0. Compare [thresholds 0, 30, 50, 80 and 90](tables/confidence_sensitivity.csv) before freezing a project rule. A stricter rule changes the observed population; it does not turn it into ground truth.",
        "The [exact quantiles](tables/exact_quantiles.csv) and [largest FRP rows](tables/frp_extremes.csv) expose the tails. [Spearman correlations](tables/type0_spearman.csv) are computed within platform and day/night for type-0 observations. Thermal contrast is a sensor-specific feature, rather than a universal fire-severity scale.",
    ])
    r.figure("10_confidence_sensitivity.png","Share of all-type detections retained at confidence thresholds 0, 30, 50, 80 and 90.","The threshold changes the observed population. The all-type ≥30 baseline and type-0 candidate rule are proposed project choices, rather than verification of wildfire.",collapsed_title="Explore how confidence thresholds change the record")
    r.figure("11_thermal_frp.png","Thermal brightness temperature and FRP scatter for a reproducible 40,000-row visualization sample.","This **40,000-row sample** is for visual scatter only (seed 20241017). Exact summary and correlation tables use the full appropriate population. The relationship between two detector outputs is not causal evidence or a measurement of flame temperature.",collapsed_title="Explore thermal signal and FRP together")

    r.section("timing", "Use the acquisition times actually observed")
    r.paragraph("Terra and Aqua have drifted away from their historical nominal crossing times. For this year, use the recorded timestamps and inspect their distribution instead of assigning every observation the old textbook time.",lead=True)
    r.table(["Platform","Daytime median solar time","Nighttime median solar time"],[[sat,clock_hour(platforms[sat]["day_median_solar_hour"]),clock_hour(platforms[sat]["night_median_solar_hour"])] for sat in ("Terra","Aqua")])
    r.figure("05_solar_time.png","Approximate local mean solar-time distribution of recorded Terra and Aqua detections by day/night.","Approximate mean solar time is **UTC + longitude / 15 hours**, wrapped over 24 hours; the local date is also retained. This is not civil clock time, and no equation-of-time correction is applied. These are times of detected hotspots, rather than the complete satellite observation schedule.")
    footprints = records("january_footprint_summary")
    r.table(["Platform","Median scan / median track","95th-percentile scan / track"],[[p["satellite"],decimal(p["scan_median_km"],2)+" / "+decimal(p["track_median_km"],2)+" km",decimal(p["scan_p95_km"],2)+" / "+decimal(p["track_p95_km"],2)+" km"] for p in footprints],"Pixel dimensions: January 1–17, 2025 FIRMS overlap only")
    r.paragraph("The complete monthly record contains the cross-track sample index, but not explicit pixel width/height fields. The footprint table above comes only from the independently checked FIRMS January overlap. It demonstrates varying observation geometry; it is not a full-year geometry summary. `scan × track` approximates pixel footprint, not land actually burning.")
    r.figure("09_footprint_january.png","Scan and track pixel-size histograms for Terra and Aqua in January 1–17, 2025 only.",f"The **{count(audit['firms_january_rows'])}-row January overlap** shows FIRMS pixel dimensions. Keep this limited date scope visible. Full-year native MCD14ML instead provides the sample index.",collapsed_title="Explore the January-only pixel-size distributions")
    r.details("Timing and geometry evidence",[
        "Read [solar-hour bins](tables/solar_hour_bins.csv), [monthly solar timing](tables/monthly_solar_timing.csv), and the limited [January footprint summary](tables/january_footprint_summary.csv). Historical nominal daytime crossings were around 10:30 Terra and 13:30 Aqua; NASA's 2024 mission material documents drift, so those nominal times should not be hard-coded for this analysis.",
    ])

    r.section("pilot", "Zoom into the northern Morocco study window")
    pilot_total = sum(num(regions[("pilot",sat)]["rows"]) for sat in ("Terra","Aqua"))
    pilot_veg = sum(num(regions[("pilot",sat)]["type0_conf30_rows"]) for sat in ("Terra","Aqua"))
    r.paragraph(f"Within the blueprint's northern Morocco rectangle, the selected year contains **{count(pilot_total)} detections**, of which **{count(pilot_veg)}** satisfy the vegetation-focused rule. This is the project's first local study window.",lead=True)
    r.note("Bounds: west **−6.4°**, south **34.5°**, east **−4.5°**, north **35.9°**. This rectangle is a study window. It is not the boundary of Morocco, a province, or a national estimate. Review a land mask and an **area of interest (AOI)** polygon before regional rates.","Keep the geography precise")
    r.table(["Platform","All detections","Type 0 + confidence ≥30","Dates with any exported detection"],[[sat,count(regions[("pilot",sat)]["rows"]),count(regions[("pilot",sat)]["type0_conf30_rows"]),count(regions[("pilot",sat)]["days_with_exported_detections"])+" / 367"] for sat in ("Terra","Aqua")])
    r.paragraph("This is a small local candidate sample. Before expecting a reliable local model, count independent eligible observation blocks and fire episodes. Broaden training years or the reviewed training area if the pilot supplies too few independent examples.")
    r.figure("08_pilot_map.png","Recorded MODIS detections inside the northern Morocco pilot rectangle, by satellite.","The map helps review spatial groups and recurring locations. A concentration is a candidate for investigation; its cause and incident identity are not supplied by these points.")
    r.figure("07_pilot_calendar.png","Northern Morocco monthly type-0 detections with confidence at least 30, separately for Terra and Aqua.",f"This local calendar contains the **{count(pilot_veg)} vegetation-focused candidates**. Monthly endpoint totals have unequal durations because January periods are partial. A zero cannot yet say whether the satellite observed usable land with no retained hotspot.")
    grid = [g for g in records("regional_grid_sensitivity") if g["region"]=="pilot"]
    r.details("Grid sensitivity and recurrence",[
        "We explored the blueprint's proposed equal-area pilot grid at **2, 5 and 10 km**, retaining the vegetation/confidence rule. Counts of occupied cells and positive cell-days change with grid size. These are positive-support summaries, not activity rates: eligible negative observations and usable-area denominators are still missing.",
        "Open [grid sensitivity](tables/regional_grid_sensitivity.csv), [5 km recurrence](tables/pilot_5km_recurrence.csv), [monthly pilot observations](tables/pilot_monthly.csv), and [every pilot detection](tables/pilot_detections.csv). Recurrence may reflect a continuing fire, repeated vegetation burning or a static-source classification issue; investigate before assigning an incident label.",
        "The broader Morocco-context and southern-Spain outputs are also rectangles, explicitly named as such in the [regional summary](tables/regional_summary.csv). They provide nearby context without claiming national administrative totals.",
    ])

    r.section("use", "Turn this EDA into FIREBRIDGE inputs")
    r.paragraph("This record can already support a transparent map, a detection calendar, sensor comparisons and selection of demonstration periods. The next scientific step is to build valid observation opportunities for the blueprint's Aqua-equivalent response.",lead=True)
    r.table(["What we have","Use in FIREBRIDGE","What still needs evidence"],[
        ["Native detections + provenance","Traceable map and observed-hotspot calendar","A hotspot calendar is not a complete fire-occurrence calendar"],
        ["Platform, UTC and solar timing","Separate morning/night/afternoon regimes","Full per-pass observation schedule and shared support"],
        ["Confidence, type, temperatures, FRP","Documented inclusion rules and source features","Threshold sensitivity and predictor availability at inference"],
        ["Pilot points and candidate grid","Choose cell size and inspect local examples","Land polygon, cloud/invalid masks and usable area"],
        ["Aqua afternoon observations","Defined reference response for VIIRS harmonization","Eligible paired positives and negatives, blocked evaluation"],
        ["Terra morning observations","Separate historical observation layer","Separate Terra adapter and evaluation"],
    ])
    r.note("Keep three states in the product: **retained hotspot**, **usable observation with no retained hotspot**, and **unsupported/missing observation**. Point files establish the first state. Full masks and geolocation are required to distinguish the other two.","The calendar contract")
    r.paragraph("The initial dataset layer should keep raw observations and derived flags together: source asset/row, platform, UTC timestamp, coordinates, native confidence/type/FRP/thermal fields, approximate solar date/time, inclusion rule and any exclusion reason. Preserve the difference between observed evidence and a later model prediction.")

    r.section("next", "What the team should do next")
    r.bullets([
        "**Freeze a reproducible starting record.** Use the downloaded full-year standard files and the processed detections. Keep all native classes; publish the ≥30 baseline and type-0 candidate rule with their sensitivity results. The requested point-data acquisition and EDA are now complete.",
        "**Choose one reviewed pilot AOI and demonstration window.** Inspect the local map, calendar and recurring locations. Agree on a land polygon and an equal-area grid; test 2/5/10 km before freezing the proposed 5 km pilot choice.",
        "**Download a bounded continuous swath sample.** Acquire Aqua `MYD14 + MYD03`, Terra `MOD14 + MOD03`, and the relevant VIIRS fire-mask/geolocation companions. Resolve compatible collections and acquisition keys, decode full masks and quality flags (QA), and geolocate non-fire pixels too. These science swaths remain pending; only the standard point record is complete.",
        "**Construct eligible cell/pass opportunities.** Record usable land, cloud and invalid fractions. A candidate Aqua–VIIRS pair starts with ≤30 minutes and ≥80% shared usable-land support, then tests alternative tolerances. Match without selecting on detected fire. Negatives require a usable reference observation with no retained hotspot.",
        "**Evaluate a small afternoon baseline before a complex model.** Compare common-grid detection and logistic regression using source-only count/FRP/geometry/coverage features. Freeze spatial and temporal blocks; keep 2024 for final temporal evaluation as proposed in the blueprint, and acquire earlier independent training/development seasons. Separate calibration and test data. Aqua is the reference convention, not ground truth.",
        "**Build the team demo around evidence.** Show native observations, usable support, model output and held-out errors as distinct layers. Add Terra through a separate adapter once evaluated. Burned-area/perimeter/incident records can corroborate patterns later; no accuracy, hectares-burned or coverage-corrected trend claim follows from this EDA alone.",
    ],ordered=True)
    r.html.append('<div class="pitch"><p class="pitch-label">A one-minute explanation for the team</p>')
    pitch = (f"“We downloaded the standard worldwide MODIS record for the exact year: {count(total)} detected hot pixels from Terra and Aqua. Every row tells us what a satellite detected at a particular time, so repeated rows are not repeated fire incidents. Aqua and Terra sample different times, which is why we compare them separately. The EDA shows where and when detections concentrate and how confidence, power and geometry behave. We can already build a map and observed-hotspot calendar. To build FIREBRIDGE's comparable calendar and test a harmonization model, our next step is full masks and geolocation, so we know when a cell was actually observed and can create valid positive and negative examples.”")
    r.html.append("<p>"+markup(pitch)+"</p></div>")
    r.md.append("### A one-minute explanation for the team\n\n"+pitch+"\n")
    r.details("Primary references and project evidence",[
        "Project: [FIREBRIDGE blueprint](../../FIREBRIDGE_Blueprint.md). Scientific interpretation: [source notes](SCIENCE_NOTES.md). Acquisition: [raw-data README](../../data/external/modis_2024_2025/README.md). Analysis: [summary](summary.json) and [validation](validation.json).",
        "[MODIS Collection 6/C6.1 user guide](https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf) supports the native schema, confidence/type classes, standard product access and point-only limitations. [NASA FIRMS archive](https://firms.modaps.eosdis.nasa.gov/download/) explains the standard historical data route.",
        "[NASA MODIS fire FAQ](https://forum.earthdata.nasa.gov/viewtopic.php?t=5191) and [FRP/confidence explanation](https://forum.earthdata.nasa.gov/viewtopic.php?t=4541) support pixel and signal interpretation. [NASA 2024 orbital-drift material](https://ntrs.nasa.gov/api/citations/20250000522/downloads/AGU24_Terra_25years_MODIS_geometry_poster_GLin.pdf) supports the timing caveat. Reference details were checked on 10 October 2026 in the source notes.",
    ])
    r.html.append("</section>")
    nav = "".join(f'<li><a href="#{slug}"><span class="number">{i:02d}</span>{escape(title)}</a></li>' for i,(slug,title) in enumerate(r.contents,1))
    artifacts = '<a href="MODIS_Terra_Aqua_2024_2025_Presentation.pptx">Presentation (PPTX)</a> · <a href="MODIS_Terra_Aqua_2024_2025_Presentation.pdf">Slides (PDF)</a> · <a href="PRESENTATION_SPEAKER_NOTES.md">Speaker notes</a> · <a href="../../notebooks/MODIS_Terra_Aqua_2024_2025.ipynb">Executed notebook</a>'
    hero = (f'<header class="hero"><p class="eyebrow">FIREBRIDGE · Team data walkthrough</p><h1>Two satellites.<br>One year of observations.</h1><p class="subtitle">Understand what MODIS Terra and Aqua measured, what the data can tell us, and how to build the next part of FIREBRIDGE.</p><p class="dates">17 January 2024 – 17 January 2025 · Both dates included · Worldwide · Standard processing</p><p class="hero-total">{count(total)} <small>recorded hot-pixel detections</small></p><div class="platform-strip"><span class="terra">Terra <strong>{count(platforms["Terra"]["rows"])}</strong></span><span class="aqua">Aqua <strong>{count(platforms["Aqua"]["rows"])}</strong></span></div><p class="artifact-links">'+artifacts+'</p></header>')
    mobile_contents = '<details class="mobile-contents"><summary>Jump to a section · 10 chapters</summary><nav aria-label="Mobile report contents"><ol>'+nav+'</ol></nav></details>'
    html = '<!doctype html><html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1"><meta name="description" content="A plain-language, evidence-based walkthrough of global MODIS Terra and Aqua detections for FIREBRIDGE."><title>MODIS Terra &amp; Aqua | FIREBRIDGE data walkthrough</title><style>'+STYLE+'</style></head><body><a class="skip" href="#main">Skip to the walkthrough</a><div class="shell"><nav class="rail" aria-label="Report contents"><p class="brand">FIREBRIDGE</p><p class="rail-label">Read in this order</p><ol>'+nav+'</ol><p class="rail-bottom">Ochre: Terra<br>Teal: Aqua<br><br>Charts are embedded for offline sharing.<br><a href="MODIS_EDA.md">Detailed Markdown report</a></p></nav><main id="main">'+hero+mobile_contents+"".join(r.html)+'<footer class="footer"><p>Prepared for the FIREBRIDGE team. Full-population summaries; raw data retained; scientific plots embedded. The requested historical point dataset is complete. Full observation masks and model evaluation are the next stage.</p><p>'+artifacts+'</p><p><a href="MODIS_EDA.md">Markdown report</a> · <a href="summary.json">Exact results</a> · <a href="SCIENCE_NOTES.md">Scientific source notes</a></p></footer></main></div>'+FIGURE_VIEWER+'</body></html>'
    (OUT / "MODIS_EDA.html").write_text(html,encoding="utf-8")
    title = "# MODIS Terra and Aqua: understanding the data for FIREBRIDGE\n\n**17 January 2024 – 17 January 2025, inclusive · Worldwide · Standard processing**\n\nThis report explains exact full-population analysis results and the next project steps. The HTML version contains all charts inline for offline sharing.\n\n[Presentation (PPTX)](MODIS_Terra_Aqua_2024_2025_Presentation.pptx) · [Slides (PDF)](MODIS_Terra_Aqua_2024_2025_Presentation.pdf) · [Speaker notes](PRESENTATION_SPEAKER_NOTES.md) · [Executed notebook](../../notebooks/MODIS_Terra_Aqua_2024_2025.ipynb)\n"
    (OUT / "MODIS_EDA.md").write_text(title+"\n".join(r.md),encoding="utf-8")
    print(json.dumps({"html":str(OUT/"MODIS_EDA.html"),"markdown":str(OUT/"MODIS_EDA.md"),"embedded_figures":r.figure_count,"html_bytes":len(html.encode())},indent=2))


if __name__ == "__main__":
    build()
