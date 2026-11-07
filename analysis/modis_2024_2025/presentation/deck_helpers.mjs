import fs from 'node:fs/promises';
import path from 'node:path';
import {pathToFileURL} from 'node:url';
import {Presentation, PresentationFile} from '@oai/artifact-tool';

export const WORKSPACE = '/home/da-rog/dev_projects/FIREBRIDGE-project';
export const SKILL = '/home/da-rog/.codex/plugins/cache/openai-primary-runtime/presentations/26.905.11957/skills/presentations';
export const BUILD = path.join(WORKSPACE, 'reports/modis_2024_2025/.build/presentation');
export const OUTPUT = path.join(WORKSPACE, 'reports/modis_2024_2025');
export const RUNTIME = '/home/da-rog/.cache/codex-runtimes/codex-primary-runtime/dependencies';
const utils = await import(pathToFileURL(path.join(SKILL, 'container_tools/artifact_tool_utils.mjs')).href);
export const font = utils.resolvePresentationFont({fontFamily:'Nimbus Sans'});
export const colors = {ink:'#17332F', muted:'#536864', paper:'#F9FAF7', aqua:'#146C94', terra:'#C66435', grid:'#D5DEDA', accent:'#C66435'};
export const ppt = Presentation.create({slideSize:{width:1280,height:720}});
export const tableOwners = [];
export const chartOwners = [];
export const number = value => Number(value).toLocaleString('en-US');
export const percent = value => `${(100*Number(value)).toFixed(1)}%`;

export function text(slide, value, left, top, width, height, size=27, extra={}) {
  const shape = slide.shapes.add({geometry:'textbox',position:{left,top,width,height},fill:'none',line:{fill:'none',width:0}});
  shape.text = String(value);
  shape.text.style = {typeface:font,fontSize:size,color:colors.ink,autoFit:'none',...extra};
  return shape;
}

export function slide(title, subtitle='', notes='') {
  const out = ppt.slides.add();
  out.background.fill=colors.paper;
  text(out,title,70,44,1140,85,44,{bold:true});
  if(subtitle) text(out,subtitle,70,128,1140,52,23,{color:colors.muted});
  text(out,String(ppt.slides.items.length),1140,666,70,30,16,{color:colors.muted,alignment:'right'});
  out.speakerNotes.textFrame.setText(notes);
  return out;
}

export function paragraphs(slide, items, left=70, top=205, width=1138, size=29, gap=103) {
  items.forEach((item,i)=>text(slide,item,left,top+i*gap,width,gap-15,size));
}

export function table(slide, values, opts={}) {
  const cols=values[0].length;
  const out=slide.tables.add({rows:values.length,columns:cols,left:opts.left??70,top:opts.top??194,width:opts.width??1140,height:opts.height??390,values,
    columnWidths:opts.columnWidths});
  const all=out.cells.block({row:0,column:0,rowCount:values.length,columnCount:cols});
  all.assign({fill:colors.paper,textStyle:{typeface:font,fontSize:opts.fontSize??24,color:colors.ink},margins:{left:16,right:12,top:6,bottom:6},anchor:'center'});
  out.borders.assign({style:'solid',fill:colors.grid,width:0.8});
  const header=out.cells.block({row:0,column:0,rowCount:1,columnCount:cols});
  header.assign({fill:colors.ink,textStyle:{typeface:font,fontSize:opts.fontSize??24,color:'#FFFFFF',bold:true}});
  out.styleOptions={headerRow:true,bandedRows:false};
  tableOwners.push(ppt.slides.items.length);
  return out;
}

export function chart(slide,type,categories,series,opts={}) {
  const out=slide.charts.add(type,{position:{left:70,top:190,width:1140,height:410},categories,
    // Excel stores at most 15 significant digits. Keep source tables exact and
    // materialize an intentional 12-digit display snapshot for editable charts.
    series:series.map((s,i)=>({...s,values:s.values.map(v=>Number(Number(v).toPrecision(12))),fill:s.fill??[colors.terra,colors.aqua][i%2],line:{fill:s.fill??[colors.terra,colors.aqua][i%2],width:3},marker:{symbol:'none'}})),
    hasLegend:series.length>1,legend:{position:'bottom',overlay:false,textStyle:{typeface:font,fontSize:22,fill:colors.ink}},
    xAxis:{textStyle:{typeface:font,fontSize:20,fill:colors.muted},line:{fill:colors.grid,width:1},majorGridlines:null},
    yAxis:{numberFormatCode:opts.format??'#,##0',min:0,textStyle:{typeface:font,fontSize:20,fill:colors.muted},majorGridlines:{fill:colors.grid,width:1},title:opts.axisTitle?{text:opts.axisTitle,textStyle:{typeface:font,fontSize:20,fill:colors.muted}}:undefined},
    chartFill:colors.paper,plotAreaFill:colors.paper,chartLine:{fill:'none',width:0},plotAreaLine:{fill:'none',width:0},
    barOptions:{direction:'column',grouping:'clustered',gapWidth:70},lineOptions:{smooth:false},
    dataLabels:{showValue:false,textStyle:{typeface:font,fontSize:20,fill:colors.ink}},...opts.config});
  utils.applyPresentationChartFont(out,{fontFamily:font});
  chartOwners.push(ppt.slides.items.length);
  return out;
}

export async function finish(filename='MODIS_Terra_Aqua_2024_2025_Presentation.pptx') {
  await fs.mkdir(BUILD,{recursive:true});
  const receiptDir=path.join(WORKSPACE,'analysis/modis_2024_2025/presentation/.validation');
  await fs.mkdir(receiptDir,{recursive:true});
  const candidate=path.join(BUILD,'candidate.pptx');
  await (await PresentationFile.exportPptx(ppt)).save(candidate);
  for(let i=0;i<ppt.slides.items.length;i++) {
    const current=ppt.slides.items[i];
    const preview=await ppt.export({slide:current,format:'png',scale:1});
    await fs.writeFile(path.join(BUILD,`slide-${String(i+1).padStart(2,'0')}.png`),new Uint8Array(await preview.arrayBuffer()));
    const layout=await current.export({format:'layout'});
    await fs.writeFile(path.join(BUILD,`slide-${String(i+1).padStart(2,'0')}.layout.json`),await layout.text());
  }
  const result=await utils.finalizePresentation({
    workspaceDir:WORKSPACE,candidatePath:candidate,finalPath:path.join(OUTPUT,filename),
    pythonExecutable:path.join(RUNTIME,'python/bin/python3.12'),
    integrityValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_package_integrity.py'),
    layoutValidatorPath:path.join(SKILL,'container_tools/inspect_presentation_layout_geometry.py'),
    layoutArgs:['--expected-slide-size-emu','12192000,6858000','--validate-bullet-geometry','--validate-heading-fit',...tableOwners.flatMap(n=>['--require-native-table-slide',String(n)])],
    requiredNativeTableOwnerSlides:tableOwners,requiredNativeChartOwnerSlides:chartOwners,
    materializeLiteralChartWorkbooks:true,fontPolicy:{basis:'design',families:[font]},verifyArtifactToolImport:true,
    receiptPath:path.join(receiptDir,`${filename}.validation.json`),
  });
  console.log(JSON.stringify({finalPath:path.join(OUTPUT,filename),slides:ppt.slides.items.length,font,tableOwners,chartOwners,result},null,2));
}
