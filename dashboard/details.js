const $ = s => document.querySelector(s);
const name = decodeURIComponent(location.pathname.split('/').filter(Boolean)[1] || '');
$('#title').textContent = name;
document.title = name + ' · Artcraft Hub';
function add(tag, text, parent=$('#readme')) { const el=document.createElement(tag); el.textContent=text; parent.append(el); return el; }
// Render a safe, readable Markdown subset. Upstream HTML and scripts remain inert text.
function renderReadme(text) {
  const root=$('#readme'); root.replaceChildren();
  let code=null, paragraph=[], list=null;
  const flush=()=>{ if(paragraph.length) { add('p',paragraph.join(' ')); paragraph=[]; } };
  for(const line of text.split('\n')) {
    if(/^\s*```/.test(line)) { flush(); list=null; if(code) code=null; else code=add('code','',add('pre','')); continue; }
    if(code) { code.textContent+=line+'\n'; continue; }
    const heading=/^(#{1,6})\s+(.+)$/.exec(line);
    const item=/^\s*(?:[-*+] |\d+\. )(.+)$/.exec(line);
    if(heading) { flush(); list=null; add('h'+Math.min(heading[1].length+1,6),heading[2]); }
    else if(item) { flush(); if(!list) list=add('ul',''); add('li',item[1],list); }
    else if(!line.trim()) { flush(); list=null; }
    else { list=null; paragraph.push(line); }
  }
  flush();
}
async function load() {
  try {
    const r=await fetch('/api/details/'+encodeURIComponent(name)); const data=await r.json();
    if(!r.ok) throw Error(data.error || 'Beschreibung konnte nicht geladen werden.');
    $('#description').textContent=data.description;
    renderReadme(data.readme);
    $('#status').textContent=(data.cached?'Gespeicherte Informationen · ':'')+'Stand: '+new Date(data.fetched*1000).toLocaleString('de-DE');
    const source=add('a','Original auf GitHub ↗',$('#detail-actions')); source.className='back'; source.href='https://github.com/storytold/'+encodeURIComponent(name); source.target='_blank'; source.rel='noreferrer';
    const statusResponse=await fetch('/api/status');
    if(statusResponse.ok) { const status=await statusResponse.json(); const app=status.apps.find(a=>a.id===name); if(app?.installed) { const start=add('a','Starten',$('#detail-actions')); start.className='start detail-start'; start.href='/'+encodeURIComponent(name)+'/'; start.target='_blank'; start.rel='noopener'; } }
  } catch(error) { $('#status').textContent=error.message; $('#status').className='error'; }
}
load();
