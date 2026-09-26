'use strict';
const paths = {
  home:'<path d="m3 10 9-7 9 7v10a1 1 0 0 1-1 1h-5v-7H9v7H4a1 1 0 0 1-1-1Z"/>',
  folder:'<path d="M3 7V5a1 1 0 0 1 1-1h5l2 3h9a1 1 0 0 1 1 1v11a1 1 0 0 1-1 1H4a1 1 0 0 1-1-1Z"/>',
  devices:'<rect x="2" y="4" width="14" height="11" rx="2"/><path d="M6 20h6m-3-5v5"/><rect x="17" y="9" width="5" height="12" rx="1"/>',
  settings:'<path d="m10 3-1 3-3 1-3-1-1 4 3 2v3l-1 2 3 3 3-1 2 1 1 2 4-1v-3l2-2 3-1-1-4-3-1-1-2V3Z"/><circle cx="12" cy="12" r="3"/>',
  cloud:'<path d="M7 18a5 5 0 1 1 .4-10 6 6 0 0 1 11.4 1.4A4.4 4.4 0 0 1 18 18Z"/>',
  wifi:'<path d="M2 8a17 17 0 0 1 20 0M5 12a12 12 0 0 1 14 0m-10 4a5 5 0 0 1 6 0"/><circle cx="12" cy="20" r=".7"/>',
  arrow:'<path d="M5 12h14m-5-5 5 5-5 5"/>',
  external:'<path d="M14 3h7v7m0-7L10 14m-3-9H4a1 1 0 0 0-1 1v14a1 1 0 0 0 1 1h14a1 1 0 0 0 1-1v-3"/>',
  copy:'<rect x="8" y="8" width="12" height="13" rx="2"/><path d="M15 8V3H3v13h5"/>',
  stop:'<rect x="6" y="6" width="12" height="12" rx="2"/>',
  play:'<path d="m8 4 12 8-12 8Z"/>',
  transfer:'<path d="M7 3v17m-4-4 4 4 4-4M17 21V4m-4 4 4-4 4 4"/>',
  upload:'<path d="M12 16V3m-5 5 5-5 5 5M3 15v5a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-5"/>',
  download:'<path d="M12 3v13m-5-5 5 5 5-5M3 16v4a1 1 0 0 0 1 1h16a1 1 0 0 0 1-1v-4"/>',
  search:'<circle cx="10" cy="10" r="6"/><path d="m15 15 6 6"/>',
  plus:'<path d="M12 5v14M5 12h14"/>',
  check:'<path d="m5 12 5 5L20 7"/>',
  close:'<path d="m6 6 12 12M6 18 18 6"/>',
  chevron:'<path d="m9 5 7 7-7 7"/>',
  file:'<path d="M14 2H5v20h14V7Zm0 0v6h5M8 13h8m-8 4h6"/>',
  phone:'<rect x="6" y="2" width="12" height="20" rx="2"/><path d="M10 18h4"/>',
  shield:'<path d="m12 2 9 4v6c0 5-9 10-9 10S3 17 3 12V6Z"/><path d="m8 12 3 3 5-6"/>',
  info:'<circle cx="12" cy="12" r="9"/><path d="M12 11v6m0-10v.5"/>',
  drive:'<path d="m8 3 7 0 8 14-4 5H4l-3-5Zm0 0 11 19M1 17h22M15 3 4 22"/>',
};
const icon = name => `<svg viewBox="0 0 24 24" aria-hidden="true">${paths[name] || paths.file}</svg>`;
const esc = value => String(value ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const $ = selector => document.querySelector(selector);
const state = {host:true, view:'home', status:{}, files:[], transfers:[], devices:[], crumbs:[], page:null, search:'', draftName:null, busy:false, loading:false, fileError:'', uploads:[], uploading:false};
const folderMime = 'application/vnd.google-apps.folder';
let token = new URLSearchParams(location.hash.slice(1)).get('token') || sessionStorage.getItem('locin-token');
if(token) { sessionStorage.setItem('locin-token', token); history.replaceState(null, '', location.pathname); }
let toastTimer, searchTimer, pollBusy=false, fileGeneration=0;

async function api(path, options={}) {
  const headers = {'X-Locin-Request':'1', ...(token ? {'X-Host-Token':token} : {}), ...options.headers};
  if(options.body && typeof options.body !== 'string' && !(options.body instanceof Blob)) {
    options.body=JSON.stringify(options.body); headers['Content-Type']='application/json';
  }
  const response=await fetch(path,{...options,headers});
  if(!response.ok) {
    const data=await response.json().catch(()=>({detail:'The host is unavailable. Check your connection.'}));
    throw new Error(typeof data.detail==='string' ? data.detail : 'Please check the values and try again.');
  }
  return response.json();
}
function toast(message,error=false) {
  const el=$('#toast');el.textContent=message;el.className='toast'+(error?' error':'');el.hidden=false;
  clearTimeout(toastTimer);toastTimer=setTimeout(()=>el.hidden=true,error?8500:4000);
}
function size(bytes) {
  if(bytes == null) return '—';
  if(!Number(bytes)) return '0 B';
  const n=Math.min(4,Math.floor(Math.log(Number(bytes))/Math.log(1024)));
  return `${(Number(bytes)/1024**n).toFixed(n ? 1 : 0)} ${['B','KB','MB','GB','TB'][n]}`;
}
function date(value) { return value ? new Date(value).toLocaleDateString(undefined,{month:'short',day:'numeric',year:'numeric'}) : '—'; }
function statusBadge() {const s=state.status.state||'Stopped';return `<span class="status ${s==='Error'?'error':s!=='Running'?'stopped':''}"><span class="tiny-dot"></span>${esc(s)}</span>`;}
function heading(title,subtitle,action='') {return `<div class="page-heading"><div><p class="eyebrow">YOUR DRIVE. A LITTLE CLOSER.</p><h1>${title}</h1><p class="subtitle">${subtitle}</p></div>${action}</div>`;}
function art() {return `<div class="hero-art" aria-hidden="true"><div class="orbit three"></div><div class="orbit two"></div><div class="orbit"></div><div class="hub">${icon('folder')}</div><span class="satellite one">${icon('cloud')}</span><span class="satellite two">${icon('phone')}</span><span class="satellite three">${icon('devices')}</span></div>`;}
function empty(symbol,title,description) {return `<div class="empty"><span class="empty-icon">${icon(symbol)}</span><h3>${title}</h3><p>${description}</p></div>`;}
function nav() {
  const items=state.host ? [['home','Home'],['folder','Files'],['devices','Devices'],['settings','Settings'],['info','About']] : [['folder','Files'],['transfer','Transfers']];
  $('#navigation').innerHTML=items.map(([key,label])=>`<button data-nav="${label.toLowerCase()}" class="${state.view===label.toLowerCase()?'active':''}" ${state.view===label.toLowerCase()?'aria-current="page"':''}>${icon(key)}<span>${label}</span>${state.view===label.toLowerCase()?'<i class="nav-dot"></i>':''}</button>`).join('');
  $('#page-label').textContent=state.view[0].toUpperCase()+state.view.slice(1);
  $('#workspace-label').textContent=state.status.local_name ? `${state.status.local_name}.loc.in` : 'Your shared Drive';
}
function alerts() {
  const s=state.status;const message=s.error || s.warning || (s.unavailable ? 'Google Drive is currently unavailable. loc.in is still running on your local network.' : (!s.connected && !state.host ? 'Google Drive disconnected. Reconnect Google Drive from the host application.' : ''));
  return message ? `<div class="alert" role="status">${esc(message)}</div>` : '';
}
function render() {
  nav();
  const views={home:home,files:files,devices:devices,settings:settings,transfers:transfers,about:about};
  $('#content').innerHTML=alerts()+(views[state.view]||home)();
}
function home() {
  const s=state.status;
  if(!s.connected || !s.folder_id) return setup();
  return heading('A home for your files.','Your Google Drive, right here on your network.',statusBadge())+`
    <section class="hero"><div class="hero-content"><p class="eyebrow">YOUR LOCAL ADDRESS</p><div class="address">${esc((s.address||'').replace('http://',''))}</div><p class="subtitle">${s.state==='Running'?'Custom address · requires network DNS. Open loc.in uses the working IP address.':'Start loc.in to make your files available on your network.'}</p><div class="hero-actions">
    ${s.state==='Running'?`<button class="primary" data-action="open-gateway">Open loc.in ${icon('external')}</button><button class="copy-button" data-action="copy-address" aria-label="Copy local address">${icon('copy')}</button><button class="text-button" data-action="stop" ${state.busy?'disabled':''}>${icon('stop')} Stop service</button>`:`<button class="primary" data-action="start" ${state.busy?'disabled':''}>${icon('play')} ${state.busy?'Starting…':'Start loc.in'}</button>`}
    </div></div>${art()}</section>
    <section class="stats" aria-label="Gateway overview"><div class="stat"><div class="stat-top"><span>Google Drive</span>${icon('drive')}</div><div class="stat-value connected"><span class="tiny-dot"></span>Connected</div><div class="stat-sub">${esc(s.email || 'Your Drive is ready')}</div></div><div class="stat"><div class="stat-top"><span>Devices</span>${icon('devices')}</div><div class="stat-value">${s.devices||0}<small>connected</small></div><div class="stat-sub">On your local network</div></div><div class="stat"><div class="stat-top"><span>Transfers</span>${icon('transfer')}</div><div class="stat-value">${s.active_transfers||0}<small>active</small></div><div class="stat-sub">${s.active_transfers?'A little back and forth':'All quiet. You’re up to date.'}</div></div></section>
    <div class="two-column"><section class="panel"><div class="panel-header"><h2>Recent transfers</h2><button class="text-button" data-nav="transfers">View all ${icon('arrow')}</button></div>${transferRows(state.transfers.slice(0,3))}</section><section class="panel"><div class="panel-header"><h2>Connected devices</h2><button class="text-button" data-nav="devices">View all ${icon('arrow')}</button></div>${deviceRows(state.devices.slice(0,3))}</section></div>
    <div class="tip">${icon('info')}<span><strong>Custom address needs network DNS.</strong> <button class="text-button" data-action="network-help">Setup instructions</button> ${s.fallback?`No DNS configured? Use <a href="${esc(s.fallback)}" target="_blank" rel="noopener">${esc(s.fallback)}</a>.`:'Your IP fallback will be ready when you start.'}</span><span class="tag">SIMPLY LOCAL</span></div>`;
}
function setup() {
  const s=state.status;
  return heading('Your Drive. Meet your network.','A few small steps to create your local space.',statusBadge())+`
  <div class="setup-layout"><section class="setup-card" aria-label="First-run setup">
    <div class="setup-step"><span class="step-number">${s.connected?icon('check'):'1'}</span><div class="step-content"><h3>Connect Google Drive</h3><p>${s.connected?esc(s.email||'Connected and ready to go.'):'Your files stay in Drive. We bring them a little closer.'}</p><button data-action="connect" ${state.busy?'disabled':''}>${icon('drive')}${s.connected?'Reconnect Google Drive':'Connect Google Drive'} ${icon('external')}</button></div></div>
    <div class="setup-step"><span class="step-number">2</span><div class="step-content"><h3>Give your space a name</h3><p>Your custom address. Network DNS setup is required.</p><div class="input-suffix"><input id="local-name" aria-label="Local name" maxlength="63" value="${esc(state.draftName??s.local_name??'locin')}" spellcheck="false" autocomplete="off"><span>.loc.in</span></div></div></div>
    <div class="setup-step"><span class="step-number">${s.folder_id?icon('check'):'3'}</span><div class="step-content"><h3>Choose a Drive folder</h3><p>${s.folder_id?`Sharing: ${esc(s.folder_name)}`:'Only this folder and what’s inside it will be shared.'}</p><button data-action="default-folder" ${!s.connected||state.busy?'disabled':''}>${icon('folder')} Use My Drive / loc.in</button> <button class="text-button" data-action="choose-folder" ${!s.connected||state.busy?'disabled':''}>Choose existing</button></div></div>
  </section><aside class="setup-aside">${art()}<h2>A little closer to your files.</h2><p>From your computer to the devices around you. No cables. No client apps. Just your browser.</p><div class="feature-line">${icon('wifi')} Available on your local network</div><div class="feature-line">${icon('shield')} Google credentials stay on this computer</div></aside></div>
  <div class="setup-start"><small>Install. Connect Drive. Choose a name. Start.</small><button class="primary" data-action="setup-start" ${!s.connected||!s.folder_id||state.busy?'disabled':''}>${state.busy?'Getting ready…':'Start loc.in'} ${icon('arrow')}</button></div>`;
}
function fileRows() {
  if(state.loading && !state.files.length)return '<div class="loading">Fetching your files…</div>';
  if(state.fileError)return empty('cloud','Your files are taking a moment.',`${esc(state.fileError)}<br><button class="text-button" data-action="refresh-files">Try again ${icon('arrow')}</button>`);
  if(!state.files.length)return empty('folder',state.search?'No matching files.':'A little room for something new.',state.search?'Try another name in this folder.':'Upload your first file, or create a folder to get organized.');
  return `<table class="file-table"><thead><tr><th>Name</th><th>Size</th><th class="modified">Modified</th><th><span class="mobile-hide">&nbsp;</span></th></tr></thead><tbody>${state.files.map((f,i)=>`<tr><td><button class="file-name" data-file="${i}"><span class="file-icon ${f.mimeType===folderMime?'':'doc'}">${icon(f.mimeType===folderMime?'folder':'file')}</span><span>${esc(f.name)}</span></button></td><td>${f.mimeType===folderMime?'Folder':size(f.size)}</td><td class="modified">${date(f.modifiedTime)}</td><td>${f.mimeType!==folderMime?`<a class="download-link" href="/api/files/${encodeURIComponent(f.id)}/download" aria-label="Download ${esc(f.name)}">${icon('download')}</a>`:''}</td></tr>`).join('')}</tbody></table>`;
}
function files() {
  return heading('Your files. All here.','A shared space for the things you want close.',`<span class="pill">${esc(state.status.folder_name||'loc.in')}</span>`)+`
  <div class="toolbar"><div class="search-wrap">${icon('search')}<input id="search" class="search" placeholder="Search this folder…" aria-label="Search this folder" value="${esc(state.search)}"></div><div class="toolbar-actions"><button data-action="new-folder">${icon('plus')} New folder</button><button class="primary" data-action="upload">${icon('upload')} Upload files</button></div></div>
  <div class="breadcrumbs"><button data-crumb="-1">${icon('folder')} ${esc(state.status.folder_name||'loc.in')}</button>${state.crumbs.map((c,i)=>`${icon('chevron')}<button data-crumb="${i}">${esc(c.name)}</button>`).join('')}</div>
  <section class="panel" id="file-drop">${fileRows()}${state.page?'<div class="load-more"><button data-action="more-files">Load more files</button></div>':''}</section>
  <div class="tip">${icon('upload')}<span>Drop files here to upload. Files go straight to your shared Drive folder.</span><span class="tag">NO LOCAL STORAGE</span></div>`;
}
function deviceRows(rows) {
  if(!rows.length)return empty('devices','A little company, whenever you’re ready.','Open your local address on another device.<br>It will appear here when it connects.');
  return rows.map(d=>`<div class="device-row"><span class="device-icon">${icon(/iPhone|iPad|Android/.test(d.name)?'phone':'devices')}</span><div class="device-info"><strong>${esc(d.name)}</strong><small>${esc(d.ip_address)}</small></div><span class="tiny-dot" title="Active in the last minute"></span></div>`).join('');
}
function devices() {
  return heading('Good company.','Devices that have visited your local space in the last minute.',`<span class="pill">${state.devices.length} connected</span>`)+`<section class="panel"><div class="panel-header"><h2>On your network</h2>${icon('wifi')}</div>${deviceRows(state.devices)}</section><div class="tip">${icon('info')}<span>Only devices using loc.in appear here. Device names are inferred from their browsers.</span></div>`;
}
function transferRows(rows) {
  const waiting=state.uploads.filter(u=>u.status==='Waiting');
  const queued=waiting.map(u=>`<div class="transfer-row"><div class="transfer-top"><strong>${esc(u.file.name)}</strong><span>Waiting</span></div><div class="transfer-meta"><span>Queued for upload</span><span>${size(u.file.size)}</span></div></div>`).join('');
  if(!rows.length&&!queued)return empty('transfer','Nothing moving. Everything in place.','Your uploads and downloads will appear here.<br>Go on, make yourself at home.');
  return queued+rows.map(t=>{
    const pct=t.status==='Completed'?100:(t.total?Math.min(99,Math.round(t.transferred/t.total*100)):0);
    const current=state.uploads.find(u=>u.id===t.id);
    return `<div class="transfer-row"><div class="transfer-top"><strong>${esc(t.filename)}</strong><span>${esc(t.status)}${['Uploading','Downloading'].includes(t.status)&&t.total?` · ${pct}%`:''}</span></div><div class="transfer-meta"><span>${t.direction==='upload'?'Device → Google Drive':'Google Drive → Device'}</span><span>${size(t.transferred)}${t.total?' / '+size(t.total):''}</span></div>${['Uploading','Downloading'].includes(t.status)?`<div class="progress" role="progressbar" aria-label="${esc(t.filename)}" aria-valuenow="${pct}" aria-valuemin="0" aria-valuemax="100"><span style="width:${pct}%"></span></div>`:''}${t.error?`<div class="transfer-meta">${esc(t.error)}</div>`:''}${current&&current.status==='Uploading'?`<button class="text-button danger" data-cancel="${esc(t.id)}">${current.cancel?'Cancelling after this chunk…':'Cancel upload'}</button>`:''}</div>`;
  }).join('');
}
function transfers() {return heading('A little back and forth.','Follow your files from here to there.')+`<section class="panel"><div class="panel-header"><h2>Transfers</h2>${icon('transfer')}</div>${transferRows(state.transfers)}</section>`;}
function settings() {
  const s=state.status;
  return heading('Make yourself at home.','Just the essentials. The way it should be.')+`<section class="panel settings-panel"><div class="panel-body"><div class="connection-line"><div><h3>Google Drive</h3><p>${s.connected?'● Connected':'Not connected'}${s.email?' · '+esc(s.email):''}</p></div><button data-action="connect">${icon('drive')} ${s.connected?'Reconnect':'Connect Google Drive'}</button></div>
  <div class="google-config"><span>${s.oauth_configured?'Google app configuration is ready.':'Google app configuration is needed.'}</span> <button class="text-button" data-action="google-help">Setup guide</button>${!s.connected?'<button class="text-button" data-action="import-oauth">Import Google JSON</button>':''}</div><div class="field"><label for="local-name">Local name</label><div class="input-suffix"><input id="local-name" value="${esc(state.draftName??s.local_name??'locin')}" maxlength="63" spellcheck="false" ${s.state==='Running'?'disabled':''}><span>.loc.in</span></div><small>Use letters, numbers, or hyphens (not underscores). Network DNS must point this address to the host.</small></div>
  <div class="field"><label>Shared Drive folder</label><div class="folder-field">${icon('folder')}<span>${s.folder_id?esc(s.folder_name):'Choose a folder'}</span><button data-action="choose-folder" ${!s.connected||s.state==='Running'?'disabled':''}>Change</button></div><small>Only files inside this folder are available to your network.</small></div>
  <div class="toggle-field"><div><label for="startup">Start with Windows</label><p>Start loc.in automatically when you sign in.</p></div><input type="checkbox" id="startup" ${s.start_at_login?'checked':''} ${s.state==='Running'?'disabled':''}></div>
  <div class="settings-actions"><button class="primary" data-action="save-settings" ${s.state==='Running'||state.busy?'disabled':''}>Save changes</button><small>${s.state==='Running'?'Stop loc.in from Home to change your settings.':'Changes stay on this computer.'}</small></div></div></section>`;
}

function googleSetupInstructions() {
  return `<ol class="guide-steps"><li>Open <a href="https://console.cloud.google.com/" target="_blank" rel="noopener">Google Cloud Console ${icon('external')}</a> and create or select a project.</li><li>In <strong>APIs &amp; Services → Library</strong>, enable <strong>Google Drive API</strong>.</li><li>Open <strong>Google Auth platform</strong>. Complete Branding and Audience. For External / Testing, add your Google email as a test user. For an eligible Workspace project, Internal limits sign-in to that organization.</li><li>In <strong>Data Access</strong>, add the Google Drive scope <code>https://www.googleapis.com/auth/drive</code>. This supports choosing existing folders.</li><li>In <strong>Clients → Create client</strong>, choose <strong>Desktop app</strong>. Download the JSON file. Do not choose Web application or Service account.</li><li>Import the JSON here, then click <strong>Connect Google Drive</strong> and sign in in your browser.</li></ol><p class="guide-note">This one-time configuration stays in this computer’s credential vault. It is not your Google password. A publisher can bundle this configuration for future installations.</p>`;
}
function googleSetupDialog() {
  showDialog(dialogHeading('Set up Google Drive')+googleSetupInstructions()+`<div class="dialog-actions"><button data-action="close-dialog">Close</button><button class="primary" data-action="import-oauth">${icon('upload')} Import Google JSON</button></div>`);
}
function networkHelp() {
  const s=state.status;
  return `<div class="guide-note"><strong>Your custom address: ${esc(s.address||'http://locin.loc.in')}</strong><p>A network DNS administrator must create an <strong>A record</strong> for <code>${esc((s.address||'http://locin.loc.in').split('//')[1].split(':')[0])}</code> pointing to <code>${esc(s.fallback ? new URL(s.fallback).hostname : 'the host’s local IP')}</code>. Reserve that IP in the router so it stays the same. Client devices must use that DNS server.</p><p>This does not publish the gateway to the internet. A subdomain under loc.in is not automatically created by this app. Use a domain you control or an administrator-managed internal DNS override.</p><p>Without custom DNS, use <strong>${esc(s.discovery_address||'http://locin.local')}</strong> on devices supporting local discovery, or ${s.fallback?`<a href="${esc(s.fallback)}" target="_blank" rel="noopener">${esc(s.fallback)}</a>`:'the IP fallback shown after starting'}. Keep any displayed <code>:8000</code> suffix.</p></div>`;
}
function about() {
  return heading('About loc.in','Your Google Drive, shared with the devices around you.', '<span class="pill">Version 1.0.1</span>')+`
    <section class="hero"><div class="hero-content"><p class="eyebrow">INSTALL. CONNECT. CHOOSE A NAME. START.</p><h2 class="about-title">One computer. A shared local space.</h2><p class="about-intro">loc.in connects a Google Drive folder to your local network. Keep the host running, and open its address from a phone, tablet, or computer. No client app is needed.</p></div>${art()}</section>
    <div class="about-grid">
      <section class="panel"><div class="panel-header"><h2>${icon('folder')} Files, kept simple</h2></div><div class="panel-body"><ul><li>Browse folders and search the current folder.</li><li>Upload multiple files, download files, and create folders.</li><li>Share only your selected Drive folder and its contents.</li><li>Download Google Docs as PDF, Sheets as XLSX, and Slides as PPTX.</li></ul></div></section>
      <section class="panel"><div class="panel-header"><h2>${icon('transfer')} Built for everyday transfers</h2></div><div class="panel-body"><ul><li>Large files move in chunks with bounded memory.</li><li>Uploaded files are not permanently stored on the host.</li><li>Follow transfer progress and recent activity.</li><li>See devices that recently used the gateway.</li></ul></div></section>
      <section class="panel"><div class="panel-header"><h2>${icon('shield')} Who can access your files?</h2></div><div class="panel-body"><p>Any device that can reach the gateway from the host’s allowed local subnet can use the shared folder. There is currently no per-device login or employee verification.</p><p>An office LAN works when devices are on that subnet and the firewall allows it. Separate VLANs, guest Wi-Fi, VPNs, and other branches are not automatically included. Organization membership alone does not grant or restrict access.</p><p>Google credentials and host controls stay on the host. Local file traffic uses HTTP; use a trusted network. No internet port forwarding is enabled.</p></div></section>
      <section class="panel"><div class="panel-header"><h2>${icon('cloud')} What needs to stay on?</h2></div><div class="panel-body"><p>Keep the host computer awake, loc.in running, and the host connected to the internet for Drive operations.</p><p>If internet access goes down, local pages and service status still load. Browsing Drive, uploads, and downloads need the connection to return.</p><p>Closing the host window keeps the app in the tray when available. Choose Exit from the tray to shut it down.</p></div></section>
    </div>
    <section class="panel about-guide"><div class="panel-header"><h2>Connect Google Drive</h2><span class="pill">${state.status.oauth_configured?'Configured':'One-time setup'}</span></div><div class="panel-body">${googleSetupInstructions()}${!state.status.connected?'<button class="primary" data-action="import-oauth">Import Google JSON</button>':''}<p class="guide-note">After connecting: choose a name, choose a Drive folder, and start loc.in. Google Workspace administrators may need to allow this OAuth app. Public distribution requires the applicable Google OAuth verification.</p></div></section>
    <section class="panel about-guide"><div class="panel-header"><h2>Your custom-name.loc.in address</h2>${icon('wifi')}</div><div class="panel-body">${networkHelp()}</div></section>`;
}
async function refresh() {
  const was=state.status.connected;
  state.status=await api('/api/status');
  const results=await Promise.allSettled([api('/api/transfers'),...(state.host?[api('/api/devices')]:[])]);
  if(results[0].status==='fulfilled')state.transfers=results[0].value.transfers;
  if(state.host&&results[1].status==='fulfilled')state.devices=results[1].value.devices;
  if(was===false&&state.status.connected)toast('Google Drive connected. Choose your shared folder.');
}
async function navigate(view) {
  state.view=view;render();
  if(view==='files')await loadFiles();
  else if(view!=='settings'){await refresh();render();}
}
async function loadFiles(append=false) {
  const generation=++fileGeneration;
  state.loading=true;state.fileError='';
  if(!append)state.files=[];
  // Keep the search input mounted while typing.
  const drawRows=()=>{const el=$('#file-drop');if(el)el.innerHTML=fileRows()+(state.page?'<div class="load-more"><button data-action="more-files">Load more files</button></div>':'');};
  drawRows();
  try {
    const parent=state.crumbs.at(-1)?.id||'';
    const params=new URLSearchParams({parent,search:state.search,...(append&&state.page?{page:state.page}:{})});
    const data=await api('/api/files?'+params);
    if(generation!==fileGeneration)return;
    state.files=append?[...state.files,...data.files]:data.files;state.page=data.nextPageToken||null;
  }catch(e){if(generation===fileGeneration){state.fileError=e.message;state.page=null;}}
  finally{if(generation===fileGeneration){state.loading=false;if(state.view==='files')drawRows();}}
}
async function saveSettings(folderId) {
  const result=await api('/api/settings',{method:'PUT',body:{local_name:$('#local-name')?.value??state.draftName??state.status.local_name??'locin',folder_id:folderId||state.status.folder_id||'',start_at_login:$('#startup')?$('#startup').checked:!!state.status.start_at_login}});
  state.draftName=null;
  return result;
}
let folderStack=[],folderPage=null,folderItems=[];
function dialogHeading(title) {return `<div class="dialog-heading"><h2>${title}</h2><button data-action="close-dialog" aria-label="Close">${icon('close')}</button></div>`;}
function showDialog(html){$('#dialog-content').innerHTML=html;if(!$('#dialog').open)$('#dialog').showModal();}
async function folderPicker(append=false) {
  const current=folderStack.at(-1)||{id:'root',name:'My Drive'};
  showDialog(dialogHeading('Choose a Drive folder')+'<div class="loading">Opening Drive folders…</div>');
  try{
    const data=await api('/api/drive/folders?'+new URLSearchParams({parent:current.id,...(append&&folderPage?{page:folderPage}:{})}));
    folderItems=append?[...folderItems,...data.files]:data.files;folderPage=data.nextPageToken;
    showDialog(dialogHeading('Choose a Drive folder')+`<p>Everything inside the selected folder will be available on your local network.</p><div class="folder-path">My Drive ${folderStack.map(f=>' / '+esc(f.name)).join('')}</div>${folderStack.length?'<button class="text-button" data-action="folder-back">← Back</button>':''}<div class="folder-list">${folderItems.length?folderItems.map((f,i)=>`<button class="folder-option" data-pick-folder="${i}">${icon('folder')} ${esc(f.name)} ${icon('chevron')}</button>`).join(''):empty('folder','No subfolders.','You can share this folder.')}</div>${folderPage?'<button class="text-button" data-action="folder-more">More folders</button>':''}<div class="dialog-actions"><button data-action="close-dialog">Cancel</button><button class="primary" data-action="select-folder" ${current.id==='root'?'disabled':''}>Share this folder</button></div>`);
  }catch(e){showDialog(dialogHeading('Choose a Drive folder')+`<div class="alert">${esc(e.message)}</div>`);}
}
function queueFiles(files) {
  const parent=state.crumbs.at(-1)?.id||'';
  for(const file of files)state.uploads.push({file,parent,status:'Waiting',cancel:false});
  toast(`${files.length} file${files.length===1?'':'s'} added to uploads.`);
  void processUploads();
}
async function processUploads() {
  if(state.uploading)return;
  state.uploading=true;
  try{
    for(const upload of state.uploads.filter(u=>u.status==='Waiting')) {
      upload.status='Uploading';
      try{
        const session=await api('/api/files/upload',{method:'POST',body:{name:upload.file.name,parent:upload.parent,size:upload.file.size,mime:upload.file.type||'application/octet-stream'}});
        upload.id=session.id;let offset=0,complete=false;
        do{
          if(upload.cancel){await api(`/api/files/upload/${session.id}`,{method:'DELETE'});upload.status='Cancelled';break;}
          const blob=upload.file.slice(offset,offset+session.chunk_size);
          const result=await api(`/api/files/upload/${session.id}?offset=${offset}`,{method:'PUT',body:blob,headers:{'Content-Type':'application/octet-stream'}});
          offset=result.transferred;complete=result.completed;
          if(!complete && offset===upload.file.size)throw new Error('Google Drive did not finalize the upload. Please retry.');
          await refresh().catch(()=>{});
          if(['home','transfers'].includes(state.view)&&!$('#dialog').open)render();
        }while(!complete);
        if(complete){upload.status='Completed';toast(`${upload.file.name} uploaded.`);}
      }catch(e){upload.status='Failed';if(upload.id)await api(`/api/files/upload/${upload.id}`,{method:'DELETE'}).catch(()=>{});toast(`${upload.file.name}: ${e.message}`,true);}
      if(state.view==='files')await loadFiles();
    }
  }finally{state.uploading=false;state.uploads=state.uploads.filter(u=>u.status==='Waiting');if(state.uploads.length)void processUploads();}
}
const actions={
  'connect':async()=>{if(!state.status.oauth_configured){googleSetupDialog();return;}const data=await api('/api/auth/google',{method:'POST'});if(data.opened)toast('Complete the connection in your browser, then return here.');else showDialog(dialogHeading('Connect Google Drive')+`<p>Sign in securely with Google in your browser. Then return here to finish setup.</p><a class="primary button-link" href="${esc(data.url)}" target="_blank" rel="noopener">Continue to Google ${icon('external')}</a>`);},
  'google-help':()=>googleSetupDialog(),
  'import-oauth':()=>$('#oauth-picker').click(),
  'network-help':()=>showDialog(dialogHeading('Set up your custom address')+networkHelp()+`<div class="dialog-actions"><button data-action="close-dialog">Done</button></div>`),
  'default-folder':async()=>{await saveSettings();await api('/api/drive/default-folder',{method:'POST'});await refresh();render();toast('Your loc.in folder is ready.');},
  'choose-folder':async()=>{folderStack=[];folderPage=null;await folderPicker();},
  'folder-back':async()=>{folderStack.pop();await folderPicker();},
  'folder-more':async()=>folderPicker(true),
  'select-folder':async()=>{await saveSettings(folderStack.at(-1).id);$('#dialog').close();state.crumbs=[];await refresh();render();toast('Shared folder updated.');},
  'save-settings':async()=>{await saveSettings();await refresh();render();toast('Your settings are saved.');},
  'setup-start':async()=>{await saveSettings();await actions.start();},
  'start':async()=>{state.status=await api('/api/service/start',{method:'POST'});render();if(state.status.error)toast(state.status.error,true);},
  'stop':async()=>{state.status=await api('/api/service/stop',{method:'POST'});await refresh();render();toast('loc.in is stopped.');},
  'open-gateway':()=>window.open(state.status.fallback||state.status.discovery_address,'_blank','noopener'),
  'copy-address':async()=>{try{await navigator.clipboard.writeText(state.status.address);toast('Local address copied.');}catch{showDialog(dialogHeading('Your local address')+`<p>Copy this address to share it with a device on your Wi-Fi.</p><input class="search" readonly value="${esc(state.status.address)}">`);}},
  'upload':()=>$('#file-picker').click(),
  'refresh-files':()=>loadFiles(),
  'more-files':()=>loadFiles(true),
  'close-dialog':()=>$('#dialog').close(),
  'new-folder':()=>{showDialog(dialogHeading('A new place for your files.')+'<div class="field"><label for="folder-name">Folder name</label><input id="folder-name" maxlength="255" placeholder="Untitled folder"></div><div class="dialog-actions"><button data-action="close-dialog">Cancel</button><button class="primary" data-action="create-folder">Create folder</button></div>');$('#folder-name').focus();},
  'create-folder':async()=>{await api('/api/folders',{method:'POST',body:{name:$('#folder-name').value,parent:state.crumbs.at(-1)?.id||''}});$('#dialog').close();await loadFiles();toast('Folder created.');},
};
document.addEventListener('click',async event=>{
  const button=event.target.closest('button');if(!button||button.disabled)return;
  try{
    if(button.dataset.nav){await navigate(button.dataset.nav);return;}
    if(button.dataset.crumb!==undefined){state.crumbs=state.crumbs.slice(0,Number(button.dataset.crumb)+1);state.search='';render();await loadFiles();return;}
    if(button.dataset.file!==undefined){
      const f=state.files[Number(button.dataset.file)];
      if(f.mimeType===folderMime){state.crumbs.push({id:f.id,name:f.name});state.search='';render();await loadFiles();}
      else showDialog(dialogHeading('File details')+`<div class="detail-icon">${icon('file')}</div><h2 class="detail-name">${esc(f.name)}</h2><div class="detail-meta"><span>${size(f.size)}</span><span>${date(f.modifiedTime)}</span></div><p>Download to open this file on your device.${f.mimeType.startsWith('application/vnd.google-apps.')?' Google Docs, Sheets, and Slides are exported to PDF, XLSX, and PPTX.':''}</p><div class="dialog-actions"><a class="primary button-link" href="/api/files/${encodeURIComponent(f.id)}/download">${icon('download')} Download file</a></div>`);
      return;
    }
    if(button.dataset.pickFolder!==undefined){folderStack.push(folderItems[Number(button.dataset.pickFolder)]);await folderPicker();return;}
    if(button.dataset.cancel){const item=state.uploads.find(u=>u.id===button.dataset.cancel);if(item)item.cancel=true;button.textContent='Cancelling after this chunk…';return;}
    if(button.dataset.action&&actions[button.dataset.action]){button.disabled=true;state.busy=true;await actions[button.dataset.action]();}
  }catch(e){toast(e.message,true);}finally{state.busy=false;button.disabled=false;if(['start','stop','setup-start','default-folder','select-folder','save-settings'].includes(button.dataset.action))render();}
});
document.addEventListener('input',event=>{if(event.target.id==='search'){state.search=event.target.value;clearTimeout(searchTimer);searchTimer=setTimeout(()=>loadFiles(),300);}if(event.target.id==='local-name')state.draftName=event.target.value;});
$('#file-picker').addEventListener('change',event=>{queueFiles([...event.target.files]);event.target.value='';});
$('#oauth-picker').addEventListener('change',async event=>{
  const file=event.target.files[0];event.target.value='';if(!file)return;
  try{
    if(file.size>16384)throw new Error('Choose the Google Desktop app JSON file (smaller than 16 KB).');
    const contents=await file.text();
    await api('/api/auth/config',{method:'POST',body:contents,headers:{'Content-Type':'application/json'}});
    $('#dialog').close();await refresh();render();toast('Google configuration saved. Click Connect Google Drive to sign in.');
  }catch(e){toast(e.message,true);}
});
document.addEventListener('dragover',event=>{if(state.view==='files'){event.preventDefault();$('#file-drop')?.classList.add('drop-active');}});
document.addEventListener('dragleave',event=>{if(!event.relatedTarget)$('#file-drop')?.classList.remove('drop-active');});
document.addEventListener('drop',event=>{if(state.view==='files'){event.preventDefault();$('#file-drop')?.classList.remove('drop-active');if(event.dataTransfer.files.length)queueFiles([...event.dataTransfer.files]);}});
window.addEventListener('beforeunload',event=>{if(state.uploading){event.preventDefault();event.returnValue='';}});
async function boot(){
  $('#workspace-icon').innerHTML=icon('folder');$('#network-icon').innerHTML=icon('wifi');$('#topbar-icon').innerHTML=icon('home');
  try{
    state.host=(await api('/mode')).host;state.view=state.host?'home':'files';$('#role-avatar').textContent=state.host?'H':'L';
    if(state.host)await api('/api/session',{method:'POST'});
    await refresh();render();if(!state.host)await loadFiles();
    setInterval(async()=>{
      if(pollBusy||document.hidden)return;pollBusy=true;
      try{await refresh();if(['home','devices','transfers'].includes(state.view)&&!state.busy&&!$('#dialog').open&&!['INPUT','TEXTAREA'].includes(document.activeElement.tagName))render();}
      catch(e){toast(e.message,true);}finally{pollBusy=false;}
    },4000);
  }catch(e){$('#content').innerHTML=heading('Your local space.','Let’s get you connected.')+`<div class="alert">${esc(e.message)}</div>`;}
}
void boot();
