import fs from 'node:fs/promises';
const out='/home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025/.build/html_qa';
await fs.mkdir(out,{recursive:true});
const list=await (await fetch('http://127.0.0.1:9338/json/list')).json();
const tab=list.find(x=>x.type==='page');
const ws=new WebSocket(tab.webSocketDebuggerUrl);
await new Promise((resolve,reject)=>{ws.addEventListener('open',resolve,{once:true});ws.addEventListener('error',reject,{once:true})});
let id=0;const pending=new Map();
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.id&&pending.has(m.id)){const {resolve,reject}=pending.get(m.id);pending.delete(m.id);m.error?reject(m.error):resolve(m.result)}});
const send=(method,params={})=>new Promise((resolve,reject)=>{const k=++id;pending.set(k,{resolve,reject});ws.send(JSON.stringify({id:k,method,params}))});
const evaluate=async(expression)=>{const a=await send('Runtime.evaluate',{expression,returnByValue:true,awaitPromise:true});if(a.exceptionDetails)throw a.exceptionDetails;return a.result.value};
await send('Page.enable');await send('Runtime.enable');
const errors=[];
ws.addEventListener('message',e=>{const m=JSON.parse(e.data);if(m.method==='Runtime.exceptionThrown')errors.push(m.params.exceptionDetails)});
await send('Page.navigate',{url:'file:///home/da-rog/dev_projects/FIREBRIDGE-project/reports/modis_2024_2025/MODIS_EDA.html'});
for(let i=0;i<30;i++){if(await evaluate('document.readyState')==='complete')break;await new Promise(r=>setTimeout(r,200));}
await evaluate(`(async()=>{for(const i of document.images)i.loading='eager';await Promise.all([...document.images].map(i=>i.decode().catch(()=>null)));return true})()`);
const checks={};
for(const width of [1440,768,375]){
 await send('Emulation.setDeviceMetricsOverride',{width,height:1000,deviceScaleFactor:1,mobile:false});
 await evaluate('window.scrollTo(0,0)');
 const info=await evaluate(`(()=>{const rect=e=>{const r=e.getBoundingClientRect();return {x:r.x,y:r.y+scrollY,width:r.width,height:r.height}};return {viewportWidth:innerWidth,documentWidth:document.documentElement.scrollWidth,bodyWidth:document.body.scrollWidth,documentHeight:document.documentElement.scrollHeight,sections:[...document.querySelectorAll('header.hero,main section,footer.footer')].map(e=>({id:e.id||e.tagName.toLowerCase(),...rect(e)})),images:[...document.images].map(e=>({alt:e.alt,loaded:e.complete&&e.naturalWidth>0,...rect(e)})),localLinks:[...document.querySelectorAll('a')].filter(a=>!a.href.startsWith('http')).map(a=>({text:a.textContent,href:a.getAttribute('href')})),bodyFont:getComputedStyle(document.body).fontSize}})()`);
 checks[width]=info;
 for(const s of [{id:'top',y:0,height:1400},...info.sections]){
  for(let offset=0;offset<s.height;offset+=1800){
   const clip={x:0,y:s.y+offset,width,height:Math.min(1800,s.height-offset),scale:1};
   const shot=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,fromSurface:true,clip});
   await fs.writeFile(`${out}/${width}_${s.id}_${offset}.png`,Buffer.from(shot.data,'base64'));
  }
 }
 const small=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,fromSurface:true,clip:{x:0,y:0,width,height:Math.min(28000,info.documentHeight),scale:1}});
 await fs.writeFile(`${out}/${width}_full.png`,Buffer.from(small.data,'base64'));
}
await send('Emulation.setDeviceMetricsOverride',{width:1440,height:1000,deviceScaleFactor:1,mobile:false});
checks.details=await evaluate(`(()=>{const d=[...document.querySelectorAll('details')];d.forEach(e=>e.open=true);return d.map(e=>({title:e.querySelector('summary').textContent,open:e.open}))})()`);
const expanded=await send('Page.captureScreenshot',{format:'png',captureBeyondViewport:true,fromSurface:true,clip:{x:0,y:0,width:1440,height:Math.min(32000,await evaluate('document.documentElement.scrollHeight')),scale:1}});
await fs.writeFile(`${out}/1440_expanded_full.png`,Buffer.from(expanded.data,'base64'));
checks.internalAnchorsValid=await evaluate(`[...document.querySelectorAll('a[href^="#"]')].every(a=>document.getElementById(a.getAttribute('href').slice(1)))`);
checks.errors=errors;
await fs.writeFile(`${out}/browser_checks.json`,JSON.stringify(checks,null,2));
console.log(JSON.stringify({out,widths:[1440,768,375],overflow:checks[375].documentWidth>375,loadedImages:checks[1440].images.filter(i=>i.loaded).length,totalImages:checks[1440].images.length,internalAnchorsValid:checks.internalAnchorsValid,errors:errors.length}));
ws.close();
