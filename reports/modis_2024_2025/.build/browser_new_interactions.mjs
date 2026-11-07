import fs from 'node:fs/promises';import path from 'node:path';
const out='/home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025/.build/html_qa_2';
const tab=(await(await fetch('http://127.0.0.1:9338/json/list')).json()).find(t=>t.type==='page');
const ws=new WebSocket(tab.webSocketDebuggerUrl);await new Promise(r=>ws.addEventListener('open',r,{once:true}));
let id=0;const p=new Map();ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&p.has(m.id)){const q=p.get(m.id);p.delete(m.id);m.error?q.reject(m.error):q.resolve(m.result)}});
const send=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;p.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}))});
const ev=async(expression)=>{const r=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(r.exceptionDetails)throw r.exceptionDetails;return r.result.value};
const delay=()=>new Promise(r=>setTimeout(r,150));
const key=async(k,code)=>{await send('Input.dispatchKeyEvent',{type:'keyDown',key:k,code:k,windowsVirtualKeyCode:code});await send('Input.dispatchKeyEvent',{type:'keyUp',key:k,code:k,windowsVirtualKeyCode:code});await delay()};
const checks={};
for(const width of [1440,375]){
 await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
 await ev(`document.querySelectorAll('details').forEach(e=>e.open=false);window.scrollTo({top:0,behavior:'instant'})`);
 const a={};checks[width]=a;
 a.mobileContents=await ev(`(()=>{const e=document.querySelector('.mobile-contents');return {visible:getComputedStyle(e).display!=='none',open:e.open,afterHero:e.getBoundingClientRect().top>document.querySelector('.hero').getBoundingClientRect().bottom-1}})()`);
 a.tableCuesVisible=await ev(`[...document.querySelectorAll('.table-scroll-hint')].every(e=>getComputedStyle(e).display!=='none')`);
 if(width===375){
  await ev(`document.querySelector('.mobile-contents summary').click()`);a.contentsToggle=await ev(`document.querySelector('.mobile-contents').open`);
  await ev(`document.querySelector('.mobile-contents a[href="#quality"]').click()`);await new Promise(r=>setTimeout(r,750));a.contentsAnchor=await ev(`Math.abs(document.getElementById('quality').getBoundingClientRect().top-24)<8`);
  await ev(`document.querySelector('.mobile-contents').open=false`);
 }
 await ev(`document.querySelector('.figure-open').scrollIntoView({block:'center',behavior:'instant'});document.querySelector('.figure-open').focus()`);
 const point=await ev(`(()=>{const r=document.querySelector('.figure-open').getBoundingClientRect();return {x:r.x+r.width/2,y:r.y+r.height/2}})()`);
 await send('Input.dispatchMouseEvent',{type:'mousePressed',...point,button:'left',clickCount:1});await send('Input.dispatchMouseEvent',{type:'mouseReleased',...point,button:'left',clickCount:1});await delay();
 a.dialog=await ev(`(()=>{const d=document.querySelector('dialog'),v=d.querySelector('.figure-viewport'),i=v.querySelector('img'),r=d.getBoundingClientRect();return {open:d.open,focusedClose:document.activeElement.classList.contains('viewer-close'),insideViewport:r.x>=0&&r.right<=innerWidth+1,viewportWidth:v.clientWidth,imageWidth:i?.getBoundingClientRect().width,naturalWidth:i?.naturalWidth,scrollWidth:v.scrollWidth,docWidth:document.documentElement.scrollWidth}})()`);
 const s=await send('Page.captureScreenshot',{format:'png',fromSurface:true});await fs.writeFile(`${out}/${width}_figure_dialog.png`,Buffer.from(s.data,'base64'));
 await key('Tab',9);a.dialogFocusTrap=await ev(`document.querySelector('dialog').contains(document.activeElement)`);
 await ev(`document.querySelector('.figure-viewport').scrollLeft=300;document.querySelector('.figure-viewport').scrollTop=120`);a.figureScroll=await ev(`({x:document.querySelector('.figure-viewport').scrollLeft,y:document.querySelector('.figure-viewport').scrollTop})`);
 await key('Escape',27);a.escape=await ev(`({closed:!document.querySelector('dialog').open,focusRestored:document.activeElement===document.querySelector('.figure-open'),cleared:document.querySelector('.figure-viewport').children.length===0})`);
 await ev(`document.querySelector('.figure-open').click()`);await delay();await ev(`document.querySelector('.viewer-close').click()`);await delay();a.close=await ev(`({closed:!document.querySelector('dialog').open,focusRestored:document.activeElement===document.querySelector('.figure-open')})`);
 a.documentWidth=await ev('document.documentElement.scrollWidth');
 a.allFigureButtons=await ev(`[...document.querySelectorAll('.figure-open')].length`);
}
checks.localLinks=[];const hrefs=await ev(`[...document.querySelectorAll('a')].map(a=>a.getAttribute('href')).filter(x=>!x.startsWith('http')&&!x.startsWith('#'))`);
for(const href of hrefs){let exists=true;try{await fs.access(path.resolve('/home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025',href))}catch{exists=false};checks.localLinks.push({href,exists})}
await fs.writeFile(`${out}/new_interactions.json`,JSON.stringify(checks,null,2));console.log(JSON.stringify(checks));ws.close();
