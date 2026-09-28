"""Loopback-only first build. Not the public/multi-tenant paid deployment."""
from __future__ import annotations
import asyncio
import csv
import hashlib
import html
import io
import ipaddress
import json
import logging
import os
import re
import socket
import sys
import tempfile
import threading
import time
import uuid
from contextlib import asynccontextmanager
from pathlib import Path
from typing import Literal
from urllib.parse import urlsplit

import uvicorn
from fastapi import FastAPI,HTTPException,Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import HTMLResponse,JSONResponse,PlainTextResponse,Response
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel,Field
from . import APP_ID,__version__
from . import storage as s,models,registry,worker,reasoning
from .net import normalize_url,UnsafeURL

PORT=int(os.environ.get('BV_PORT','8768'))
SERVER=None

@asynccontextmanager
async def lifespan(app):
    s.init()
    logging.basicConfig(level=logging.INFO,format='%(asctime)s %(levelname)s %(message)s',
       handlers=[logging.FileHandler(s.DATA/'logs'/'application.log',encoding='utf-8'),logging.StreamHandler()])
    try:s.read_carrier_key()
    except ValueError:logging.warning('Phone connection could not be unlocked; reconnect in Settings.')
    worker.STOP.clear()
    yield
    worker.STOP.set()

app=FastAPI(title='PinSpector — HP Local',version=__version__,lifespan=lifespan,docs_url=None,redoc_url=None)

@app.exception_handler(RequestValidationError)
async def safe_validation_error(request,exc):
    # Pydantic includes submitted input by default, including rejected API keys.
    return JSONResponse({'detail':[{k:e[k] for k in ('loc','msg','type')} for e in exc.errors()]},status_code=422)

@app.middleware('http')
async def local_only(request: Request,call_next):
    host=request.headers.get('host','').lower()
    if host not in {f'127.0.0.1:{PORT}',f'localhost:{PORT}'}:
        return JSONResponse({'detail':'This build only serves its local loopback hostname.'},status_code=403)
    origin=request.headers.get('origin')
    if origin and origin not in {f'http://127.0.0.1:{PORT}',f'http://localhost:{PORT}'}:
        return JSONResponse({'detail':'Cross-origin requests are not allowed.'},status_code=403)
    if request.headers.get('sec-fetch-site')=='cross-site':
        return JSONResponse({'detail':'Cross-site requests are not allowed.'},status_code=403)
    if request.method not in ('GET','HEAD','OPTIONS') and request.headers.get('x-bv-local')!='1':
        return JSONResponse({'detail':'Use the local dashboard for this action.'},status_code=403)
    response=await call_next(request)
    response.headers['X-Content-Type-Options']='nosniff'
    response.headers['Referrer-Policy']='no-referrer'
    response.headers['X-Frame-Options']='DENY'
    response.headers['Cache-Control']='no-store'
    response.headers['Content-Security-Policy']="default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'"
    return response

app.mount('/static',StaticFiles(directory=s.ROOT/'app'/'static'),name='static')

@app.get('/',response_class=HTMLResponse)
def index(): return (s.ROOT/'app'/'static'/'index.html').read_text(encoding='utf-8')

@app.get('/api/health')
def health():
    return {'app':APP_ID,'version':__version__,'pid':os.getpid(),'instance':s.fingerprint(str(s.ROOT))[:16],
      'mode':'local_only','data_dir':str(s.DATA)}

@app.get('/api/status')
def status():
    with s.db() as c:
        reg=dict(c.execute('SELECT * FROM registry_import WHERE id=1').fetchone() or {})
        active=c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('queued','running')").fetchone()[0]
    return {'version':__version__,'registry':reg,'model':s.read_settings().get('model',{}),
        'active_jobs':active,'data_dir':str(s.DATA),'rules_version':'2026-09-14.1',
        'limits':{'live_maps':'Experimental: live source selectors require HP verification.',
          'locations':'Address-role statements and branch review only. No automatic premises, staffing, mailbox, or pin validation.',
          'licensing':'Optional imported CSLB snapshot; not live official verification.',
          'public_access':'Disabled in this local single-user build.'}}

class ScanIn(BaseModel):
    mode: Literal['maps','websites','single','demo']='maps'
    business_name: str=Field(default='',max_length=150)
    category: str=Field(default='',max_length=120)
    city: str=Field(default='',max_length=120)
    state: str=Field(default='CA',max_length=60)
    urls: list[str]=Field(default_factory=list,max_length=20)
    max_businesses: int=Field(default=10,ge=1,le=20)
    max_pages: int=Field(default=8,ge=1,le=12)
    use_model: bool=True
    headless: bool=False
    parent_scan_id: str=Field(default='',max_length=40)
    parent_business_id: str=Field(default='',max_length=40)

@app.post('/api/scans')
def create_scan(body: ScanIn):
    seed={}
    if body.parent_scan_id or body.parent_business_id:
        parent=get_scan(body.parent_scan_id)
        seed=next((b for b in parent['businesses'] if b['id']==body.parent_business_id),None)
        if not seed:raise HTTPException(404,'Business not found in that investigation.')
        if parent['mode']=='demo':raise HTTPException(400,'Fictional businesses cannot run live deep scans.')
        if not seed['website']:raise HTTPException(400,'Add a website in a single-business scan first.')
        body=body.model_copy(update={'mode':'single','business_name':seed['name'],'urls':[seed['website']],
            'city':parent['city'],'state':parent['state'],'max_pages':12,'max_businesses':1})
    if body.mode=='maps' and (not body.category.strip() or not body.city.strip()):
        raise HTTPException(400,'Category and city are required for Maps discovery.')
    if body.mode=='websites' and not body.urls: raise HTTPException(400,'Add at least one public website URL.')
    try: urls=list(dict.fromkeys(normalize_url(x) for x in body.urls if x.strip()))
    except UnsafeURL as e: raise HTTPException(400,str(e))
    if body.mode=='single' and (not body.business_name.strip() or len(urls)!=1):
        raise HTTPException(400,'A single-business scan requires a business name and exactly one public website URL.')
    if body.mode=='single':
        host=urlsplit(urls[0]).hostname or ''
        try: public_literal=ipaddress.ip_address(host).is_global
        except ValueError: public_literal=True
        if not public_literal or host.rstrip('.').lower()=='localhost':
            raise HTTPException(400,'Enter a public business website, not a local network address.')
    with s.db() as c:
        n=c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('queued','running')").fetchone()[0]
        if n>=3: raise HTTPException(429,'The local queue already has three investigations. Finish or cancel one first.')
        reg=dict(c.execute('SELECT * FROM registry_import WHERE id=1').fetchone() or {})
        sid=s.uid(); cfg=body.model_dump(); cfg['urls']=urls
        if seed:cfg['seed_profile']={k:seed[k] for k in ('profile_url','phone','address','address_state')}
        cfg['model_config']=s.read_settings().get('model',{}); cfg['registry_at_start']=reg
        c.execute('INSERT INTO scans(id,category,city,state,mode,status,stage,created_at,updated_at,config) VALUES (?,?,?,?,?,?,?,?,?,?)',
          (sid,body.business_name.strip() if body.mode=='single' else body.category.strip() or 'Website investigation',body.city.strip() or 'Not specified',body.state.strip(),body.mode,'queued','Queued on the HP; one job runs at a time.',s.now(),s.now(),json.dumps(cfg)))
    worker.submit(sid)
    return {'id':sid}

class CarrierObservation(BaseModel):
    phone: str=Field(max_length=30)
    carrier: str=Field(min_length=1,max_length=150)
    line_type: Literal['unknown','wireless','landline','voip','fixed_voip','non_fixed_voip']='unknown'
    source_text: str=Field(min_length=10,max_length=5000)

class CarrierKey(BaseModel):
    key: str=Field(min_length=10,max_length=300)

@app.post('/api/carrier/connect')
def connect_carrier(body: CarrierKey):
    from . import carrier
    try:carrier.free_account(body.key.strip())
    except carrier.LookupError as e:raise HTTPException(400,str(e))
    try:s.put_setting('carrier_free_key',body.key.strip())
    except ValueError:raise HTTPException(400,'Windows could not protect the key. The connection was not saved.') from None
    return {'connected':True,'provider':'Veriphone','mode':'free_only'}

class CarrierPhone(BaseModel):
    phone: str=Field(max_length=30)

@app.post('/api/scans/{sid}/businesses/{bid}/carrier/lookup')
def automatic_carrier(sid: str,bid: str,body: CarrierPhone):
    from .extract import phone
    from . import carrier
    detail=get_scan(sid)
    business=next((b for b in detail['businesses'] if b['id']==bid),None)
    if not business:raise HTTPException(404,'Business not found.')
    number=phone(body.phone)
    known={phone(business.get('phone',''))}|{x['value'] for x in detail['identifiers'] if x['business_id']==bid and x['kind']=='phone' and x['role']=='displayed_contact'}
    if not number or number not in known:raise HTTPException(400,'Select a captured business phone number.')
    if detail['status'] in ('running','queued'):raise HTTPException(409,'Wait for this scan to finish.')
    try:result=carrier.lookup(number)
    except carrier.LookupError as e:raise HTTPException(400,str(e))
    return attach_carrier(detail,sid,bid,result,'carrier_lookup_api')

@app.post('/api/scans/{sid}/businesses/{bid}/carrier')
def save_carrier(sid: str,bid: str,body: CarrierObservation):
    from .extract import phone
    detail=get_scan(sid);business=next((b for b in detail['businesses'] if b['id']==bid),None)
    if not business:raise HTTPException(404,'Business not found.')
    number=phone(body.phone)
    if 'voip' in body.line_type and not re.search(r'\b(?:voip|voice over (?:internet|ip))\b',body.source_text,re.I):
        raise HTTPException(400,'The pasted result must explicitly report VoIP. Do not infer it from a carrier name or landline label.')
    known={phone(business.get('phone',''))}|{x['value'] for x in detail['identifiers'] if x['business_id']==bid and x['kind']=='phone' and x['role']=='displayed_contact'}
    if not number or number not in known:raise HTTPException(400,'Select a captured business phone number.')
    if detail['status'] in ('running','queued'):raise HTTPException(409,'Wait for this investigation to finish before saving a lookup.')
    result={**body.model_dump(),'phone':number,'source_url':'https://www.freecarrierlookup.com/',
        'observed_at':s.now(),'verification':'User-entered lookup result; provider response not independently retrieved.'}
    return attach_carrier(detail,sid,bid,result,'carrier_lookup_manual')

def attach_carrier(detail,sid,bid,result,kind):
    number=result['phone']
    text=json.dumps(result,ensure_ascii=False)
    cid=s.save_capture(sid,bid,result['source_url'],result['source_url'],'Carrier lookup — '+('provider response' if kind=='carrier_lookup_api' else 'user supplied'),text,text.encode(),kind)
    # Attach immediately without a model call; reassessment reads the same immutable capture.
    previous=next((a['result'] for a in detail['assessments'] if a['business_id']==bid),None)
    if previous and previous.get('combined'):
        ctx=previous['combined'].setdefault('site_context',{})
        ctx['phone_checks']=[x for x in ctx.get('phone_checks',[]) if x['phone']!=number]+[{**result,'capture_id':cid}]
        from .conclusion import combine
        external=next((x['result'] for x in detail['corroborations'] if x['business_id']==bid),{})
        discovery=next((x['result'] for x in detail['profile_discoveries'] if x['business_id']==bid),{})
        old=previous['combined']
        previous['combined']=combine(previous,{**external,'site_context':ctx},discovery,old.get('relationship_signals',[]),old.get('operator_disclosures',[]))
        if previous['combined'].get('pattern_explanation'):
            previous['conclusion']=previous['combined']['label']+'. '+previous['combined']['answer']
        with s.db() as c:c.execute('INSERT INTO assessments VALUES (?,?,?,?,?)',(s.uid(),sid,bid,s.now(),json.dumps(previous)))
    return {'capture_id':cid}

@app.get('/api/scans')
def list_scans():
    with s.db() as c:
        return [dict(x) for x in c.execute('''SELECT s.id,s.category,s.city,s.state,s.mode,s.status,s.stage,s.created_at,
            (SELECT count(*) FROM businesses b WHERE b.scan_id=s.id) business_count,
            (SELECT count(*) FROM findings f WHERE f.scan_id=s.id) finding_count
            FROM scans s ORDER BY s.created_at DESC LIMIT 100''')]

def get_scan(sid):
    result=s.scan_detail(sid)
    if not result: raise HTTPException(404,'Investigation not found.')
    return result

@app.get('/api/scans/{sid}')
def detail(sid: str): return get_scan(sid)

@app.get('/api/constitution')
def constitution():
    return {'version':reasoning.VERSION,'sha256':reasoning.POLICY_HASH,'text':reasoning.CONSTITUTION}

@app.post('/api/scans/{sid}/assess')
def reassess(sid: str):
    get_scan(sid)
    settings=s.read_settings().get('model',{})
    if not settings.get('model'): raise HTTPException(400,'Connect a local model in Settings before assessing saved evidence.')
    with s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('running','queued')").fetchone()[0]:
            raise HTTPException(409,'Finish the active investigation before reassessing saved evidence.')
        c.execute("UPDATE scans SET status='queued',cancelled=0,stage='Queued for saved-evidence assessment',updated_at=? WHERE id=?",(s.now(),sid))
    worker.POOL.submit(worker.reassess,sid,settings)
    return {'id':sid}

@app.post('/api/scans/{sid}/discover-profiles')
def discover_saved_profiles(sid: str):
    scan=get_scan(sid)
    if scan['mode']!='single': raise HTTPException(400,'Related-profile discovery is available for single-business scans.')
    with s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('running','queued')").fetchone()[0]:
            raise HTTPException(409,'Finish the active investigation before searching for related profiles.')
        c.execute("UPDATE scans SET status='queued',cancelled=0,stage='Queued for profile discovery',updated_at=? WHERE id=?",(s.now(),sid))
    worker.POOL.submit(worker.discover_saved_profiles,sid)
    return {'id':sid}

@app.post('/api/scans/{sid}/investigate')
def investigate_saved(sid: str):
    scan=get_scan(sid)
    if scan['mode']=='demo':raise HTTPException(400,'Demo scans use fictional evidence and cannot run live collection.')
    with s.db() as c:
        c.execute('BEGIN IMMEDIATE')
        if c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('running','queued')").fetchone()[0]:
            raise HTTPException(409,'Finish the active investigation before starting another.')
        c.execute("UPDATE scans SET status='queued',cancelled=0,stage='Queued for complete investigation',updated_at=? WHERE id=?",(s.now(),sid))
    worker.POOL.submit(worker.investigate_saved,sid,s.read_settings().get('model',{}))
    return {'id':sid}

@app.post('/api/scans/{sid}/cancel')
def cancel(sid: str):
    get_scan(sid)
    with s.db() as c:
        c.execute('UPDATE scans SET cancelled=1 WHERE id=?',(sid,))
    s.event(sid,'Cancellation requested. The current bounded network/model call may finish before the worker stops.')
    return {'ok':True}

class ReviewIn(BaseModel):
    state: Literal['unreviewed','supported','explained','unresolved']
    note: str=Field(default='',max_length=4000)

@app.post('/api/findings/{fid}/review')
def review(fid: str,body: ReviewIn):
    with s.db() as c:
        r=c.execute('SELECT id FROM findings WHERE id=?',(fid,)).fetchone()
        if not r: raise HTTPException(404,'Finding not found.')
        c.execute('UPDATE findings SET state=?,reviewer_note=? WHERE id=?',(body.state,body.note,fid))
        c.execute('INSERT INTO reviews VALUES (?,?,?,?,?)',(s.uid(),fid,body.state,body.note,s.now()))
    return {'ok':True}

@app.get('/api/captures/{cid}')
def capture(cid: str):
    with s.db() as c:
        row=c.execute('SELECT * FROM captures WHERE id=?',(cid,)).fetchone()
        if not row: raise HTTPException(404,'Capture not found.')
        result=dict(row); result.pop('artifact',None)
        return result

@app.get('/api/captures/{cid}/download')
def capture_download(cid: str):
    with s.db() as c:
        row=c.execute('SELECT * FROM captures WHERE id=?',(cid,)).fetchone()
        if not row: raise HTTPException(404,'Capture not found.')
        data=(s.DATA/row['artifact']).read_bytes()
    # Force plain text attachment. Do not execute captured third-party HTML.
    return Response(data,media_type='text/plain',headers={'Content-Disposition':f'attachment; filename="capture-{cid}.html.txt"'})

class ModelConfig(BaseModel):
    kind: Literal['ollama','openai']='ollama'
    endpoint: str='http://127.0.0.1:11434'
    model: str=Field(default='',max_length=150)

@app.post('/api/model/probe')
def model_probe(body: ModelConfig):
    try: return models.probe(body.endpoint,body.kind)
    except ValueError as e: raise HTTPException(400,str(e))

@app.post('/api/model/settings')
def model_save(body: ModelConfig):
    try: base=models.endpoint(body.endpoint)
    except ValueError as e: raise HTTPException(400,str(e))
    value=body.model_dump(); value['endpoint']=base
    if body.model:
        live=models.probe(base,body.kind)
        if not live['available']: raise HTTPException(400,'Local runtime is not reachable. No configuration was changed.')
        if body.model not in [x['id'] for x in live['models']]: raise HTTPException(400,'Select a model returned by this local server; no model will be downloaded.')
    s.put_setting('model',value)
    return {'ok':True,'model':value}

@app.post('/api/registry/import')
async def import_registry(request: Request):
    with s.db() as c:
        n=c.execute("SELECT COUNT(*) FROM scans WHERE status IN ('running','queued')").fetchone()[0]
    if n: raise HTTPException(409,'Finish investigations before replacing the registry snapshot.')
    date=request.headers.get('x-source-date','')
    name=request.headers.get('x-filename','registry.csv')
    name=re.sub(r'[^a-zA-Z0-9_.-]','_',name)[:120]
    path=s.DATA/'imports'/f'{uuid.uuid4().hex}.csv'
    size=0
    try:
        with path.open('wb') as f:
            async for chunk in request.stream():
                size+=len(chunk)
                if size>128*1024*1024: raise HTTPException(413,'CSV is larger than the 128 MB local import limit.')
                f.write(chunk)
        result=await asyncio.to_thread(registry.import_csv,path,name,date)
        return result
    except ValueError as e: raise HTTPException(400,str(e))
    finally: path.unlink(missing_ok=True)

@app.get('/api/registry/{license_number}')
def lookup_registry(license_number: str):
    if not re.fullmatch(r'\d{5,9}',license_number): raise HTTPException(400,'Invalid license-number format.')
    return registry.lookup(license_number)

@app.get('/api/scans/{sid}/export.json')
def export_json(sid: str):
    result=get_scan(sid)
    result['exported_at']=s.now(); result['disclaimer']='Evidence and review suggestions, not proof of fraud, ownership, or GBP ineligibility. Synthetic fixtures are not live research.'
    return Response(json.dumps(result,indent=2,ensure_ascii=False),media_type='application/json',
       headers={'Content-Disposition':f'attachment; filename="evidence-{sid[:8]}.json"'})

@app.get('/api/scans/{sid}/report',response_class=HTMLResponse)
def report(sid: str):
    d=get_scan(sid); E=html.escape
    captures={x['id']:x for x in d['captures']}; businesses={x['id']:x for x in d['businesses']}
    out=['<!doctype html><html><head><meta charset="utf-8"><title>Business evidence report</title>',
      '<style>body{max-width:900px;margin:50px auto;padding:0 25px;font:16px/1.6 system-ui;color:#17212e}h1,h2{line-height:1.2}article{border-top:1px solid #aaa;padding:24px 0;break-inside:avoid}blockquote{border-left:3px solid #777;padding-left:15px;margin-left:0}small{overflow-wrap:anywhere}.note{background:#eee;padding:15px}a{overflow-wrap:anywhere}@media print{body{margin:15px}a{color:inherit}}</style></head><body>',
      '<p>BUSINESS VALIDATOR / PRIVATE LOCAL EVIDENCE</p>',f'<h1>{E(d["category"])} · {E(d["city"])}</h1>',
      f'<p>Investigation {E(sid)}<br>Created {E(d["created_at"])}<br>Exported {E(s.now())}<br>Status: {E(d["status"])}</p>',
      '<div class="note">Evidence collection and review suggestions, not a fraud verdict. A real company may have unresolved location claims. Missing evidence is not adverse evidence. No report has been submitted anywhere.</div>']
    if d['mode']=='demo': out.append('<h2>FICTIONAL DEMONSTRATION — NOT LIVE RESEARCH</h2>')
    out.append(f'<p>{len(d["businesses"])} candidates · {len(d["captures"])} captures · {len(d["findings"])} observations/suggestions. Not exhaustive market coverage.</p>')
    if d['warnings']: out.append('<h2>Coverage limitations</h2>'+''.join('<p>'+E(x)+'</p>' for x in d['warnings']))
    for b in d['businesses']:
        out.append(f'<h2>{E(b["name"])}</h2><p>Website: {E(b["website"] or "Not captured")}<br>Profile: {E(b["profile_url"] or "Not supplied")}<br>Address: {E(b["address"] or "Unknown")}; public-display state: {E(b["address_state"])}<br>Collection status: {E(b["status"])}</p>')
        refs=d.get('cross_references',{}).get(b['id'],[])
        if refs:
            out.append('<h3>How these businesses connect</h3>')
            for ref in refs:
                out.append('<p><strong>'+E(ref['text'])+'</strong><br>'+E(ref['meaning'])+'</p><small>Captures: '+E(', '.join(ref['capture_ids']))+'</small>')
        fs=[f for f in d['findings'] if f['business_id']==b['id']]
        discovery=next((a['result'] for a in d['profile_discoveries'] if a['business_id']==b['id']),None)
        if discovery:
            out.append('<h3>Google Business Profiles</h3><p>'+E(discovery['summary'])+'</p><p>'+E(discovery['limits'])+'</p>')
            for profile in discovery['profiles']:
                out.append('<article><h3><a href="'+E(profile['profile_url'],quote=True)+'">'+E(profile['name'])+'</a></h3><p>'+E(profile['match_status'])+' · '+E(', '.join(profile['matched_by']))+'</p><p>Website: '+E(profile['website'])+'<br>Phone: '+E(profile['phone'])+'<br>'+E('Published address: '+profile['address'] if profile['address'] else 'No street address captured; storefront not assumed.')+'</p><small>Capture '+E(profile['capture_id'])+'</small></article>')
            for query in discovery['searches']:
                out.append('<p>'+E(query['kind'])+' search: '+E(query['query'])+' · '+E(query['status'])+' · '+E(query.get('error',''))+'</p>')
        elif d['mode']=='single': out.append('<p>Google Business Profile discovery has not completed. Additional listings are not assessed.</p>')
        assessment=next((a for a in d['assessments'] if a['business_id']==b['id']),None)
        external=next((a['result'] for a in d['corroborations'] if a['business_id']==b['id']),None)
        if external:
            out.append('<h3>External evidence and coverage</h3>')
            for evidence in external['evidence']:
                out.append('<article><strong>'+E(evidence['kind'])+'</strong><blockquote>'+E(evidence['quote'])+'</blockquote><p>'+E(evidence['scope'])+'</p><small>Source: '+E(evidence['url'])+' · Capture '+E(evidence['capture_id'])+'</small></article>')
            for check in external['checks']:
                out.append('<p>'+E(check['check'])+' · '+E(check['status'])+': '+E(check['detail'])+'</p>')
        if assessment:
            result=assessment['result']
            if result.get('combined'):
                joint=result['combined']
                pattern=joint.get('pattern_explanation')
                if pattern:
                    out.append('<h3>Why this pattern matters</h3><p>'+E(pattern['summary'])+'</p>')
                    for reason in pattern['reasons']:out.append('<p>'+E(reason['text'])+' · Capture '+E(reason['capture_id'])+'</p>')
                    out.append('<p>'+E(pattern['limit'])+'</p>')
                out.append('<h3>'+E(joint['label'])+'</h3><p>'+E(joint['answer'])+'</p><p>'+E(joint['profile_summary'])+'</p>')
                out.extend('<p>'+E(x)+'</p>' for x in joint['supporting']+joint['concerns'])
                for disclosure in joint.get('operator_disclosures',[]):
                    out.append('<blockquote>'+E(disclosure['quote'])+'</blockquote><p>Operator disclosure: <a href="'+E(disclosure['url'],quote=True)+'">'+E(disclosure['url'])+'</a> · Capture '+E(disclosure['capture_id'])+'</p>')
                context=joint.get('site_context',{})
                for signal in context.get('signals',[]):
                    out.append('<p><strong>'+E(signal['kind'].replace('_',' '))+'</strong>: '+E(signal['quote'])+'</p><small>'+E(signal['url'])+' · Capture '+E(signal['capture_id'])+'</small>')
                for person in context.get('staff',[]):
                    out.append('<p>Published staff: '+E(person['name'])+' — '+E(person['role'])+' · Capture '+E(person['capture_id'])+'</p>')
                for link in context.get('social_profiles',[])+context.get('outbound_links',[]):
                    out.append('<p>Captured link: '+E(link['url'])+' · Capture '+E(link['capture_id'])+'</p>')
                for path in context.get('link_paths',[]):
                    out.append('<p>Observed link path: '+E(' → '.join([path[0]['from']]+[edge['domain'] for edge in path]))+'</p>')
                for lookup in context.get('phone_checks',[]):
                    out.append('<p>Phone: '+E(lookup['phone'])+' · '+E(lookup['carrier'])+' · '+E(lookup['line_type'])+' · '+E(lookup['verification'])+' · Capture '+E(lookup['capture_id'])+'</p>')
                for signal in joint.get('relationship_signals',[]):
                    out.append('<p>'+E(signal['description'])+'</p><p>'+E(signal['alternative_explanations'])+'</p>')
                    for cid in signal['capture_ids']:
                        cap=captures.get(cid,{})
                        out.append('<small>Source: '+E(cap.get('final_url',''))+' · Capture '+E(cid)+'</small><br>')
                out.extend('<p>Unknown — '+E(x['check'])+': '+E(x['detail'])+'</p>' for x in joint['gaps'])
            out.append('<h3>Business assessment</h3><p>'+E(result['conclusion'])+'</p><p>'+E(result['status'])+' · Model '+E(result['model'] or 'Not connected')+' · Constitution '+E(result['constitution_version'])+' · '+E(assessment['created_at'])+'</p>')
            for claim in result['claims']:
                cap=captures[claim['capture_id']]
                out.append('<article><p>'+E(claim['statement'])+'</p><blockquote>'+E(claim['quote'])+'</blockquote><p>'+E(claim['limitation'])+'</p><small>Source: '+E(cap['final_url'])+' · '+E(cap['sha256'])+'</small></article>')
            out.append('<ul>'+''.join('<li>'+E(limit)+'</li>' for limit in result['limits'])+'</ul>')
        for f in fs:
            cap=captures.get(f['capture_id'],{})
            url=cap.get('final_url','')
            out.append(f'<article><h3>{E(f["title"])}</h3><p>{E(f["dimension"])} · {E(f["strength"])} · review: {E(f["state"])}</p><blockquote>{E(f["quote"])}</blockquote><p>{E(f["explanation"])}</p><p>Reviewer note: {E(f["reviewer_note"] or "None")}</p><small>Source: <a href="{E(url,quote=True)}" rel="noreferrer">{E(url)}</a><br>Observed {E(cap.get("observed_at",""))}<br>SHA-256 {E(cap.get("sha256",""))}<br>Rule {E(f["rule"])}</small></article>')
    out.append('<h2>Connected identifiers</h2>')
    for c in d['connections']: out.append(f'<p>{E(c["kind"])} {E(c["value"])}: {c["business_count"]} candidates. {E(c["interpretation"])}</p>')
    out.append('<h2>Method and unfinished checks</h2><p>Selective public HTML collection; exact-quote rules; optional local-model proposals; optional imported CSLB snapshot. This build does not independently verify premises, staffing, legal ownership, or licensing status in real time. Website rendering, source freshness, and discovery coverage may be incomplete. Export JSON includes the activity log.</p></body></html>')
    return ''.join(out)

@app.post('/api/shutdown')
def shutdown():
    worker.STOP.set()
    with s.db() as c: c.execute("UPDATE scans SET cancelled=1 WHERE status IN ('running','queued')")
    if SERVER:
        def stop():
            time.sleep(.4); SERVER.should_exit=True
        threading.Thread(target=stop,daemon=True).start()
    return {'ok':True,'message':'Shutdown requested; a bounded in-flight operation may finish before the process exits.'}


def main():
    global SERVER
    s.DATA.mkdir(parents=True,exist_ok=True)
    conf=uvicorn.Config(app,host='127.0.0.1',port=PORT,log_level='info',proxy_headers=False,access_log=False)
    SERVER=uvicorn.Server(conf)
    SERVER.run()
    worker.STOP.set()
    worker.POOL.shutdown(wait=True,cancel_futures=True)

if __name__=='__main__': main()
