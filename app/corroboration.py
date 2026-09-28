"""Bounded external corroboration; source failures and provenance remain explicit."""
import json
import re
import time
from urllib.parse import urljoin,urlsplit,quote,parse_qs
from bs4 import BeautifulSoup
from . import storage as s
from .net import PoliteFetcher,fetch,normalize_url,public_addresses
from .gbp import domain
from .maps import browser_launch

SKIP_HOSTS={'google.com','maps.google.com','youtube.com','youtu.be','facebook.com','instagram.com','linkedin.com','x.com','twitter.com','gstatic.com','googleapis.com','schema.org','wordpress.org'}
WORK=re.compile(r'portfolio|case.stud|results|projects|clients|work|website|visit',re.I)
CREDIT=re.compile(r'powered by|(?:web(?:site)?|site).{0,35}(?:design|develop|build|built|by)|(?:design|develop|built|marketing|seo).{0,20}by',re.I)
CHALLENGE=re.compile(r'verify you are human|checking your browser|enable javascript and cookies|unusual traffic|before you continue to google',re.I)

def eligible(url,own):
    host=domain(url)
    return host and host!=own and not any(host==h or host.endswith('.'+h) for h in SKIP_HOSTS)

def page_links(raw,url,own):
    soup=BeautifulSoup(raw,'html.parser');links=[]
    for a in soup.find_all('a',href=True):
        target=urljoin(url,a['href']).split('#')[0]
        if urlsplit(target).scheme not in ('http','https'):continue
        if eligible(target,own):
            context=a.parent.get_text(' ',strip=True)[:700]
            links.append({'url':target,'context':context,'priority':0 if WORK.search(context+' '+url) else 1})
    return sorted(links,key=lambda x:x['priority'])

def external_evidence(raw,url,own):
    soup=BeautifulSoup(raw,'html.parser');found=[]
    for a in soup.find_all('a',href=True):
        if domain(urljoin(url,a['href']))!=own:continue
        text=a.parent.get_text(' ',strip=True)
        if len(text)<15 and a.parent.parent:text=a.parent.parent.get_text(' ',strip=True)
        text=text[:1200]
        found.append({'kind':'work_credit' if CREDIT.search(text) else 'backlink',
                      'quote':text,'target':urljoin(url,a['href'])})
    return found

def public_search(query,capture):
    """Discovery only: result snippets never become factual corroboration."""
    from playwright.sync_api import sync_playwright
    result={'query':query,'status':'failed','urls':[],'error':''}
    url='https://www.google.com/search?q='+quote(query,safe='')+'&num=10&hl=en'
    try:
        with sync_playwright() as p:
            browser=browser_launch(p,headless=True)
            try:
                context=browser.new_context(accept_downloads=False,service_workers='block')
                # Only Google search infrastructure can load in this context.
                validated=set()
                def route(r):
                    host=domain(r.request.url)
                    if urlsplit(r.request.url).scheme not in ('http','https') or not any(host==h or host.endswith('.'+h) for h in ('google.com','gstatic.com','googleusercontent.com')):r.abort();return
                    try:
                        if host not in validated:public_addresses(host,443);validated.add(host)
                    except Exception:r.abort();return
                    r.continue_()
                context.route('**/*',route)
                page=context.new_page();page.goto(url,wait_until='domcontentloaded',timeout=30000);page.wait_for_timeout(2200)
                text=page.locator('body').inner_text();raw=page.content().encode()
                result['capture_id']=capture(page.url,page.title(),text,raw,'external_search')
                if CHALLENGE.search(text):result.update(status='blocked',error='Search displayed an access challenge; further web searches stopped.');return result
                for href in page.locator('a:has(h3)').evaluate_all('(els)=>els.map(e=>e.href)'):
                    if domain(href)=='google.com' and '/url?' in href:
                        href=(parse_qs(urlsplit(href).query).get('q') or [''])[0]
                    if href.startswith(('https://','http://')) and domain(href)!='google.com':result['urls'].append(href)
                result['urls']=list(dict.fromkeys(result['urls']))[:6]
                if result['urls']:result['status']='complete'
                elif re.search(r'did not match any documents|no results found',text,re.I):result['status']='complete'
                else:result['error']='No usable search links; this is not evidence of no external mentions.'
            finally:browser.close()
    except Exception as exc:result['error']=str(exc).splitlines()[0][:250]
    return result

def investigate(business,captures,discovery,identifiers,report,cancelled,collector=None,search=public_search,api_fetch=fetch,deep=False):
    collector=collector or PoliteFetcher();own=domain(business['website'])
    result={'version':'1.0','started_at':s.now(),'checks':[],'evidence':[],'searches':[],
            'limits':['External credits may be placed by the service provider; they are not automatically independent endorsements.',
                      'Review samples are customer claims, not authenticated purchases. Repeated credits on one domain count as one relationship.',
                      'Public search does not provide a complete backlink index. Collection is bounded to eight external domains.']}
    def save(url,title,text,raw,kind):return s.save_capture(business['scan_id'],business['id'],url,url,title,text,raw,kind)
    def evidence(kind,cid,url,text,scope):
        item={'kind':kind,'capture_id':cid,'url':url,'quote':text[:1200],'scope':scope}
        if not any(x['kind']==kind and x['url']==url and x['quote']==item['quote'] for x in result['evidence']):result['evidence'].append(item)
    candidates=[];testimonial_count=0;review_count=0
    latest={}
    for cap in captures:latest[(cap['final_url'],cap['source_type'],cap.get('text','') if cap['source_type']=='customer_review' else '')]=cap
    captures=list(latest.values())
    for cap in captures:
        if cancelled():break
        raw=(s.DATA/cap['artifact']).read_bytes()
        soup=BeautifulSoup(raw,'html.parser')
        if cap['source_type']=='website' and domain(cap['final_url'])==own:
            candidates.extend(page_links(raw,cap['final_url'],own))
            # Customer quotations remain separate from operator statements.
            for node in soup.select('blockquote,[itemprop="reviewBody"]')[:6]:
                text=node.get_text(' ',strip=True)
                if len(text)<30:continue
                if any(e['kind']=='testimonial' and e['quote']==text[:1200] for e in result['evidence']):continue
                cid=save(cap['final_url'],'On-site customer quotation',text,raw,'onsite_testimonial')
                evidence('testimonial',cid,cap['final_url'],text,'Business-published quotation; customer identity and experience not independently verified.')
                testimonial_count+=1
        if cap['source_type']=='maps_profile':
            if review_count>=8:continue
            # Only use reviews attached to identifier-matched profile observations.
            matched_ids={c for p in (discovery or {}).get('profiles',[]) if p['match_status']=='identifier_match' for c in p.get('capture_ids',[p['capture_id']])}
            if cap['id'] not in matched_ids:continue
            for node in soup.select('[data-review-id]'):
                review=node.select_one('.wiI7pd')
                if review is None:continue
                text=review.get_text(' ',strip=True)
                if len(text)<30 or any(e['kind']=='customer_review' and e['quote']==text[:1200] for e in result['evidence']):continue
                cid=save(cap['final_url'],'Public Maps review excerpt',text,raw,'customer_review')
                evidence('customer_review',cid,cap['final_url'],text,'Visible Google review sample; not independently authenticated. No reviewer profiling performed.')
                review_count+=1
                if review_count>=8:break
    result['checks'].append({'check':'Customer accounts','status':'complete' if testimonial_count or review_count else 'limited',
        'detail':f'{testimonial_count} on-site quotations and {review_count} distinct visible review excerpts collected. This is a sample, not the full review history.'})
    queries=(f'"{own}" -site:{own}',f'"{business["name"]}" "website" -site:{own}') if own else (f'"{business["name"]}" business reviews',)
    for query in queries:
        if cancelled():break
        report('Discovering external mentions: '+query)
        outcome=search(query,save);result['searches'].append(outcome)
        candidates.extend({'url':url,'context':'Public search discovery','priority':1} for url in outcome['urls'])
        if outcome['status']=='blocked':break
    visited=set();failures=[];checked=0
    pending=sorted(candidates,key=lambda x:x['priority'])
    budget=12 if deep else 8
    result['limits'][-1]=f'Public search does not provide a complete backlink index. At most {budget} external domains; '+('up to two link hops.' if deep else 'direct links and search results only.')
    while pending:
        candidate=pending.pop(0)
        if cancelled() or len(visited)>=budget:break
        url=candidate['url'];host=domain(url)
        if not eligible(url,own) or host in visited:continue
        visited.add(host);report('Checking external source: '+url)
        try:
            page=collector.get(url)
            if page.status>=400 or 'html' not in page.content_type:raise ValueError('Source returned no usable HTML.')
            text=BeautifulSoup(page.content,'html.parser').get_text(' ',strip=True)
            if CHALLENGE.search(text[:5000]):raise ValueError('Source displayed an access challenge.')
            if not eligible(page.url,own):raise ValueError('Source redirected to the business itself or an excluded platform.')
            checked+=1
            observations=external_evidence(page.content,page.url,own) if own else []
            cid=save(page.url,'External business reference',text,page.content,'external_page')
            if deep and candidate.get('depth',0)==0:
                from .site_signals import links,TRADE
                follow=[x for x in links(page.content,page.url) if eligible(x['url'],own) and x['domain'] not in visited and TRADE.search(x['anchor'])]
                # Reserve part of the same total budget for observed second-hop edges.
                pending[0:0]=[{**x,'priority':1,'depth':1} for x in follow[:2]]
            for item in observations:
                ecid=save(page.url,'External '+item['kind'],item['quote'],page.content,'external_credit' if item['kind']=='work_credit' else 'external_mention')
                evidence(item['kind'],ecid,page.url,item['quote'],'Published on another domain; editorial independence and authorship unverified.')
            if not observations and re.search(re.escape(business['name']),text,re.I):
                match=re.search(re.escape(business['name']),text,re.I);excerpt=text[max(0,match.start()-120):match.end()+300]
                evidence('mention',cid,page.url,excerpt,'Business-name mention only; relationship not established.')
        except Exception as exc:failures.append({'url':url,'error':str(exc)[:220]})
    result['checks'].append({'check':'External work credits and backlinks','status':'limited' if failures or len({domain(c['url']) for c in candidates if eligible(c['url'],own)})>len(visited) else 'complete',
        'detail':f'{checked} external domains checked; {len(failures)} failed. Only exact link targets and captured attribution are counted.',
        'failures':failures,'visited_domains':sorted(visited)})
    result['checks'].append({'check':'External discovery','status':'complete' if result['searches'] and all(x['status']=='complete' for x in result['searches']) else 'limited',
        'detail':f'{len(result["searches"])} of two planned public searches attempted, plus links discovered on the business website; no comprehensive backlink index.'})
    for kind,url in (
        ('Domain registration','https://rdap.org/domain/'+quote(own,safe='')),
        ('Website history','https://archive.org/wayback/available?url='+quote(business['website'],safe=''))):
        if not own:
            result['checks'].append({'check':kind,'status':'not_triggered','detail':'No website domain available; not a negative business signal.'});continue
        if cancelled():break
        report('Checking '+kind.lower())
        try:
            response=api_fetch(url,timeout=12,limit=500000)
            if response.status>=400:raise ValueError(f'HTTP {response.status}')
            data=json.loads(response.text)
            if kind=='Domain registration':
                dates=[x.get('eventDate') for x in data.get('events',[]) if x.get('eventAction')=='registration']
                text=f'Domain {own}: registration event '+(', '.join(dates) if dates else 'not supplied')
                cid=save(response.url,kind,text,response.content,'domain_registration')
                evidence('domain_registration',cid,response.url,text,'Domain registration date is not the business founding date and does not prove continuous ownership.')
                detail=text
            else:
                snapshot=data.get('archived_snapshots',{}).get('closest',{})
                if not snapshot.get('available'):
                    result['checks'].append({'check':kind,'status':'not_found','detail':'No accessible snapshot returned by the availability API; not evidence of a new or fake business.'});continue
                text=f'Archived snapshot available: {snapshot.get("timestamp")} at {snapshot.get("url")}'
                cid=save(response.url,kind,text,response.content,'website_history')
                evidence('archive_available',cid,response.url,text,'Archive availability only; historical business claims have not been verified from snapshot contents.')
                detail=text
            result['checks'].append({'check':kind,'status':'complete','detail':detail})
        except Exception as exc:result['checks'].append({'check':kind,'status':'failed','detail':str(exc)[:250]})
    licenses=[x for x in identifiers if x['kind']=='license' and x['role']=='claimed_license']
    result['checks'].append({'check':'Official licensing','status':'not_checked' if licenses else 'not_triggered',
        'detail':'License claims found; any imported snapshot matches remain separate from current official verification.' if licenses else 'No explicit license number extracted; no licensing requirement inferred from the business category.'})
    result['finished_at']=s.now();result['status']='cancelled' if cancelled() else 'complete'
    return result
