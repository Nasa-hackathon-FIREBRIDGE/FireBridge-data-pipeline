import fs from 'node:fs/promises';
import path from 'node:path';
const out='/home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025/.build/html_qa';
const tab=(await (await fetch('http://127.0.0.1:9338/json/list')).json()).find(x=>x.type==='page');
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
let id=0;const p=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(m.error):q.resolve(m.result)}});
const send=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;p.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}))});
const ev=async(expression)=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});return r.result.value};
const tests={};
for(const width of [1440,768,375]){
 await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
 const rects=await ev(`(()=>{document.querySelectorAll('details').forEach(e=>e.open=true);return [...document.querySelectorAll('details:has(figure)')].map((e,i)=>{const r=e.getBoundingClientRect();return {i,y:r.y+scrollY,height:r.height}})})()`);
 for(const r of rects){const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,fromSurface:true,clip:{x:0,y:r.y,width,height:r.height,scale:1}});await fs.writeFile(`${out}/${width}_details_figure_${r.i}.png`,Buffer.from(shot.data,'base64'))}
 tests[width]=await ev(`(()=>({documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,tableScrolls:[...document.querySelectorAll('.table-wrap')].map(e=>({scrollWidth:e.scrollWidth,clientWidth:e.clientWidth,tabindex:e.getAttribute('tabindex')}))}))()`);
}
await ev(`document.querySelectorAll('details').forEach(e=>e.open=false);document.querySelector('details summary').click();`);
tests.detailsClickToggles=await ev(`document.querySelector('details').open`);
await ev(`document.querySelector('.rail a[href="#quality"]').click()`);
await new Promise(r=>setTimeout(r,750));
tests.navScrollsToTarget=await ev(`Math.abs(document.getElementById('quality').getBoundingClientRect().top-24)<8`);
const hrefs=await ev(`[...document.querySelectorAll('a')].map(a=>a.getAttribute('href')).filter(x=>!x.startsWith('http')&&!x.startsWith('#'))`);
tests.localLinkFiles=[];
for(const href of hrefs){const target=path.resolve('/home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025',href);let exists=true;try{await fs.access(target)}catch{exists=false};tests.localLinkFiles.push({href,exists})}
await ev(`document.querySelector('.table-wrap').focus()`);
tests.focusVisible=await ev(`(()=>{const c=getComputedStyle(document.activeElement);return {outlineStyle:c.outlineStyle,outlineWidth:c.outlineWidth}})()`);
await send('Input.dispatchKeyEvent',{type:'keyDown',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});await send('Input.dispatchKeyEvent',{type:'keyUp',key:'ArrowRight',code:'ArrowRight',windowsVirtualKeyCode:39});
await new Promise(r=>setTimeout(r,100));tests.keyboardTableScroll=await ev(`document.activeElement.scrollLeft`);
tests.focusAfterKeyboard=await ev(`(()=>{const e=document.activeElement,c=getComputedStyle(e);return {focusVisible:e.matches(':focus-visible'),outlineStyle:c.outlineStyle,outlineWidth:c.outlineWidth}})()`);
await fs.writeFile(`${out}/interaction_checks.json`,JSON.stringify(tests,null,2));
console.log(JSON.stringify({detailsClickToggles:tests.detailsClickToggles,navScrollsToTarget:tests.navScrollsToTarget,brokenLocalLinks:tests.localLinkFiles.filter(x=>!x.exists),focusVisible:tests.focusVisible,keyboardTableScroll:tests.keyboardTableScroll}));
ws.close();
