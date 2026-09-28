"""One local job at a time; bounded collection; optional serial model requests."""
from __future__ import annotations
import concurrent.futures
import json
import logging
import re
import threading
from urllib.parse import urlsplit
from pathlib import Path
from . import storage as s
from . import extract, models, registry, reasoning
from .net import PoliteFetcher, FetchError,normalize_url

POOL=concurrent.futures.ThreadPoolExecutor(max_workers=1,thread_name_prefix='evidence-worker')
STOP=threading.Event()

def submit(scan_id): return POOL.submit(run,scan_id)

def cancelled(sid): return STOP.is_set() or s.is_cancelled(sid)


def analyze_capture(sid,bid,cid,page,config,model_count):
    for ident in page['identifiers']:
        s.add_identifier(sid,bid,cid,**ident)
    for finding in extract.observations(page['text']):
        if page.get('external_document'):
            finding['strength']='unresolved'
            finding['explanation']='This is an externally linked document, not the business website itself. Confirm whose statement it is before attributing it to the business. '+finding['explanation']
        s.add_finding(sid,bid,cid,**finding)
    if config.get('state','').upper() in ('CA','CALIFORNIA'):
        for x in page['identifiers']:
            if x['kind']!='license' or x['role']=='third_party': continue
            result=registry.lookup(x['value'])
            if result['status']=='not_configured': continue
            if result['status']=='found':
                r=result['record']; meta=result['snapshot']
                s.add_finding(sid,bid,cid,'license','license:snapshot_match','record_match',
                  'Claimed license has a record in the imported snapshot',
                  f"License {x['value']}: {r['name']}; recorded status: {r['status'] or 'not supplied'}. Snapshot source date {meta['source_date']}. This does not confirm the website operator owns the license, resolve a DBA, or establish current status. Verify the official current record before drawing conclusions.",x['context'])
            else:
                s.add_finding(sid,bid,cid,'license','license:snapshot_missing','unresolved',
                  'Claimed license not found in the imported snapshot',
                  'The imported file may omit expired, canceled, or revoked records, or be incomplete/out of date. This is NOT a fake-license finding. An individual current official lookup is still required.',x['context'])
    cfg=config.get('model_config',{})
    if config.get('use_model') and cfg.get('model') and model_count<2 and len(page['text'])>=80 and not cancelled(sid):
        s.stage(sid,'Local model: checking a captured passage; one request at a time.')
        result,error=models.analyze(page['text'],cfg)
        if result:
            dimension='location' if result['classification']=='location_review' else 'business_role'
            s.add_finding(sid,bid,cid,dimension,'local-model:quoted-proposal','model_suggestion',
               'Local model suggestion: '+result['classification'].replace('_',' '),
               result['reason']+' Quote presence was checked mechanically. Interpretation is not independently verified; review required.',result['quote'])
        if error: s.event(sid,error,'warning')
        return model_count+1
    return model_count


def crawl_business(sid,bid,url,config):
    collector=PoliteFetcher(); pending=[normalize_url(url)]; seen=set(); count=0; model_count=0; origin=None
    max_pages=config.get('max_pages',8)
    while pending and count<max_pages and not cancelled(sid):
        target=pending.pop(0)
        if target in seen: continue
        seen.add(target)
        s.stage(sid,'Collecting '+target[:180])
        try:
            result=collector.get(target)
            if result.status>=400: raise FetchError(f'HTTP {result.status}; not treated as business evidence.')
            if not any(x in result.content_type.lower() for x in ('text/html','application/xhtml','text/plain')):
                raise FetchError('Unsupported content type; HTML/text only in this build.')
            page=extract.parse_page(result.text,result.url)
            if any(x in page['text'].lower()[:5000] for x in ('verify you are human','checking your browser','enable javascript and cookies to continue','just a moment...')):
                raise FetchError('Possible access challenge; no bypass attempted.')
            if not page['text']: raise FetchError('No extractable text; this site may require browser rendering.')
            cid=s.save_capture(sid,bid,target,result.url,page['title'],page['text'],result.content)
            count+=1
            if not origin: origin=urlsplit(result.url).hostname
            if count==1:
                with s.db() as c:
                    c.execute("UPDATE businesses SET name=? WHERE id=? AND source='website_input'",(page['title'][:150],bid))
            page['external_document']=urlsplit(result.url).hostname!=origin
            model_count=analyze_capture(sid,bid,cid,page,{**config,'use_model':False},model_count)
            links=sorted(page['links'],key=lambda x: 0 if re.search('terms|privacy|disclaim',x['label']+' '+x['url'],re.I) else 1 if re.search('about|team|staff|contact|people',x['label']+' '+x['url'],re.I) else 2)
            for item in links:
                link=item['url']; host=urlsplit(link).hostname
                # Two external legal destinations max; context/attribution preserved.
                external_legal=bool(re.search('terms|privacy|legal|disclaim',item['label'],re.I))
                if host==origin or (external_legal and sum(urlsplit(x).hostname!=origin for x in pending)<2):
                    if link not in seen and link not in pending and len(pending)<30: pending.append(link)
        except (FetchError,ValueError) as e:
            s.event(sid,f'{target}: {e}','warning')
    if pending:
        s.event(sid,'Page limit reached; additional pages were not checked.','warning')
    with s.db() as c:
        c.execute('UPDATE businesses SET status=? WHERE id=?',('collected' if count else 'source_unavailable',bid))
    if not count: s.warn(sid,'At least one website could not be collected. Missing data does not increase suspicion.')


def demo(sid,config):
    root=s.ROOT/'fixtures'
    for website,name,files in (
      ('https://cedar-referral.example','Cedar Roof Connect — FICTIONAL',['referral-home.html','referral-terms.html']),
      ('https://cedar-market.example','Cedar Market Connect — FICTIONAL',['network.html']),
      ('https://honest-roofs.example','Honest Roofs — FICTIONAL',['legitimate.html'])):
        bid=s.business(sid,name,website=website,source='synthetic_fixture')
        for filename in files:
            raw=(root/filename).read_bytes(); url=website+'/'+filename; page=extract.parse_page(raw.decode(),url)
            cid=s.save_capture(sid,bid,url,url,page['title'],page['text'],raw,'synthetic_fixture')
            analyze_capture(sid,bid,cid,page,{**config,'use_model':False},2)
        with s.db() as c: c.execute("UPDATE businesses SET status='collected' WHERE id=?",(bid,))
    s.warn(sid,'DEMO: all businesses and source pages in this investigation are fictional fixtures. No live research was performed.')


def run(sid):
    try:
        if cancelled(sid): s.stage(sid,'Cancelled before collection.','cancelled'); return
        detail=s.scan_detail(sid); cfg=detail['config']; cfg['state']=detail['state']
        s.stage(sid,'Starting local evidence investigation.','running')
        if detail['mode']=='demo': demo(sid,cfg)
        else:
            if cfg.get('use_model') and not cfg.get('model_config',{}).get('model'):
                s.warn(sid,'No local model selected. This run uses deterministic evidence checks only; configure Local model for subsequent runs.')
            if detail['mode']=='maps':
                from .maps import discover
                candidates=discover(detail['category'],detail['city'],detail['state'],cfg['max_businesses'],
                        lambda x:s.stage(sid,x),lambda:cancelled(sid),cfg.get('headless',False))
                for x in candidates: s.business(sid,**x)
                s.warn(sid,'Maps discovery is a bounded sample, not complete market coverage. Public address display is unknown where the visible address control was not readable.')
            elif detail['mode']=='single':
                s.business(sid,cfg['business_name'].strip(),website=cfg['urls'][0],source='user_named_website',**cfg.get('seed_profile',{}))
                s.event(sid,'Business name and website supplied by the user; their relationship has not been independently verified.')
            else:
                for url in cfg.get('urls',[]):
                    s.business(sid,urlsplit(url).hostname or url,website=url,source='website_input')
            with s.db() as c: businesses=[dict(x) for x in c.execute('SELECT * FROM businesses WHERE scan_id=?',(sid,))]
            visited={}
            for i,b in enumerate(businesses):
                if cancelled(sid): break
                s.stage(sid,f'Business {i+1}/{len(businesses)}: {b["name"]}')
                if not b['website']:
                    with s.db() as c: c.execute("UPDATE businesses SET status='no_website' WHERE id=?",(b['id'],))
                    s.event(sid,b['name']+': no website captured; profile and external checks will still run.'); continue
                try:
                    crawl_business(sid,b['id'],b['website'],cfg)
                except Exception as e:
                    logging.exception('Business collection failed')
                    s.warn(sid,b['name']+': collection failed safely: '+str(e)[:200])
                    with s.db() as c: c.execute("UPDATE businesses SET status='source_unavailable' WHERE id=?",(b['id'],))
            # Compare all collected website identifiers before assessing any business.
            for i,b in enumerate(businesses):
                if cancelled(sid):break
                s.stage(sid,f'Investigating {i+1}/{len(businesses)}: {b["name"]}')
                enrich_business(sid,b,cfg)
        if cancelled(sid): s.stage(sid,'Cancelled; evidence already saved is retained.','cancelled')
        else:
            detail=s.scan_detail(sid)
            warnings=any(x['level']=='warning' for x in detail['events']) or bool(detail['warnings'])
            state='ready_with_gaps' if warnings else 'ready'
            s.stage(sid,f"Complete: {len(detail['businesses'])} businesses, {len(detail['captures'])} source captures. Assessments and collection limits are available below.",state)
    except Exception as e:
        logging.exception('Investigation failed')
        s.warn(sid,str(e)[:700]); s.stage(sid,'Investigation could not complete. See activity for the specific error.','failed')

def assess_business(sid,business,settings):
    s.stage(sid,'Assessing business evidence against constitution '+reasoning.VERSION+'.')
    with s.db() as c:
        captures=[dict(x) for x in c.execute('SELECT * FROM captures WHERE scan_id=? AND business_id=? ORDER BY rowid',(sid,business['id']))]
    from .conclusion import combine
    from .relationships import signals
    detail=s.scan_detail(sid)
    external=next((a['result'] for a in detail['corroborations'] if a['business_id']==business['id']),{})
    discovery=next((a['result'] for a in detail['profile_discoveries'] if a['business_id']==business['id']),{})
    leads=signals(business,detail,discovery)
    from .disclosures import collect
    explicit=collect(business,captures)
    from .site_signals import analyze
    context=analyze(business,captures)
    context['phone_checks']=[]
    for cap in captures:
        if cap.get('source_type') in ('carrier_lookup_manual','carrier_lookup_api'):
            try:
                item=json.loads(cap['text']);item['capture_id']=cap['id']
                context['phone_checks']=[x for x in context['phone_checks'] if x['phone']!=item['phone']]+[item]
            except (ValueError,KeyError):pass
    external={**external,'site_context':context}
    from .relationships import cross_references
    reference_detail={**detail,'assessments':[{'business_id':business['id'],'result':{'combined':{'site_context':context}}}]+detail['assessments']}
    for ref in cross_references(reference_detail).get(business['id'],[]):
        leads.append({'kind':'cross_reference','description':ref['text'],'alternative_explanations':ref['meaning'],
                      'capture_ids':ref['capture_ids'],'requires_review':False})
    result=reasoning.assess(business,captures,settings,lambda:cancelled(sid),relationships=leads,site_context=context)
    result['combined']=combine(result,external,discovery,leads,explicit)
    if explicit or result['combined'].get('pattern_explanation'):
        result['conclusion']=result['combined']['label']+'. '+result['combined']['answer']
    disclosures=[f for f in detail['findings'] if f['business_id']==business['id'] and f['dimension']=='business_role' and f['strength']=='direct_statement']
    if disclosures and not explicit:
        result['combined']['label']='Intermediary disclosures need interpretation'
        result['combined']['answer']='The website includes referral or non-performance wording that needs attribution.'
        result['combined']['concerns'].extend(f['title']+': '+f['quote'] for f in disclosures[:3])
    with s.db() as c:
        c.execute('INSERT INTO assessments VALUES (?,?,?,?,?)',(s.uid(),sid,business['id'],s.now(),json.dumps(result)))
    if result['status']!='assessed': s.event(sid,result['conclusion']+' '+result.get('error',''),'warning')

def enrich_business(sid,business,config):
    """One investigation path for market, single-business, and URL scans."""
    for name,collect in (('Related profiles',discover_profiles),('External evidence',corroborate_business)):
        if cancelled(sid):return
        try:collect(sid,business)
        except Exception as exc:
            logging.exception('%s failed',name)
            s.event(sid,business['name']+': '+name+' failed: '+str(exc)[:180],'warning')
    if not cancelled(sid):assess_business(sid,business,config.get('model_config',{}) if config.get('use_model') else {})

def discover_profiles(sid,business):
    from . import gbp
    with s.db() as c:
        scan_location=c.execute('SELECT city,state FROM scans WHERE id=?',(sid,)).fetchone()
        identifiers=[dict(x) for x in c.execute('SELECT * FROM identifiers WHERE business_id=?',(business['id'],))]
        pages=[dict(x) for x in c.execute("SELECT * FROM captures WHERE business_id=? AND source_type='website' ORDER BY rowid",(business['id'],))]
    number=extract.phone(business.get('phone',''))
    if number:identifiers.append({'kind':'phone','value':number,'role':'displayed_contact'})
    seeds={};aliases={}
    for page in pages:
        if gbp.domain(page['final_url'])!=gbp.domain(business['website']):continue
        for profile in gbp.website_profiles((s.DATA/page['artifact']).read_bytes(),page['final_url'],page['id']):seeds[profile['key']]=profile
        for alias in gbp.website_aliases((s.DATA/page['artifact']).read_bytes(),page['final_url'],page['id']):aliases[alias['name'].casefold()]=alias
    def capture(url,title,text,raw,kind):
        return s.save_capture(sid,business['id'],url,url,title,text,raw,kind)
    location=', '.join(x for x in scan_location if x and x!='Not specified')
    result=gbp.investigate(business,identifiers,lambda message:s.stage(sid,message),lambda:cancelled(sid),capture,seeds=list(seeds.values()),aliases=list(aliases.values()),location=location)
    with s.db() as c:
        c.execute('INSERT INTO profile_discoveries VALUES (?,?,?,?,?)',(s.uid(),sid,business['id'],s.now(),json.dumps(result)))
    s.event(sid,result['summary'],'info' if result['status']=='complete' else 'warning')

def corroborate_business(sid,business):
    from . import corroboration
    detail=s.scan_detail(sid)
    discovery=next((a['result'] for a in detail['profile_discoveries'] if a['business_id']==business['id']),{})
    with s.db() as c:
        captures=[dict(x) for x in c.execute('SELECT * FROM captures WHERE scan_id=? AND business_id=? ORDER BY rowid',(sid,business['id']))]
    result=corroboration.investigate({**business,'scan_id':sid},captures,discovery,
        [x for x in detail['identifiers'] if x['business_id']==business['id']],
        lambda message:s.stage(sid,message),lambda:cancelled(sid),deep=detail['config'].get('max_pages',8)>=12)
    with s.db() as c:c.execute('INSERT INTO corroborations VALUES (?,?,?,?,?)',(s.uid(),sid,business['id'],s.now(),json.dumps(result)))

def investigate_saved(sid,settings):
    try:
        s.stage(sid,'Refreshing the complete business investigation.','running')
        detail=s.scan_detail(sid)
        cfg={**detail['config'],'model_config':settings,'use_model':bool(settings.get('model'))}
        for business in detail['businesses']:
            if cancelled(sid):break
            if business['website']:crawl_business(sid,business['id'],business['website'],cfg)
        for i,business in enumerate(detail['businesses']):
            if cancelled(sid):break
            s.stage(sid,f'Investigating {i+1}/{len(detail["businesses"])}: {business["name"]}')
            enrich_business(sid,business,cfg)
        s.stage(sid,'Combined investigation finished. See conclusion, supporting evidence, and exact coverage below.','cancelled' if cancelled(sid) else 'ready')
    except Exception as exc:
        logging.exception('Combined investigation failed')
        s.stage(sid,'Investigation failed: '+str(exc)[:250],'failed')

def discover_saved_profiles(sid):
    try:
        s.stage(sid,'Searching Maps for profiles related to the saved business.','running')
        for business in s.scan_detail(sid)['businesses']:
            if cancelled(sid): break
            discover_profiles(sid,business)
        latest=s.scan_detail(sid)['profile_discoveries']
        state='cancelled' if cancelled(sid) else 'ready' if latest and latest[0]['result']['status']=='complete' else 'ready_with_gaps'
        s.stage(sid,'Profile discovery finished. See matches, search coverage, and captured sources.',state)
    except Exception as exc:
        logging.exception('Profile discovery failed')
        s.stage(sid,'Profile discovery failed: '+str(exc)[:250],'failed')

def reassess(sid,settings):
    try:
        s.stage(sid,'Reassessing saved evidence with the current local model.','running')
        detail=s.scan_detail(sid)
        for business in detail['businesses']:
            if cancelled(sid): break
            assess_business(sid,business,settings)
        detail=s.scan_detail(sid)
        state='cancelled' if cancelled(sid) else 'ready_with_gaps' if detail['warnings'] or any(e['level']=='warning' for e in detail['events']) else 'ready'
        s.stage(sid,'Saved-evidence assessment finished. Original captures and earlier assessments retained.',state)
    except Exception as exc:
        logging.exception('Reassessment failed')
        s.stage(sid,'Reassessment failed: '+str(exc)[:200],'failed')
