let state = {apps: []}, pending = false, rendered = '';
const $ = s => document.querySelector(s);
function element(tag, text, cls) { const el = document.createElement(tag); el.textContent = text; if (cls) el.className = cls; return el; }
async function action(action, id) {
  if (pending || state.busy) return;
  pending = true; render();
  try {
    const response = await fetch('/api/action', {method:'POST', headers:{'Content-Type':'application/json','X-CSRF-Token':state.csrf}, body:JSON.stringify({action,id})});
    const result = await response.json();
    if (!response.ok) throw Error(result.error || 'Ein Vorgang läuft bereits.');
    await refresh();
  } catch (error) { $('#status').textContent = error.message; }
  finally { pending = false; render(); }
}
function button(label, command, app, cls) {
  const b = element('button', label, cls);
  b.disabled = state.busy || pending;
  b.onclick = () => action(command, app.id);
  return b;
}
function row(app) {
  const card = element('article', '', 'app-row');
  const icon = element('div', app.id.slice(0,2).toUpperCase(), 'icon');
  if (app.icon && app.icon.startsWith('/api/icon/')) {
    const img = document.createElement('img'); img.alt = ''; img.loading = 'lazy';
    img.onload = () => icon.classList.add('loaded'); img.onerror = () => img.remove(); icon.append(img); img.src = app.icon;
  }
  const info = element('div', '', 'app-info');
  const title = element('a', app.id, 'app-name'); title.href = '/details/'+encodeURIComponent(app.id); title.title = 'Beschreibung anzeigen';
  info.append(title, element('p', app.description || 'Beschreibung auf GitHub ansehen.', 'description'));
  const version = app.installed ? 'Installiert: '+app.installed : (app.release ? 'Version '+app.release.tag : '');
  info.append(element('span', version, 'version'));
  if (app.installed && app.update) info.append(element('span', 'Update verfügbar', 'badge update'));
  const actions = element('div', '', 'row-actions');
  if (app.installed) {
    const split = element('div', '', 'split-button');
    const start = element('a', 'Starten', 'start'); start.href = '/'+encodeURIComponent(app.id)+'/'; start.target = '_blank'; start.rel = 'noopener';
    const menu = element('details', '', 'dropdown');
    const toggle = element('summary', '▾'); toggle.setAttribute('aria-label', 'Aktionen für '+app.id);
    const options = element('div', '', 'dropdown-menu');
    if (app.release && app.update) options.append(button('Aktualisieren', 'install', app, 'menu-item'));
    if (app.rollback) options.append(button('Vorherige Version', 'rollback', app, 'menu-item'));
    options.append(button('Deinstallieren', 'uninstall', app, 'menu-item danger'));
    menu.append(toggle, options); split.append(start, menu); actions.append(split);
    menu.addEventListener('toggle', () => { if(menu.open) document.querySelectorAll('details.dropdown').forEach(other => { if(other!==menu) other.open=false; }); });
  } else if (app.release) actions.append(button('Installieren', 'install', app, 'install'));
  card.append(icon, info, actions); return card;
}
function render() {
  $('#check').disabled = state.busy || pending;
  $('#checked').textContent = state.checked ? 'Zuletzt geprüft: ' + new Date(state.checked*1000).toLocaleString('de-DE') : 'Noch keine Prüfung';
  const query = $('#search').value.toLowerCase();
  const apps = state.apps.filter(a => (a.id+' '+a.description).toLowerCase().includes(query));
  const signature = JSON.stringify([apps, Boolean(state.busy), pending, query]);
  if(signature === rendered) return; // Keep an open dropdown and keyboard focus during polling.
  rendered = signature;
  for (const [selector, list, empty] of [
    ['installed', apps.filter(a=>a.installed), 'Noch keine Anwendungen installiert. Entdecke die verfügbaren Anwendungen darunter.'],
    ['available', apps.filter(a=>!a.installed && a.release), state.busy ? 'Verfügbare Anwendungen werden ermittelt …' : 'Keine weiteren Anwendungen verfügbar. Suche nach Updates, um den Katalog zu aktualisieren.']
  ]) {
    const container = $('#'+selector+'-apps'); container.replaceChildren();
    $('#'+selector+'-count').textContent = list.length;
    if (!list.length) container.append(element('p',query ? 'Keine Anwendungen für diese Suche.' : empty, 'empty'));
    for(const app of list) container.append(row(app));
  }
}
async function refresh() {
  try { const r=await fetch('/api/status'); if(!r.ok) throw Error('Status konnte nicht geladen werden ('+r.status+').'); state=await r.json(); $('#status').textContent=state.error || (state.busy?'Vorgang läuft …':state.message); $('#status').className=state.error?'error':''; render(); }
  catch(e) { $('#status').textContent=e.message; }
}
$('#check').onclick=()=>action('check',''); $('#search').oninput=render;
document.addEventListener('click',event=>{ if(!event.target.closest('.dropdown')) document.querySelectorAll('.dropdown[open]').forEach(menu=>menu.open=false); });
document.addEventListener('keydown',event=>{ if(event.key==='Escape') document.querySelectorAll('.dropdown[open]').forEach(menu=>{ menu.open=false; menu.querySelector('summary').focus(); }); });
refresh(); setInterval(refresh,2500);
