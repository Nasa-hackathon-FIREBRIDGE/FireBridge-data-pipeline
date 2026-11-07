import fs from 'node:fs/promises';
import path from 'node:path';
import {ppt,slide,text,paragraphs,table,chart,finish,OUTPUT,colors,number,percent} from './deck_helpers.mjs';
import {sources,teaching,sourceNote} from './content_notes.mjs';

function csvParse(raw) {
  const rows=[];let row=[],value='',quoted=false;
  for(let i=0;i<raw.length;i++) {
    const c=raw[i];
    if(c==='"'){if(quoted&&raw[i+1]==='"'){value+='"';i++;}else quoted=!quoted;}
    else if(c===','&&!quoted){row.push(value);value='';}
    else if(c==='\n'&&!quoted){row.push(value.replace(/\r$/,''));if(row.some(v=>v!==''))rows.push(row);row=[];value='';}
    else value+=c;
  }
  if(value||row.length){row.push(value);rows.push(row);}
  const head=rows.shift();return rows.map(r=>Object.fromEntries(head.map((h,i)=>[h,r[i]??''])));
}
const load=async name=>csvParse(await fs.readFile(path.join(OUTPUT,'tables',`${name}.csv`),'utf8'));
const summary=JSON.parse(await fs.readFile(path.join(OUTPUT,'summary.json'),'utf8'));
const [monthly,confidence,typeRows,hemisphere,frpQuantiles,timing,footprint,regionalGrid,pilotRows,pilotMonthly,recurrence]=await Promise.all(
  ['monthly','confidence','type','hemisphere_monthly','exact_quantiles','solar_hour_bins','january_footprint_summary','regional_grid_sensitivity','pilot_detections','pilot_monthly','pilot_5km_recurrence'].map(load));
const evidence=name=>`reports/modis_2024_2025/tables/${name}.csv`;
const localNotes=(script,...tables)=>`${script}\n\nLocal evidence: ${tables.map(evidence).join(', ')}`;
const data=Object.fromEntries(summary.platforms.map(r=>[r.satellite,r]));
const sats=['Terra','Aqua'];
const total=summary.analysis_rows;
const pct=n=>percent(n/total);
const qty=v=>Number(v).toLocaleString('en-US',{maximumFractionDigits:1});
const mdMonth=m=>new Date(`${m}-01T00:00:00Z`).toLocaleString('en-US',{month:'short',year:'2-digit',timeZone:'UTC'});
const notes=[];
function newSlide(title,subtitle,script){const s=slide(title,subtitle,script);notes.push({slide:ppt.slides.items.length,title,notes:script});return s;}
function caption(s,value){text(s,value,70,614,1140,48,23,{color:colors.muted});}

// 1. Minimal title slide.
{
  const s=ppt.slides.add();s.background.fill=colors.ink;
  text(s,'MODIS Terra and Aqua',70,210,1120,95,68,{bold:true,color:'#FFFFFF'});
  text(s,'Understanding the data for FIREBRIDGE',70,320,1110,60,36,{color:'#FFFFFF'});
  text(s,'17 January 2024 to 17 January 2025',70,425,1080,52,29,{color:'#D8E3DD'});
  const n='This presentation explains the global MODIS point data, then applies the findings to the northern Morocco pilot in the FIREBRIDGE blueprint. The window includes both endpoint dates. Read the charts as recorded satellite detections. This EDA does not establish wildfire incident counts, burned hectares or model accuracy.\n\nLocal evidence: reports/modis_2024_2025/summary.json and FIREBRIDGE_Blueprint.md.';
  s.speakerNotes.textFrame.setText(n);notes.push({slide:1,title:'MODIS Terra and Aqua',notes:n});
}
// 2. Scope and file provenance.
{
  const audit=summary.january_overlap_audit;
  const s=newSlide('The analysis covers 367 UTC dates','Worldwide points, with a northern Morocco study window',localNotes(
    `The inputs comprise ${summary.monthly_files} standard monthly files from the MODIS Fire Science Team. Exact date filtering gives ${number(summary.target_raw_rows)} input rows. Native exact-row deduplication and quarantine produce ${number(total)} analysis rows. We independently compare ${number(audit.umd_january_rows)} January 1–17 2025 rows to the user\'s FIRMS archive across every shared native field. ${number(audit.matched_rows_all_shared_native_fields)} rows match. Full export coverage means the monthly archives are available for the window. Actual cloud-free observation coverage remains unknown from points.`, 'input_inventory'));
  table(s,[['Scope','Evidence'],['Requested dates','17 Jan 2024 through 17 Jan 2025, inclusive'],['Standard archive',`${summary.monthly_files} monthly MCD14ML files, Collection 6.1`],['Analysis detections',number(total)],['Dates with global detections',`${summary.global_dates_with_any_exported_detection} of 367`],['Independent January audit',`${number(audit.matched_rows_all_shared_native_fields)} shared-field matches`]],{height:410,columnWidths:[340,800]});
  caption(s,'January 2024 contains 15 included dates. January 2025 contains 17.');
}
// 3. A real row, with readable field groups.
{
  const example=pilotRows.find(r=>r.satellite==='Aqua'&&r.daynight==='D'&&r.type==='0'&&Number(r.confidence)>=30)??pilotRows[0];
  if(!example)throw new Error('No actual pilot row available for teaching example');
  const time=`${example.acq_date} ${example.acq_time.slice(0,2)}:${example.acq_time.slice(2)} UTC`;
  const s=newSlide('One row is one thermal detection','A real Aqua example inside the northern Morocco study rectangle',sourceNote('attributes',teaching.row,evidence('pilot_detections')));
  table(s,[['Field group','Example','Meaning'],['Acquisition',time,'The satellite observation time'],['Platform',example.satellite,'MODIS on the Aqua satellite'],['Pixel center',`${Number(example.latitude).toFixed(4)}, ${Number(example.longitude).toFixed(4)}`,'Latitude and longitude in degrees'],['Brightness',`${qty(example.brightness)} K / ${qty(example.bright_t31)} K`,'Thermal band temperatures'],['FRP',`${qty(example.frp)} MW`,'Radiative power inside the pixel'],['Quality and class',`${example.confidence} confidence, ${example.daynight}, type ${example.type}`,'Native algorithm fields']],{height:410,columnWidths:[220,470,450],fontSize:23});
  caption(s,'One ongoing fire can produce many rows. A row does not define a fire perimeter.');
}
// 4. Platform comparison.
{
  const s=newSlide('Terra and Aqua sample different times','Platform differences include fire evolution and observation conditions',sourceNote('products',teaching.satellite,evidence('platform_summary')));
  table(s,[['Metric','Terra','Aqua'],['All detections',...sats.map(x=>number(data[x].rows))],['Daytime fraction',...sats.map(x=>percent(data[x].day_rows/data[x].rows))],['Type 0 and confidence ≥30',...sats.map(x=>number(data[x].type0_conf30_rows))],['Median FRP',...sats.map(x=>`${qty(data[x].median_frp_MW)} MW`)],['Daytime median solar time',...sats.map(x=>`${Number(data[x].day_median_solar_hour).toFixed(2)} h`)]],{height:395,columnWidths:[480,330,330]});
  caption(s,'Keep Terra and Aqua separate. FIREBRIDGE uses Aqua as its reference convention.');
}
// 5. Integrity and unusual values.
{
  const q=summary.quality,a=summary.january_overlap_audit;
  const s=newSlide('Data validity and observation coverage','The table checks answer whether fields and records are usable',localNotes(teaching.quality+'\nNegative FRP values remain review flags and do not enter FRP quantiles. Zero FRP is reported separately. The January overlap audit checks every shared native field as a multiset, so it does not rely on row order.', 'quality_checks','january_overlap_differences'));
  table(s,[['Check','Rows'],['Exact duplicate excess',number(q.exact_duplicate_excess)],['Rows quarantined by validation',number(q.quarantined_rows)],['Invalid UTC acquisition',number(q.invalid_datetime)],['Invalid coordinates',number(q.invalid_coordinates)],['Negative FRP values',number(q.negative_frp)],['Zero FRP values',number(q.zero_frp)]],{height:405,columnWidths:[840,300]});
  caption(s,`January audit: ${percent(a.matched_rows_all_shared_native_fields/a.umd_january_rows)} of UMD rows match all shared fields.`);
}
// 6. Global temporal pattern, accounting for partial months.
{
  const months=[...new Set(monthly.map(r=>r.month))].sort();
  const combined=months.map(month=>({month,rate:monthly.filter(r=>r.month===month).reduce((a,r)=>a+Number(r.detections_per_requested_calendar_day),0)}));
  const peak=combined.sort((a,b)=>b.rate-a.rate)[0];
  const s=newSlide(`Global recorded activity peaks in ${mdMonth(peak.month)}`,'All detections per included calendar day, by acquisition month',localNotes(teaching.monthly,'monthly'));
  chart(s,'line',months.map(m=>`${mdMonth(m)}${['2024-01','2025-01'].includes(m)?'*':''}`),sats.map(sat=>({name:sat,values:months.map(month=>Number(monthly.find(r=>r.month===month&&r.satellite===sat)?.detections_per_requested_calendar_day??0))})),{axisTitle:'Detections / calendar day'});
  caption(s,'* Partial January windows. Rates describe recorded detections without a coverage correction.');
}
// 7. Global geography through hemisphere totals.
{
  const months=[...new Set(hemisphere.map(r=>r.month))].sort();
  const days=Object.fromEntries(monthly.map(r=>[r.month,Number(r.days_in_requested_window)]));
  const s=newSlide('Northern and southern patterns differ','Both platforms combined, all detections per included calendar day',localNotes(
    'This chart groups latitude at or above zero as Northern and below zero as Southern. It compares recorded detection patterns and mixes many climates and land uses inside each hemisphere. It does not imply a single fire season for either hemisphere. One-degree spatial bins and the detailed global map in the report provide a closer geographic view. One-degree bins differ in area with latitude, so their raw counts cannot establish geographic fire intensity.','hemisphere_monthly','global_1degree_bins'));
  chart(s,'line',months.map(m=>`${mdMonth(m)}${['2024-01','2025-01'].includes(m)?'*':''}`),['Northern','Southern'].map((h,i)=>({name:`${h} hemisphere`,fill:[colors.aqua,colors.terra][i],values:months.map(m=>hemisphere.filter(r=>r.month===m&&r.hemisphere===h).reduce((a,r)=>a+Number(r.rows),0)/days[m])})),{axisTitle:'Detections / calendar day'});
  caption(s,'Global totals combine regional calendars. The report includes spatial bins for closer inspection.');
}
// 8. Quality sensitivity.
{
  const classes=['low','nominal','high'];
  const s=newSlide('Confidence changes which rows we retain','Native score classes, shown as a share of each platform',sourceNote('guide',teaching.confidence,evidence('confidence')));
  chart(s,'bar',['Low <30','Nominal 30–79','High ≥80'],sats.map(sat=>{
    const values=classes.map(c=>Number(confidence.find(r=>r.satellite===sat&&r.confidence_class===c)?.rows??0)/data[sat].rows);
    return {name:sat,values,valuesFormatCode:'0.0%',dataLabelOverrides:values.map((v,idx)=>({idx,text:percent(v),showValue:false,position:'outEnd',textStyle:{typeface:'Nimbus Sans',fontSize:22,fill:colors.ink,bold:true}}))};
  }),{format:'0%',axisTitle:'Share of detections',config:{dataLabels:{showValue:true,position:'outEnd',textStyle:{typeface:'Nimbus Sans',fontSize:22,fill:colors.ink}},yAxis:{numberFormatCode:'0%',min:0,max:1,textStyle:{typeface:'Nimbus Sans',fontSize:20,fill:colors.muted},majorGridlines:{fill:colors.grid,width:1}}}});
  caption(s,'Project baseline: type 0 with confidence ≥30. Keep all and ≥80 views for sensitivity.');
}
// 9. Radiative power quantiles.
{
  const s=newSlide('FRP has a long upper tail','Exact quantiles across each platform, in megawatts',sourceNote('attributes',teaching.frp,evidence('platform_summary')));
  table(s,[['FRP summary','Terra','Aqua'],['Median',...sats.map(x=>qty(data[x].median_frp_MW))],['95th percentile',...sats.map(x=>qty(data[x].p95_frp_MW))],['99th percentile',...sats.map(x=>qty(data[x].p99_frp_MW))],['Maximum',...sats.map(x=>qty(data[x].max_frp_MW))],['Zero FRP rows',...sats.map(x=>number(data[x].zero_frp_rows))]],{height:400,columnWidths:[480,330,330]});
  caption(s,'FRP measures power at acquisition time. Negative values are excluded from these quantiles.');
}
// 10. Actual acquisition regime.
{
  const s=newSlide('Daytime detection times show separate regimes','Approximate local solar hour, conditional on a recorded daytime detection',localNotes(teaching.timing,'solar_hour_bins','platform_daynight_summary'));
  chart(s,'line',Array.from({length:24},(_,i)=>String(i)),sats.map(sat=>({name:sat,values:Array.from({length:24},(_,i)=>Number(timing.find(r=>r.satellite===sat&&r.daynight==='D'&&Number(r.solar_hour_bin)===i)?.rows??0)/data[sat].day_rows)})),{format:'0%',axisTitle:'Share of daytime detections'});
  caption(s,'Solar hour ≈ UTC hour + longitude / 15. It differs from civil time and orbit crossing time.');
}
// 11. Footprint source limitation.
{
  const f=Object.fromEntries(footprint.map(r=>[r.satellite,r]));
  const s=newSlide('Pixel footprints vary across the swath','Measured FIRMS dimensions for 1–17 January 2025 only',sourceNote('attributes',teaching.footprint,evidence('january_footprint_summary')));
  table(s,[['Dimension','Terra','Aqua'],['Median scan width',...sats.map(x=>`${qty(f[x].scan_median_km)} km`)],['95th percentile scan width',...sats.map(x=>`${qty(f[x].scan_p95_km)} km`)],['Median track height',...sats.map(x=>`${qty(f[x].track_median_km)} km`)],['95th percentile track height',...sats.map(x=>`${qty(f[x].track_p95_km)} km`)],['Rows in this overlap',...sats.map(x=>number(f[x].rows))]],{height:395,columnWidths:[480,330,330]});
  caption(s,'The full MCD14ML window has a sample index, with no explicit scan/track dimensions.');
}
// 12. Native inferred type.
{
  const labels=['Presumed vegetation','Active volcano','Other static land','Offshore'];
  const s=newSlide('Thermal anomalies have inferred source types','Native type codes support review, with no incident-level verification',sourceNote('guide',teaching.sources,evidence('type')));
  table(s,[['Type','Terra detections','Aqua detections'],...labels.map((label,i)=>[`${i}: ${label}`,...sats.map(sat=>number(typeRows.find(r=>r.satellite===sat&&Number(r.type)===i)?.rows??0))])],{height:350,columnWidths:[480,330,330]});
  caption(s,'Type 0 can include agricultural burning. Recurrence alone does not justify deletion.');
}
// 13. Study area evidence.
{
  const pilot=Object.fromEntries(summary.regions.filter(r=>r.region==='pilot').map(r=>[r.satellite,r]));
  const months=[...new Set(monthly.map(r=>r.month))].sort();
  const n=sats.reduce((a,sat)=>a+Number(pilot[sat]?.rows??0),0);
  const retained=sats.reduce((a,sat)=>a+Number(pilot[sat]?.type0_conf30_rows??0),0);
  const s=newSlide(`The Morocco pilot contains ${number(n)} detections`,`${number(retained)} meet type 0 and confidence ≥30 inside the study rectangle`,localNotes(teaching.morocco+'\nThe monthly bars show recorded detections. A zero bar only means no exported hotspot in this rectangle for that month and platform. It does not indicate complete clear-sky coverage or absence of all burning.', 'regional_summary','pilot_monthly','regional_grid_sensitivity'));
  chart(s,'bar',months.map(m=>`${mdMonth(m)}${['2024-01','2025-01'].includes(m)?'*':''}`),sats.map(sat=>({name:sat,values:months.map(month=>Number(pilotMonthly.find(r=>r.month===month&&r.satellite===sat)?.rows??0))})),{axisTitle:'Recorded detections'});
  caption(s,'Bounds: 6.4°W to 4.5°W, 34.5°N to 35.9°N. This is a study rectangle, not all Morocco.');
}
// 14. Response definition.
{
  const s=newSlide('The FIREBRIDGE response','A supported Aqua-equivalent detection indicator in a 5 km cell',teaching.target+'\n\nProject source: FIREBRIDGE_Blueprint.md, sections on the scientific target and matched opportunity table.');
  paragraphs(s,[
    'Reference: at least one retained Aqua detection in a supported cell and pass.',
    'VIIRS provides the prediction features for a withheld-Aqua experiment.',
    'Terra keeps a separate adapter because its observation regime differs.',
    'The EDA prepares the native record. Observation support defines the labels.'
  ],70,204,1130,29,103);
}
// 15. Required absence information.
{
  const s=newSlide('Observation masks make absence labels possible','A point table only describes detected thermal anomalies',sourceNote('aqua',teaching.masks)+'\nCompatible geolocation source: '+sources.geo+'\nProject source: FIREBRIDGE_Blueprint.md.');
  table(s,[['Cell/pass state','Evidence needed'],['Retained detection','Point detection plus the defined inclusion rule'],['Usable observation with no retained detection','Full fire mask, QA and geolocation'],['Cloud, invalid or missing observation','Full mask and an explicit exclusion reason'],['Aqua science files','MYD14 plus collection-compatible MYD03'],['Terra science files','MOD14 plus collection-compatible MOD03']],{height:405,columnWidths:[495,645]});
  caption(s,'An archive with rows on every date does not prove that every cell had a usable observation.');
}
// 16. Next deliverable and baseline.
{
  const s=newSlide('The next deliverable is a supported pilot table','A small reproducible season and area before model training',teaching.next+'\n\nProject source: FIREBRIDGE_Blueprint.md, acquisition, pairing and evaluation design.');
  paragraphs(s,[
    '1. Retrieve a manageable season of matched fire masks and geolocation.',
    '2. Build cell/pass support with usable-land fractions and exclusion reasons.',
    '3. Evaluate the proposed 5 km, 30-minute and 80% shared-land rules.',
    '4. Freeze a transparent baseline, then test with withheld time and geography.'
  ],70,202,1130,29,105);
  caption(s,'Deliver the native observations, support flags and baseline errors together.');
}

await fs.writeFile(path.join(OUTPUT,'PRESENTATION_SPEAKER_NOTES.md'), '# MODIS Terra and Aqua presentation notes\n\n'+notes.map(r=>`## ${r.slide}. ${r.title}\n\n${r.notes}`).join('\n\n'));
await finish(process.env.DECK_FILENAME??'MODIS_Terra_Aqua_2024_2025_Presentation.pptx');
