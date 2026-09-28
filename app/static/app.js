'use strict';
const $=s=>document.querySelector(s);
const esc=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
let mode='maps', selected=null, pollBusy=false, currentDetail=null, currentPanel='investigate';
const terminal=new Set(['ready','ready_with_gaps','failed','cancelled','interrupted']);
function toast(message,error=false){const t=$('#toast');t.textContent=message;t.classList.toggle('error',error);t.hidden=false;clearTimeout(t.timer);t.timer=setTimeout(()=>t.hidden=true,error?12000:5500);}
async function api(url,body){
if(url==='/api/scans'&&body?.mode==='single')body={...body,business_name:$('#businessName').value.trim(),urls:[$('#businessUrl').value.trim()],category:'',city:'',max_businesses:1};
const options=body===undefined?{}:{method:'POST',headers:{'Content-Type':'application/json','X-BV-Local':'1'},body:JSON.stringify(body)};const r=await fetch(url,options);const d=await r.json().catch(()=>({detail:'Response could not be read.'}));if(!r.ok)throw new Error(typeof d.detail==='string'?d.detail:JSON.stringify(d.detail));return d;}
function badge(status){const style=['failed','interrupted'].includes(status)?'bad':status==='ready_with_gaps'?'warning':['running','queued'].includes(status)?'active':'';return `<span class="badge ${style}">${esc(status.replaceAll('_',' '))}</span>`;}
function renderKeepingOpen(d){
  const root=$('#detail');
  const key=el=>{const path=[];for(let node=el;node&&node!==root;node=node.parentElement){if(node.matches('details'))path.unshift(node.dataset.business||node.querySelector(':scope > summary')?.textContent||'');}return JSON.stringify(path);};
  const same=root.dataset.scanId===d.id;
  const opened=new Set(same?[...root.querySelectorAll('details[open]')].map(key):[]);
  renderDetail(d);root.dataset.scanId=d.id;
  if(same)for(const el of root.querySelectorAll('details'))el.open=opened.has(key(el));
}
function disclosureEvidence(r){return (r?.operator_disclosures||[]).slice(0,2).map(d=>'<article class="operator-disclosure"><blockquote>'+esc(d.quote)+'</blockquote><button class="subtle" data-capture="'+esc(d.capture_id)+'">Inspect operator disclosure ↗</button></article>').join('')+patternEvidence(r);}
function patternEvidence(r){const p=r?.pattern_explanation;if(!p)return '';return '<details class="pattern-explanation"><summary>Why this pattern points to lead-gen</summary><ul>'+p.reasons.map(x=>'<li>'+esc(x.text)+' <button class="subtle" data-capture="'+esc(x.capture_id)+'">Inspect source ↗</button></li>').join('')+'</ul><p class="muted">'+esc(p.limit)+'</p></details>';}
function businessResearch(d,b,r){
  const ctx=r?.site_context,source=id=>'<button class="subtle" data-capture="'+esc(id)+'">Inspect source ↗</button>';
  const refs=d.cross_references?.[b.id]||[];
  let out=refs.length?'<section class="cross-references"><h4>How these businesses connect</h4>'+refs.map(x=>'<p><strong>'+esc(x.text)+'</strong><br>'+esc(x.meaning)+' '+x.capture_ids.map(source).join(' ')+'</p>').join('')+'</section>':'';
  out+='<div class="research-tools"><button class="secondary" data-deep="'+esc(b.id)+'" data-parent="'+esc(d.id)+'" '+(!b.website||!terminal.has(d.status)?'disabled':'')+'>Deep scan this business</button><small> Up to 12 website pages; preserves the discovered profile and phone.</small></div>';
  out+='<details class="site-research"><summary>People, social profiles & link network</summary>';
  if(!ctx)out+='<p>Run a deep scan or update investigation to collect these checks.</p>';
  else{
    if(ctx.naming_context)out+='<p>'+esc(ctx.naming_context)+'</p>';
    for(const s of ctx.signals||[])out+='<p><strong>'+esc(s.kind.replaceAll('_',' '))+'</strong></p><blockquote>'+esc(s.quote)+'</blockquote><p>'+esc(s.scope||'Website statement; relationship not independently verified.')+'</p>'+source(s.capture_id);
    out+='<h4>Published staff</h4>'+(ctx.staff?.length?ctx.staff.map(p=>'<p>'+esc(p.name)+' — '+esc(p.role)+'<br>'+esc(p.scope)+' '+source(p.capture_id)+'</p>').join(''):'<p>No named staff extracted from the checked pages. This is not a negative signal.</p>');
    out+='<h4>Linked social profiles</h4>'+(ctx.social_profiles?.length?ctx.social_profiles.map(p=>'<p><a href="'+esc(p.url)+'" target="_blank" rel="noreferrer">'+esc(p.url)+'</a> '+source(p.capture_id)+'</p>').join(''):'<p>No social profile links extracted from checked pages.</p>');
    out+='<h4>Observed link paths</h4><p>A closed path shows links, not an exchange agreement or common ownership.</p>'+(ctx.link_paths?.length?ctx.link_paths.map(path=>'<p>'+esc([path[0].from,...path.map(e=>e.domain)].join(' → '))+'<br>'+path.map(e=>source(e.capture_id)).join(' ')+'</p>').join(''):'<p>No closed link path established in the bounded sample.</p>');
    out+='<details><summary>Outbound links ('+(ctx.outbound_links||[]).length+')</summary>'+(ctx.outbound_links||[]).map(e=>'<p>'+esc(e.anchor||'Unlabelled link')+' → <a href="'+esc(e.url)+'" target="_blank" rel="noreferrer">'+esc(e.domain)+'</a> '+source(e.capture_id)+'</p>').join('')+'</details>';
  }
  out+='</details><details class="carrier-research"><summary>Phone carrier lookup</summary><p>VoIP is also used by real businesses. Carrier identity does not establish CallRail, call forwarding, or who performs the work.</p>';
  for(const p of ctx?.phone_checks||[])out+='<p><strong>'+esc(p.phone)+' · '+esc(p.carrier)+' · '+esc(p.line_type.replaceAll('_',' '))+'</strong><br>'+esc(p.verification)+' · '+esc(p.observed_at)+'</p>'+source(p.capture_id);
  const numbers=[...new Set([b.phone,...d.identifiers.filter(x=>x.business_id===b.id&&x.kind==='phone'&&x.role==='displayed_contact').map(x=>x.value)].filter(Boolean))];
  if(numbers.length)out+='<form data-phone-auto="'+esc(b.id)+'" data-parent="'+esc(d.id)+'"><label>Business phone<select name="phone">'+numbers.map(n=>'<option>'+esc(n)+'</option>').join('')+'</select></label><button class="secondary" '+(!terminal.has(d.status)?'disabled':'')+'>Check phone — free</button></form><p>Reports the original carrier and line type. A ported number’s current carrier/VoIP status may differ.</p><a href="#phone-lookup">Phone lookup settings</a>';
  else out+='<p>No business phone captured yet.</p>';
  return out+'</details>';
}
function setMode(value){
mode=value;
$('#singleBox').hidden=value!=='single';
$('#businessName').required=value==='single';$('#businessUrl').required=value==='single';
$('#category').closest('label').hidden=value==='single';$('#city').closest('label').hidden=value==='single';
document.querySelectorAll('.mode').forEach(b=>b.classList.toggle('active',b.dataset.mode===value));
$('#urlBox').hidden=value!=='websites';
$('#category').required=value==='maps';$('#city').required=value==='maps';$('#maxBusinesses').disabled=value!=='maps';
$('#modeNote').textContent=value==='demo'?'Creates fictional source captures. No website or model is contacted.':value==='websites'?'Manual investigation of websites you already know. Checks relevant pages for disclosures and claims.':'Finds Maps listings and their published website links, then checks relevant pages for disclosures and claims. Discovery is experimental; collection gaps are shown in the results.';
$('#startScan').innerHTML=value==='demo'?'Create fictional demo <span>→</span>':value==='maps'?'Discover businesses <span>→</span>':'Investigate websites <span>→</span>';
if(value==='single'){$('#startScan').innerHTML='Scan business <span>→</span>';$('#modeNote').textContent='Assess one business using its website and linked source pages. The supplied name is a research label, not a verified identity.';}
}
document.querySelectorAll('.mode').forEach(b=>b.addEventListener('click',()=>setMode(b.dataset.mode)));
document.querySelectorAll('.nav').forEach(b=>b.addEventListener('click',()=>{currentPanel=b.dataset.panel;document.querySelectorAll('.nav').forEach(x=>x.classList.toggle('active',x===b));$('#investigatePanel').hidden=currentPanel!=='investigate';$('#settingsPanel').hidden=currentPanel!=='settings';$('#pageTitle').innerHTML=currentPanel==='settings'?'Your hardware.<br>Your research workspace.':'Investigate the business<br>behind the listing.';if(currentPanel==='settings')loadStatus();}));
$('#scanForm').addEventListener('submit',async e=>{e.preventDefault();const btn=$('#startScan');btn.disabled=true;try{const data=await api('/api/scans',{mode,category:$('#category').value,city:$('#city').value,state:$('#state').value,urls:$('#urls').value.split(/\r?\n/).map(s=>s.trim()).filter(Boolean),max_businesses:Number($('#maxBusinesses').value),max_pages:Number($('#maxPages').value),use_model:$('#useModel').checked,headless:false});selected=data.id;currentDetail=null;toast('Investigation added to the local queue.');await refresh(true);$('#detail').scrollIntoView({behavior:'smooth',block:'start'});}catch(e){toast(e.message,true);}finally{btn.disabled=false;}});
async function loadStatus(){try{const st=await api('/api/status');$('#modelHint').textContent=st.model.model?'Selected local model: '+st.model.model:'No local model selected. Rules still work; configure the existing 7B under Local model & data.';$('#dataPath').textContent='Local data: '+st.data_dir;$('#registryStatus').textContent=st.registry.records?`${st.registry.records.toLocaleString()} rows · source date ${st.registry.source_date} · ${st.registry.filename}`:'No snapshot imported. License claims can still be collected, but no registry comparison will run.';if(st.model.endpoint){$('#endpoint').value=st.model.endpoint;$('#runtime').value=st.model.kind;if(st.model.model){$('#modelSelect').innerHTML=`<option value="${esc(st.model.model)}">${esc(st.model.model)}</option>`;}}}catch(e){toast(e.message,true);}}
async function refresh(force=false){if(pollBusy)return;pollBusy=true;try{const scans=await api('/api/scans');$('#scanList').innerHTML=scans.length?scans.map(s=>`<button class="scan-row ${selected===s.id?'selected':''}" data-scan="${s.id}"><div><div class="scan-name">${esc(s.category)} <span class="muted">/ ${esc(s.city)}</span></div><div class="scan-sub">${esc(s.created_at)}${s.mode==='demo'?' · FICTIONAL DEMO':''}</div></div><span class="scan-count muted">${s.business_count} candidates · ${s.finding_count} observations</span>${badge(s.status)}</button>`).join(''):'<div class="empty">No investigations yet. Start with a market, a website, or the fictional demonstration.</div>';if(selected){const active=scans.find(x=>x.id===selected);const editing=$('#detail').contains(document.activeElement)&&['INPUT','SELECT','TEXTAREA'].includes(document.activeElement.tagName);if(force||(!editing&&(!currentDetail||!terminal.has(currentDetail.status)||active?.status!==currentDetail.status))){currentDetail=await api('/api/scans/'+selected);renderKeepingOpen(currentDetail);}}}catch(e){if(force)toast(e.message,true);}finally{pollBusy=false;}}
$('#refresh').addEventListener('click',()=>refresh(true));
$('#scanList').addEventListener('click',e=>{const row=e.target.closest('[data-scan]');if(row){selected=row.dataset.scan;currentDetail=null;refresh(true);}});
function renderDetail(d){$('#detail').hidden=false;const caps=Object.fromEntries(d.captures.map(c=>[c.id,c]));let out=`<div class="detail-heading"><div><h2>${esc(d.category)} · ${esc(d.city)}</h2>${badge(d.status)} ${d.mode==='demo'?'<span class="badge demo">FICTIONAL DEMO</span>':''}</div><div class="detail-actions"><a href="/api/scans/${d.id}/report" target="_blank" rel="noopener">Report / print</a><a href="/api/scans/${d.id}/export.json">Export JSON</a>${!terminal.has(d.status)?'<button class="subtle" data-cancel="'+d.id+'">Cancel investigation</button>':''}</div></div><div class="stage">${esc(d.stage)}</div><div class="metrics"><div class="metric"><strong>${d.businesses.length}</strong>Discovered candidates</div><div class="metric"><strong>${d.captures.length}</strong>Source captures</div><div class="metric"><strong>${d.findings.length}</strong>Observations / suggestions</div><div class="metric"><strong>${d.connections.length}</strong>Shared identifiers</div></div>`;
if(d.mode==='demo')out+='<div class="warning-box"><strong>Fictional demonstration.</strong> No findings in this case concern real businesses.</div>';
for(const w of d.warnings)out+=`<div class="warning-box">${esc(w)}</div>`;
for(const b of d.businesses){const findings=d.findings.filter(f=>f.business_id===b.id);const bc=d.captures.filter(c=>c.business_id===b.id);out+=`<section class="business"><div class="business-head"><div><h3>${esc(b.name)}</h3><div class="business-links">${b.website?'<a href="'+esc(b.website)+'" target="_blank" rel="noreferrer">'+esc(b.website)+'</a>':'No website captured'}${b.profile_url?' · <a href="'+esc(b.profile_url)+'" target="_blank" rel="noreferrer">Public profile ↗</a>':''}<br>${b.address?esc(b.address)+' · ':''}Address display: ${esc(b.address_state)} · ${bc.length} captures</div></div>${badge(b.status)}</div>`;
const bi=d.identifiers.filter(x=>x.business_id===b.id); const bvSeen=new Set(); out+='<div class="business-links">'+bi.filter(x=>{const k=x.kind+':'+x.value+':'+x.role;if(bvSeen.has(k))return false;bvSeen.add(k);return true;}).map(x=>`<button class="subtle" data-capture="${x.capture_id}">${esc(x.kind==='license'?'Claimed license':x.kind)}: ${esc(x.value)} · ${esc(x.role.replaceAll('_',' '))} ↗</button>`).join(' &nbsp; ')+'</div>';
if(!findings.length)out+='<p class="muted">No matching statement found in the pages checked. This does not verify legitimacy. Unchecked location and licensing questions remain unresolved.</p>';
for(const f of findings){const cap=caps[f.capture_id];out+=`<article class="finding"><span class="badge ${f.strength==='model_suggestion'?'warning':''}">${esc(f.dimension.replaceAll('_',' '))} · ${esc(f.strength.replaceAll('_',' '))}</span><h3>${esc(f.title)}</h3><blockquote>${esc(f.quote)}</blockquote><p class="explanation">${esc(f.explanation)}</p><div class="finding-meta"><span class="muted">${cap?esc(cap.title)+' · '+esc(cap.observed_at):'Source unavailable'}</span>${cap?'<button class="subtle" data-capture="'+cap.id+'">Inspect exact source ↗</button>':''}</div><div class="review"><select data-state="${f.id}">${['unreviewed','supported','explained','unresolved'].map(x=>`<option ${f.state===x?'selected':''} value="${x}">${x}</option>`).join('')}</select><input data-note="${f.id}" value="${esc(f.reviewer_note)}" placeholder="Reviewer note, legitimate explanation, or next verification step"><button class="secondary" data-review="${f.id}">Save review</button></div></article>`;}
out+='<details><summary class="muted">All source captures</summary>'+bc.map(c=>`<p><button class="subtle" data-capture="${c.id}">${esc(c.title)}</button><br><small class="muted">${esc(c.final_url)}</small></p>`).join('')+'</details></section>';}
if(d.connections.length){out+='<section class="business"><h3>Documented connections</h3>';for(const c of d.connections){out+=`<div class="connection"><strong>${esc(c.kind)} · ${esc(c.value)}</strong><small>${c.business_count} candidates. ${esc(c.interpretation)}</small>${c.sources.map(x=>`<button class="subtle" data-capture="${x.capture_id}">${esc(x.name)} ↗</button>`).join(' &nbsp; ')}</div>`;}out+='</section>';}
out+='<section class="business"><h3>Activity &amp; collection gaps</h3><div class="log">'+d.events.map(x=>`<div class="${x.level==='warning'?'warning':''}">${esc(x.created_at)} · ${esc(x.message)}</div>`).join('')+'</div></section>';$('#detail').innerHTML=out;}
$('#detail').addEventListener('click',async e=>{const cap=e.target.closest('[data-capture]'),rev=e.target.closest('[data-review]'),cancel=e.target.closest('[data-cancel]');try{if(cap){const d=await api('/api/captures/'+cap.dataset.capture);$('#captureBody').innerHTML=`<p><a href="${esc(d.final_url)}" target="_blank" rel="noreferrer">${esc(d.final_url)}</a></p><p class="mono">Observed: ${esc(d.observed_at)}<br>SHA-256: ${esc(d.sha256)}<br>Source type: ${esc(d.source_type)}</p><a href="/api/captures/${d.id}/download">Download original bytes as non-executing text</a><pre>${esc(d.text)}</pre>`;$('#captureDialog').showModal();}if(rev){const id=rev.dataset.review;await api('/api/findings/'+id+'/review',{state:document.querySelector(`[data-state="${id}"]`).value,note:document.querySelector(`[data-note="${id}"]`).value});toast('Review saved; history retained.');await refresh(true);}if(cancel){await api('/api/scans/'+cancel.dataset.cancel+'/cancel',{});toast('Cancellation requested.');await refresh(true);}}catch(err){toast(err.message,true);}});
$('#closeCapture').addEventListener('click',()=>$('#captureDialog').close());
$('#runtime').addEventListener('change',()=>{$('#endpoint').value=$('#runtime').value==='ollama'?'http://127.0.0.1:11434':'http://127.0.0.1:1234';});
$('#probeModel').addEventListener('click',async()=>{const btn=$('#probeModel');btn.disabled=true;$('#probeStatus').textContent='Checking the existing local runtime…';try{const d=await api('/api/model/probe',{kind:$('#runtime').value,endpoint:$('#endpoint').value});if(!d.available)throw new Error(d.error||'Local server did not respond.');$('#modelSelect').innerHTML='<option value="">No model selected</option>'+d.models.map(m=>`<option value="${esc(m.id)}">${esc(m.id)}${m.size?' · '+esc(m.size):''}</option>`).join('');if(d.models.length===1)$('#modelSelect').value=d.models[0].id;$('#probeStatus').textContent=`${d.models.length} existing model(s) found. Select yours, then save. No model was loaded or downloaded.`;}catch(e){$('#probeStatus').textContent=e.message;toast(e.message,true);}finally{btn.disabled=false;}});
$('#saveModel').addEventListener('click',async()=>{try{await api('/api/model/settings',{kind:$('#runtime').value,endpoint:$('#endpoint').value,model:$('#modelSelect').value});toast('Local connection saved.');loadStatus();}catch(e){toast(e.message,true);}});
$('#importRegistry').addEventListener('click',async()=>{const file=$('#registryFile').files[0],date=$('#registryDate').value;if(!file||!date){toast('Select a CSV and its actual source/download date.',true);return;}const btn=$('#importRegistry');btn.disabled=true;try{const r=await fetch('/api/registry/import',{method:'POST',headers:{'X-BV-Local':'1','Content-Type':'text/csv','X-Filename':file.name.replace(/[^a-zA-Z0-9_.-]/g,'_'),'X-Source-Date':date},body:file});const d=await r.json();if(!r.ok)throw new Error(d.detail);toast(`Imported ${d.records.toLocaleString()} reference records.`);await loadStatus();}catch(e){toast(e.message,true);}finally{btn.disabled=false;}});
$('#stopApp').addEventListener('click',async()=>{if(!confirm('Stop this application? Current investigations will be cancelled. Your model and other applications will not be stopped.'))return;try{await api('/api/shutdown',{});toast('Application shutdown requested. Use Start PinSpector.cmd to reopen it.');clearInterval(window.pollTimer);}catch(e){toast(e.message,true);}});
const renderEvidenceDetail=renderDetail;
function renderProfileNetwork(discovery){
const n=discovery?.network;if(!n||n.profile_count<2)return '';
const profiles=discovery.profiles.filter(p=>p.match_status==='identifier_match'&&!['unresolved','share_link'].includes(p.identity_source));
let out='<section class="profile-network"><h4>'+esc(n.summary)+'</h4><p>'+esc(n.meaning)+'</p><div style="overflow-x:auto"><table><thead><tr><th>Connected GBP</th><th>Phone</th><th>Published address</th><th>Connection</th></tr></thead><tbody>';
for(const p of profiles){const edges=n.edges.filter(e=>e.to===p.key||e.from===p.key);const links=[...new Set(edges.map(e=>e.kind+': '+e.value))];out+='<tr><td><a target="_blank" rel="noreferrer" href="'+esc(p.profile_url)+'">'+esc(p.name)+'</a></td><td>'+esc(p.phone||'Not captured')+'</td><td>'+esc(p.address||'No public address captured')+'</td><td>'+esc(links.join('; '))+' <button class="subtle" data-capture="'+esc(p.capture_id)+'">Source ↗</button></td></tr>';}
return out+'</tbody></table></div></section>';
}
function renderProfileDiscovery(d){
if(d.mode!=='single')return '';
let out='<section class="business"><div class="card-top"><h2>Google Business Profiles</h2>'+(terminal.has(d.status)?'<button class="secondary" data-discover="'+esc(d.id)+'">Search related profiles</button>':'')+'</div>';
const latest=d.profile_discoveries?.[0]?.result;
if(!latest)return out+'<p>Profile discovery has not completed for this business. No conclusion about additional listings is available yet.</p></section>';
out+='<p><strong>'+esc(latest.summary)+'</strong></p><p class="muted">Searched '+esc(latest.finished_at)+' · '+esc(latest.limits)+'</p>';
out+=renderProfileNetwork(latest);
for(const p of latest.profiles){out+='<article class="finding"><h3><a href="'+esc(p.profile_url)+'" target="_blank" rel="noreferrer">'+esc(p.name)+' ↗</a></h3><span class="badge">'+esc(p.match_status.replaceAll('_',' '))+'</span><p>'+(p.match_status==='website_reference'?'Explicit Google listing reference captured on the business website; live profile details are not yet verified.':p.matched_by.length?'Matched by '+esc(p.matched_by.join(' + '))+'. Shared identifiers indicate a related profile; they do not prove common ownership or duplication.':'Name/search candidate only; relationship is not confirmed.')+'</p><p>Website: '+esc(p.website||'Not captured')+'<br>Phone: '+esc(p.phone||'Not captured')+'<br>'+esc(p.address?'Published address: '+p.address:'No street address captured. Public address display is unconfirmed; a storefront is not assumed.')+'</p><button class="subtle" data-capture="'+esc(p.capture_id)+'">Inspect captured profile evidence ↗</button></article>';}
out+='<h3>Search coverage</h3>';
for(const q of latest.searches){out+='<div class="connection"><strong>'+esc(q.kind)+' search · '+esc(q.query||'No query available')+'</strong> '+badge(q.status)+'<p>'+esc(q.error||'')+'</p><small>'+q.profiles.length+' profile observations collected in this query.</small>'+(q.capture_ids||[]).map(id=>'<button class="subtle" data-capture="'+esc(id)+'">Inspect source ↗</button>').join(' ')+'</div>';}
return out+'</section>';
}
renderDetail=function(d){
if(d.mode!=='single'&&d.mode!=='demo'){renderMarket(d);return;}
const assessedIds=new Set((d.assessments||[]).filter(a=>a.result.status==='assessed').map(a=>a.business_id));
const displayedWarnings=d.warnings.filter(w=>!(w.startsWith('No local model selected.')&&d.businesses.every(b=>assessedIds.has(b.id))));
renderEvidenceDetail({...d,warnings:displayedWarnings});
for(const paragraph of $('#detail').querySelectorAll('p.muted'))if(paragraph.textContent.startsWith('No matching statement found'))paragraph.textContent='Phrase checks found no explicit matching disclosure in the collected website text. See the assessment and profile discovery results for the investigation conclusions.';
const latest=new Map();for(const a of d.assessments||[])if(!latest.has(a.business_id))latest.set(a.business_id,a);
let summary=renderProfileDiscovery(d)+'<section class="business assessment-summary"><div class="card-top"><h2>Business assessment</h2>'+(terminal.has(d.status)?'<button class="secondary" data-assess="'+esc(d.id)+'">Assess saved evidence</button>':'')+'</div>';
for(const b of d.businesses){const entry=latest.get(b.id),r=entry?.result;
summary+='<h3>'+esc(b.name)+'</h3>';
if(!r){summary+='<p>No constitutional model assessment has run on these sources. Connect the existing model in Settings, then choose Assess saved evidence.</p>';continue;}
summary+='<p><strong>'+esc(r.conclusion)+'</strong></p><p class="muted">'+esc(r.status)+' · '+esc(r.model||'No model connected')+' · Constitution '+esc(r.constitution_version)+' · '+esc(entry.created_at)+'</p>';
for(const claim of r.claims){summary+='<article class="finding"><span class="badge">'+esc(claim.dimension.replaceAll('_',' '))+' · Model interpretation</span><p>'+esc(claim.statement)+'</p><blockquote>'+esc(claim.quote)+'</blockquote><button class="subtle" data-capture="'+esc(claim.capture_id)+'">Inspect source ↗</button><p class="muted">'+esc(claim.limitation)+'</p></article>';}
summary+='<details><summary>Scope and validation limits</summary><ul>'+r.limits.map(x=>'<li>'+esc(x)+'</li>').join('')+'</ul><p>'+r.sources.length+' source excerpts considered. '+esc(r.error||'')+'</p><p>Policy hash: '+esc(r.constitution_sha256)+'</p></details>';
}
summary+='</section>';$('#detail').insertAdjacentHTML('afterbegin',summary);
if(d.mode==='single'){
  $('#detail').querySelectorAll('[data-assess],[data-discover]').forEach(el=>el.remove());
  let joint='<section class="business joint-summary"><div class="card-top"><h2>Combined investigation</h2>'+(terminal.has(d.status)?'<button class="secondary" data-investigate="'+esc(d.id)+'">Update investigation</button>':'<span class="badge active">Collecting and assessing</span>')+'</div>';
  for(const b of d.businesses){
    const a=latest.get(b.id),r=a?.result?.combined,x=(d.corroborations||[]).find(x=>x.business_id===b.id)?.result;
    joint+='<h3>'+esc(r?.label||'Combined conclusion pending')+'</h3><p>'+esc(r?.answer||'Run Update investigation to collect website pages, related profiles, external work credits, customer accounts, and domain/history records together.')+'</p>';
    if(r){joint+='<p class="muted">Assessed '+esc(a.created_at)+(terminal.has(d.status)?'':' · Previous result; refresh is in progress.')+'</p><p><strong>'+esc(r.profile_summary)+'</strong></p>';
      joint+=disclosureEvidence(r);
      if(r.location_summary)joint+='<p class="warning-box">'+esc(r.location_summary)+'</p>';
      joint+='<details><summary>Why this verdict</summary>'+r.supporting.map(text=>'<p>'+esc(text)+'</p>').join('')+r.concerns.map(text=>'<p>'+esc(text)+'</p>').join('')+(r.supporting_capture_ids||[]).map(id=>'<button class="subtle" data-capture="'+esc(id)+'">Inspect supporting source ↗</button>').join(' ')+'</details>';
      if(r.relationship_signals?.length)joint+='<details><summary>Identity and location evidence</summary>'+r.relationship_signals.map(s=>'<p><strong>'+esc(s.requires_review?'Review lead':'Location context')+'</strong>: '+esc(s.description)+'</p><p>'+esc(s.alternative_explanations)+'</p>'+s.capture_ids.map(id=>'<button class="subtle" data-capture="'+esc(id)+'">Inspect source ↗</button>').join(' ')).join('')+'</details>';
      joint+='<details><summary>Collection details</summary>'+r.gaps.map(g=>'<p><strong>'+esc(g.check)+':</strong> '+esc(g.detail)+'</p>').join('')+'<p class="muted">'+esc(r.scope)+'</p></details>';
    }
    if(x){joint+='<details><summary>External evidence and check coverage</summary>';
      for(const e of x.evidence)joint+='<article class="finding"><span class="badge">'+esc(e.kind.replaceAll('_',' '))+'</span><blockquote>'+esc(e.quote)+'</blockquote><p>'+esc(e.scope)+'</p><small>'+esc(e.url)+'</small><br><button class="subtle" data-capture="'+esc(e.capture_id)+'">Inspect captured source ↗</button></article>';
      for(const c of x.checks)joint+='<p><strong>'+esc(c.check)+' · '+esc(c.status.replaceAll('_',' '))+'</strong><br>'+esc(c.detail)+'</p>'+(c.failures||[]).map(f=>'<p class="muted">'+esc(f.url)+': '+esc(f.error)+'</p>').join('');
      for(const q of x.searches)joint+='<p>Search: '+esc(q.query)+' · '+esc(q.status)+' '+esc(q.error||'')+(q.capture_id?' <button class="subtle" data-capture="'+esc(q.capture_id)+'">Source ↗</button>':'')+'</p>';
      joint+='</details>';
    }
    joint+=businessResearch(d,b,r);
  }
  $('#detail').insertAdjacentHTML('afterbegin',joint+'</section>');
  const extra=document.createElement('details');extra.innerHTML='<summary>Full evidence and search history</summary>';
  Array.from($('#detail').children).filter(el=>el.matches('section.business')&&!el.classList.contains('joint-summary')).forEach(el=>extra.appendChild(el));
  $('#detail').appendChild(extra);
  $('#detail').querySelectorAll('.badge').forEach(el=>{if(el.textContent==='ready with gaps'){el.textContent='Collection complete';el.classList.remove('warning');}});
}
};
function renderMarket(d){
  $('#detail').hidden=false;
  const latest=(items,id)=>(items||[]).find(x=>x.business_id===id)?.result;
  const investigated=d.businesses.filter(b=>latest(d.corroborations,b.id)&&latest(d.profile_discoveries,b.id)).length;
  let out='<div class="detail-heading"><div><h2>'+esc(d.category)+' · '+esc(d.city)+'</h2><p>'+d.businesses.length+' businesses · '+investigated+' with expanded collection</p></div><div class="detail-actions">'+(terminal.has(d.status)?'<button class="secondary" data-investigate="'+esc(d.id)+'">Update investigation</button>':'<button class="secondary" data-cancel="'+esc(d.id)+'">Cancel investigation</button>')+'<a href="/api/scans/'+esc(d.id)+'/report" target="_blank">Report / print</a><a href="/api/scans/'+esc(d.id)+'/export.json">Export JSON</a></div></div>';
  out+='<div class="stage">'+esc(d.stage)+'</div>';
  if(terminal.has(d.status)&&investigated<d.businesses.length)out+='<p>Expanded collection is missing for '+(d.businesses.length-investigated)+' businesses. Update investigation runs profile, review, and external-evidence checks.</p>';
  const priority=b=>{const r=latest(d.assessments,b.id)?.combined;return r?.concerns?.length?0:r?.label?.startsWith('Unlikely')?1:2;};
  for(const b of [...d.businesses].sort((a,b)=>priority(a)-priority(b))){
    const a=latest(d.assessments,b.id),r=a?.combined,p=latest(d.profile_discoveries,b.id),x=latest(d.corroborations,b.id);
    const caps=d.captures.filter(c=>c.business_id===b.id),fs=d.findings.filter(f=>f.business_id===b.id);
    out+='<details class="business market-result" data-business="'+esc(b.id)+'"><summary><strong>'+esc(b.name)+'</strong><span>'+esc(r?.label||'Assessment not run')+'</span></summary><p>'+esc(r?.answer||'No business-role conclusion is available yet.')+'</p>';
    out+=disclosureEvidence(r);
    if(r?.location_summary)out+='<p class="warning-box">'+esc(r.location_summary)+'</p>';
    out+='<p>'+esc(p?.summary||'Related-profile checks have not run.')+'</p><p class="muted">'+caps.length+' captures · '+(x?x.evidence.length+' external/customer evidence items':'External checks have not run')+'</p>';
    out+=renderProfileNetwork(p);
    if(p?.profiles?.length){
      out+='<details><summary>Which profiles matched—and which did not</summary>';
      for(const profile of p.profiles){
        const stable=!['unresolved','share_link'].includes(profile.identity_source),matched=profile.match_status==='identifier_match';
        out+='<article class="finding"><h3>'+esc(profile.name)+'</h3><p><strong>'+esc(matched?(stable?'Identifier match; location not verified':'Matching observation; listing ID unresolved'):'Separate candidate — not matched to this business')+'</strong></p><p>'+esc(profile.address||'No address captured')+'<br>'+esc(profile.phone||'No phone captured')+'<br>'+esc(profile.website||'No website captured')+'</p><p>'+esc(matched?'Matched by '+profile.matched_by.join(' + '):(profile.name_match_reason||'Direct website reference')+'. This does not establish common ownership or a legitimate location.')+'</p><button class="subtle" data-capture="'+esc(profile.capture_id)+'">Inspect profile source ↗</button></article>';
      }
      out+='</details>';
    }
    if(b.website)out+='<p><a href="'+esc(b.website)+'" target="_blank" rel="noreferrer">Website ↗</a></p>';
    out+=businessResearch(d,b,r);
    out+='<details><summary>Evidence behind the verdict</summary>';
    for(const c of a?.claims||[])out+='<p>'+esc(c.statement)+'</p><blockquote>'+esc(c.quote)+'</blockquote><button class="subtle" data-capture="'+esc(c.capture_id)+'">Inspect source ↗</button>';
    for(const e of x?.evidence||[])out+='<p><strong>'+esc(e.kind.replaceAll('_',' '))+'</strong></p><blockquote>'+esc(e.quote)+'</blockquote><button class="subtle" data-capture="'+esc(e.capture_id)+'">Inspect source ↗</button>';
    for(const f of fs)out+='<p><strong>'+esc(f.title)+'</strong></p><blockquote>'+esc(f.quote)+'</blockquote><button class="subtle" data-capture="'+esc(f.capture_id)+'">Inspect source ↗</button>';
    out+='</details><details><summary>Collection details and sources</summary>';
    if(p?.excluded_profiles?.length)out+='<p>'+p.excluded_profiles.length+' search hits without connection evidence excluded from related profiles. Original captures are retained below.</p>';
    for(const q of p?.searches||[])out+='<p>'+esc(q.kind)+': '+esc(q.query||'')+' � '+esc(q.status)+' '+esc(q.error||'')+'</p>';
    for(const c of x?.checks||[])out+='<p>'+esc(c.check)+': '+esc(c.status)+' — '+esc(c.detail)+'</p>';
    for(const c of caps)out+='<p><button class="subtle" data-capture="'+esc(c.id)+'">'+esc(c.title||c.final_url)+' ↗</button></p>';
    out+='</details></details>';
  }
  out+='<details class="business"><summary>Activity and collection errors</summary><div class="log">'+d.events.map(e=>'<p>'+esc(e.message)+'</p>').join('')+'</div></details>';
  $('#detail').innerHTML=out;
}
$('#detail').addEventListener('click',async e=>{const button=e.target.closest('[data-investigate]');if(!button)return;button.disabled=true;try{await api('/api/scans/'+button.dataset.investigate+'/investigate',{});currentDetail=null;await refresh(true);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
$('#detail').addEventListener('click',async e=>{const b=e.target.closest('[data-deep]');if(!b)return;b.disabled=true;try{const result=await api('/api/scans',{parent_scan_id:b.dataset.parent,parent_business_id:b.dataset.deep,mode:'single',max_pages:12,use_model:true,headless:true});selected=result.id;currentDetail=null;await refresh(true);toast('Deep scan queued. The original discovery result is retained.');}catch(error){toast(error.message,true);}finally{b.disabled=false;}});
document.addEventListener('submit',async e=>{const f=e.target.closest('[data-phone-auto],[data-carrier-connect]');if(!f)return;e.preventDefault();const button=f.querySelector('button');button.disabled=true;try{const connect=f.hasAttribute('data-carrier-connect');await api(connect?'/api/carrier/connect':'/api/scans/'+f.dataset.parent+'/businesses/'+f.dataset.phoneAuto+'/carrier/lookup',Object.fromEntries(new FormData(f)));if(connect){f.reset();const message=f.querySelector('[data-carrier-message]');if(message)message.textContent='Connected. You can now use Check phone in any business result.';toast('Free lookup connected. Click Check phone.');}else{if(selected===f.dataset.parent){const section=f.closest('.carrier-research');const top=section.getBoundingClientRect().top;const businessId=f.dataset.phoneAuto;await refresh(true);const updated=[...document.querySelectorAll('[data-phone-auto]')].find(x=>x.dataset.phoneAuto===businessId);if(updated){const current=updated.closest('.carrier-research');current.open=true;window.scrollBy(0,current.getBoundingClientRect().top-top);}}toast('Carrier result saved.');}}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
$('#detail').addEventListener('click',async e=>{const button=e.target.closest('[data-assess]');if(!button)return;button.disabled=true;try{await api('/api/scans/'+button.dataset.assess+'/assess',{});currentDetail=null;await refresh(true);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
$('#detail').addEventListener('click',async e=>{const button=e.target.closest('[data-discover]');if(!button)return;button.disabled=true;try{await api('/api/scans/'+button.dataset.discover+'/discover-profiles',{});currentDetail=null;await refresh(true);}catch(error){toast(error.message,true);}finally{button.disabled=false;}});
setMode('maps');loadStatus();refresh();window.pollTimer=setInterval(()=>{if(currentPanel==='investigate'&&!document.hidden)refresh();},2200);
api('/api/constitution').then(c=>{$('#constitutionText').textContent=c.text;}).catch(()=>{$('#constitutionText').textContent='Constitution could not be loaded.';});

function showPhoneSetup(){if(location.hash==="#phone-lookup"){document.querySelector('[data-panel="settings"]').click();document.getElementById("phone-lookup").scrollIntoView();}}
window.addEventListener("hashchange",showPhoneSetup);showPhoneSetup();
