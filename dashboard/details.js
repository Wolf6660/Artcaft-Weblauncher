const $ = s => document.querySelector(s);
const name = decodeURIComponent(location.pathname.split('/').filter(Boolean)[1] || '');
$('#title').textContent = name;
document.title = name + ' · Artcraft Hub';
function add(tag, text, parent=$('#readme')) { const el=document.createElement(tag); el.textContent=text; parent.append(el); return el; }
// Convert Markdown, sanitize the generated HTML, then resolve repository-relative URLs.
function renderReadme(text, data) {
  const branch = encodeURIComponent(data.branch || 'main');
  const repo = 'https://github.com/storytold/'+encodeURIComponent(name);
  const rawBase = 'https://raw.githubusercontent.com/storytold/'+encodeURIComponent(name)+'/'+branch+'/';
  const readmePath = data.readme_path || 'README.md';
  const rawDirectory = new URL(readmePath, rawBase);
  const linkDirectory = new URL(readmePath, repo+'/blob/'+branch+'/');
  const fragment = DOMPurify.sanitize(marked.parse(text, {gfm:true}), {
    USE_PROFILES:{html:true}, RETURN_DOM_FRAGMENT:true,
    FORBID_TAGS:['script','style','iframe','object','embed','form','input','button','audio','video'],
    FORBID_ATTR:['style'], SANITIZE_NAMED_PROPS:true
  });
  const imageURL = value => {
    if(!value || !value.trim()) return null;
    try {
      let url = new URL(value, rawDirectory);
      if(url.hostname === 'github.com') {
        const match = /^\/([^/]+)\/([^/]+)\/(?:blob|raw)\/(.+)$/.exec(url.pathname);
        if(match) url = new URL('https://raw.githubusercontent.com/'+match[1]+'/'+match[2]+'/'+match[3]);
      }
      if(url.protocol !== 'https:' || !['raw.githubusercontent.com','img.shields.io','user-images.githubusercontent.com','private-user-images.githubusercontent.com'].includes(url.hostname)) return null;
      return '/api/readme-image?url='+encodeURIComponent(url.href);
    } catch { return null; }
  };
  fragment.querySelectorAll('img').forEach(img => {
    const src = imageURL(img.getAttribute('src') || '');
    img.removeAttribute('srcset'); img.removeAttribute('crossorigin');
    if(src) { img.src=src; img.loading='lazy'; img.decoding='async'; }
    else { img.removeAttribute('src'); }
  });
  fragment.querySelectorAll('source').forEach(source => {
    const parts=(source.getAttribute('srcset') || '').split(',').map(part=>{
      const [url, size] = part.trim().split(/\s+/);
      const resolved=imageURL(url);
      return resolved ? resolved+(size ? ' '+size : '') : '';
    }).filter(Boolean);
    if(parts.length) source.setAttribute('srcset',parts.join(', ')); else source.remove();
  });
  // Give headings stable anchors for GitHub's table-of-contents links.
  const usedIds=new Set();
  fragment.querySelectorAll('h1,h2,h3,h4,h5,h6').forEach(heading=>{
    let id=heading.textContent.trim().toLowerCase().replace(/[^\p{L}\p{N}_ -]/gu,'').replace(/ /g,'-');
    const base=id; let suffix=0; while(usedIds.has(id)) id=base+'-'+(++suffix);
    usedIds.add(id); heading.id='readme-'+id;
  });
  fragment.querySelectorAll('a').forEach(link => {
    const href=link.getAttribute('href'); if(!href) return;
    if(href.startsWith('#')) { link.href='#readme-'+href.slice(1); return; }
    try {
      const url=new URL(href,linkDirectory);
      if(!['https:','http:','mailto:'].includes(url.protocol)) { link.removeAttribute('href'); return; }
      link.href=url.href; link.target='_blank'; link.rel='noopener noreferrer';
    } catch { link.removeAttribute('href'); }
  });
  $('#readme').replaceChildren(fragment);
}

async function load() {
  try {
    const r=await fetch('/api/details/'+encodeURIComponent(name)); const data=await r.json();
    if(!r.ok) throw Error(data.error || 'Beschreibung konnte nicht geladen werden.');
    $('#description').textContent=data.description;
    renderReadme(data.readme, data);
    $('#status').textContent=(data.cached?'Gespeicherte Informationen · ':'')+'Stand: '+new Date(data.fetched*1000).toLocaleString('de-DE');
    const source=add('a','Original auf GitHub ↗',$('#detail-actions')); source.className='back'; source.href='https://github.com/storytold/'+encodeURIComponent(name); source.target='_blank'; source.rel='noreferrer';
    const statusResponse=await fetch('/api/status');
    if(statusResponse.ok) { const status=await statusResponse.json(); const app=status.apps.find(a=>a.id===name); if(app?.installed) { const start=add('a','Starten',$('#detail-actions')); start.className='start detail-start'; start.href='/'+encodeURIComponent(name)+'/'; start.target='_blank'; start.rel='noopener'; } }
  } catch(error) { $('#status').textContent=error.message; $('#status').className='error'; }
}
load();
