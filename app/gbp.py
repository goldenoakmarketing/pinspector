"""Bounded Maps identifier discovery with explicit search outcomes and source captures."""
import re
import time
import unicodedata
from difflib import SequenceMatcher
from urllib.parse import quote, urlsplit, parse_qs, unquote
from . import storage as s
from .extract import phone
from .maps import browser_launch
from .net import public_addresses, normalize_url

def website_profiles(raw,source_url,capture_id):
    """Read explicit Google listing IDs from links/iframes; never infer pins from coordinates."""
    from bs4 import BeautifulSoup
    from urllib.parse import urljoin
    found={}
    for node in BeautifulSoup(raw,'html.parser').select('iframe,a[href]'):
        url=urljoin(source_url,node.get('src') or node.get('data-src') or node.get('href',''))
        if domain(url) not in ('google.com','maps.google.com') or '/maps' not in urlsplit(url).path:continue
        key=profile_key(url)
        if not re.fullmatch(r'cid:\d+',key):continue
        decoded=unquote(url)
        label=re.search(r'!2s([^!]+)',decoded)
        name=label.group(1) if label else node.get('title') or node.get_text(' ',strip=True) or 'Website-linked Google listing'
        found[key]={'key':key,'profile_url':'https://www.google.com/maps?cid='+key[4:],
            'name':name,'website':'','phone':'','address':'','address_state':'not_observed',
            'capture_id':capture_id,'identity_source':'website_embed' if node.name=='iframe' else 'website_link',
            'source_url':source_url,'embedded_url':url,'match_status':'website_reference','matched_by':['website_reference'],
            'name_matches':False,'queries':[],'capture_ids':[capture_id]}
    return list(found.values())

def domain(url):
    try: return (urlsplit(url).hostname or '').lower().removeprefix('www.').rstrip('.')
    except ValueError: return ''

def profile_key(url):
    decoded=unquote(url)
    match=re.search(r'!1s([^!/?]+)',decoded)
    def normalized(value):
        if re.fullmatch(r'0x[0-9a-f]+:0x[0-9a-f]+',value,re.I): return 'cid:'+str(int(value.split(':')[1],16))
        if value.isdigit(): return 'cid:'+value
        return value
    if match: return normalized(match.group(1))
    params=parse_qs(urlsplit(url).query)
    for key in ('cid','ftid','query_place_id'):
        if params.get(key): return normalized(params[key][0])
    return urlsplit(url)._replace(query='',fragment='').geturl()

NAME_GENERIC=set('all window windows replacement landscaping landscape lawn garden restaurant cafe food painting painter electrical electrician hvac the a an and of in at for by llc inc incorporated ltd limited co company corp corporation group services service solutions agency agencies local seo digital marketing web website design internet search engine optimization advertising best top pro professional expert experts affordable premier quality california ca usa united states plumbing plumber roofing roofer insulation contractor contractors heating cooling repair installation'.split())


def name_tokens(value):
    value=unicodedata.normalize('NFKD',value).encode('ascii','ignore').decode().lower()
    return re.findall(r'[a-z0-9]+',value.replace('&',' and '))


def brand_tokens(name,location='',address=''):
    # Explicit location context and a listing's address identify geographic words;
    # do not infer that every unfamiliar word is a city or a brand.
    places=set(name_tokens(location))
    parts=address.split(',')
    if len(parts)>=3:places.update(name_tokens(parts[-2]))
    elif len(parts)==2:places.update(name_tokens(parts[0]))
    name=re.split(r'\s+(?:of|in|at)\s+',name,maxsplit=1,flags=re.I)[0]
    return [w for w in name_tokens(name) if w not in NAME_GENERIC and w not in places]


def name_connection(profile,name,location=''):
    left=name_tokens(name);right=name_tokens(profile.get('name',''))
    if left and left==right:return 'exact_name','Exact normalized business name'
    trades=({'window','windows','replacement'},{'landscaping','landscape','lawn','garden'},{'plumber','plumbing'},{'roof','roofing','roofer'},{'restaurant','cafe','sandwich','grill','brewing','brewery','bar'},{'seo','marketing','advertising'},{'electrical','electrician'},{'painting','painter'})
    left_trades={i for i,t in enumerate(trades) if set(left)&t}
    right_trades={i for i,t in enumerate(trades) if set(right)&t}
    if left_trades and right_trades and left_trades.isdisjoint(right_trades):return '', ''
    a=brand_tokens(name,location)
    b=brand_tokens(profile.get('name',''),location,profile.get('address',''))
    shared=set(a)&set(b)
    # A distinctive shared brand token or phrase can survive added service/city
    # keywords. Generic-only names require an exact match or another identifier.
    if shared and (set(a)<=set(b) or set(b)<=set(a)) and (len(shared)>=2 or (len(set(a))==len(set(b))==1 and any(len(w)>=4 for w in shared))):
        return 'brand_variant','Shared distinctive name: '+' '.join(w for w in a if w in shared)
    aa=' '.join(a);bb=' '.join(b)
    if a and b and len(a)==len(b) and min(len(aa),len(bb))>=6 and SequenceMatcher(None,aa,bb).ratio()>=0.88:
        return 'brand_variant','Similar distinctive name spelling: '+aa+' / '+bb
    return '', ''


def match_profile(profile,name,website,phones,location=''):
    reasons=[]
    if identity_domain(profile.get('website','')) and identity_domain(profile['website'])==identity_domain(website): reasons.append('domain')
    number=phone(profile.get('phone',''))
    if number and number in phones: reasons.append('phone')
    relation,explanation=name_connection(profile,name,location)
    return {'match_status':'identifier_match' if reasons else 'name_only' if relation else 'unresolved_candidate',
            'matched_by':reasons,'name_matches':relation=='exact_name',
            'name_match_kind':relation,'name_match_reason':explanation}


def identity_domain(url):
    host=domain(url)
    return '' if host in {'sites.google.com','facebook.com','instagram.com','linkedin.com','linktr.ee','wixsite.com','wordpress.com','business.site'} else host


def relevant_profiles(result,business=None,location=''):
    """Keep unrelated hits as search audit evidence, not business connections."""
    candidates={p['key']:p for p in result.get('excluded_profiles',[])}
    candidates.update({p['key']:p for p in result.get('profiles',[])})
    excluded={}
    kept=[]
    for p in candidates.values():
        if business and p.get('match_status') not in ('identifier_match','website_reference'):
            p.update(match_profile(p,business['name'],'',set(),location))
        if p.get('match_status') in ('identifier_match','website_reference','name_only'):
            kept.append(p)
        else:
            excluded[p['key']]=p
    result['profiles']=kept
    result['excluded_profiles']=list(excluded.values())
    result['summary']=summary(result)
    return result


def name_query(name,location=''):
    return ' '.join(x for x in ('"'+name.replace('"','').strip()+'"',location.strip()) if x)

def summary(result):
    def stable(p): return p.get('identity_source') not in ('unresolved','share_link')
    matches=[p for p in result['profiles'] if p['match_status']=='identifier_match' and stable(p)]
    ambiguous=[p for p in result['profiles'] if p['match_status']=='identifier_match' and not stable(p)]
    count=len(matches)
    linked=[p for p in result['profiles'] if p['match_status']=='website_reference' and stable(p)]
    others=[p for p in result['profiles'] if p not in matches and p not in ambiguous]
    def same_details(a,b):
        name=lambda p:re.sub(r'[^a-z0-9]','',p.get('name','').lower())
        return bool(name(a) and name(a)==name(b) and domain(a.get('website','')) and
            domain(a['website'])==domain(b.get('website','')) and phone(a.get('phone','')) and
            phone(a['phone'])==phone(b.get('phone','')))
    if count==1:
        if others or any(not same_details(p,matches[0]) for p in ambiguous):
            return '1 GBP confirmed. Additional candidates need review.'
        return '1 GBP confirmed. No distinct additional profiles identified.'
    if count>1:
        text=f'{count} GBP identifier matches. Branch/location legitimacy not verified.'
        if others:text+=f' {len(others)} separate candidate(s) not matched.'
        return text
    if linked:return f'{len(linked)} GBP reference(s) found on the website. Live verification pending.'
    if ambiguous:return 'Matching GBP results found. Listing identity unresolved.'
    if others:return f'{len(others)} possible name connection(s). No identifier match confirmed.'
    return 'No GBP confirmed. Collection was inconclusive.'

def search_maps(query, limit, report, cancelled, capture):
    """Run one real query; never convert a layout/access failure to zero results."""
    from playwright.sync_api import sync_playwright
    import os
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(s.DATA/'browser')
    result={'query':query,'status':'failed','profiles':[],'capture_ids':[],
            'started_at':s.now(),'search_url':'https://www.google.com/maps/search/'+quote(query,safe='')+'?hl=en',
            'limit':limit,'error':''}
    if domain(query) in ('google.com','maps.google.com') and '/maps' in urlsplit(query).path:
        result['search_url']=normalize_url(query)
    browser=None; deadline=time.monotonic()+150
    try:
        with sync_playwright() as playwright:
            browser=browser_launch(playwright,headless=True)
            context=browser.new_context(locale='en-US',viewport={'width':1280,'height':900},accept_downloads=False,service_workers='block')
            validated=set()
            def gate(route):
                parts=urlsplit(route.request.url);host=(parts.hostname or '').lower()
                if parts.scheme not in ('http','https') or not any(host==d or host.endswith('.'+d) for d in ('google.com','gstatic.com','googleapis.com','googleusercontent.com','ggpht.com','maps.app.goo.gl')):
                    route.abort();return
                try:
                    if host not in validated: public_addresses(host,parts.port or (443 if parts.scheme=='https' else 80));validated.add(host)
                except Exception: route.abort();return
                route.continue_()
            context.route('**/*',gate)
            page=context.new_page();page.set_default_timeout(5000)
            def blocked(text):
                return any(x in text.lower() for x in ('unusual traffic','verify you are human','before you continue to google','our systems have detected','access denied'))
            def save(kind):
                body=page.locator('body').inner_text(timeout=5000)
                cid=capture(page.url,page.title(),body,page.content().encode(),kind)
                result['capture_ids'].append(cid)
                return body,cid
            try:
                report('Maps search: '+query)
                page.goto(result['search_url'],wait_until='domcontentloaded',timeout=35000)
                page.wait_for_timeout(3000)
                text=page.locator('body').inner_text()
                if blocked(text):
                    save('maps_search');result.update(status='blocked',error='Consent, CAPTCHA, or access gate; collection stopped.');return result
                links={};ended=False;direct=False
                for _ in range(10):
                    if cancelled(): result['status']='cancelled';break
                    if time.monotonic()>deadline: break
                    for item in page.locator('a[href*="/maps/place/"]').evaluate_all('(els)=>els.map(e=>({url:e.href,name:e.getAttribute("aria-label")||e.textContent||""}))'):
                        if item['url'].startswith('https://www.google.com/maps/place/'):
                            links.setdefault(profile_key(item['url']),item)
                    text=page.locator('body').inner_text()
                    ended=bool(re.search(r"you.ve reached the end|no results found|couldn.t find|can.t find",text,re.I))
                    if page.locator('h1').count() and page.locator('[data-item-id="authority"], [data-item-id^="phone:"]').count() and not page.locator('[role="feed"]').count():
                        links={profile_key(page.url):{'url':page.url,'name':page.locator('h1').first.inner_text()}};direct=True;break
                    if ended or len(links)>=limit: break
                    feed=page.locator('[role="feed"]').first
                    if not feed.count(): break
                    feed.evaluate('(e)=>e.scrollBy(0,1600)');page.wait_for_timeout(1200)
                _,search_capture=save('maps_search')
                result['result_links']=list(links.values())
                if result['status']=='cancelled': return result
                if not links:
                    if ended: result.update(status='complete',error='No profiles returned by this search.')
                    else: result.update(status='failed',error='No readable results and no explicit empty-results message; source layout or loading failure.')
                    return result
                result['status']='complete' if (ended and len(links)<=limit) or direct else 'limited'
                failures=0
                for item in list(links.values())[:limit]:
                    if cancelled(): result['status']='cancelled';break
                    if time.monotonic()>deadline: result['status']='limited';break
                    try:
                        if page.url!=item['url']:
                            page.goto(item['url'],wait_until='domcontentloaded',timeout=25000);page.wait_for_timeout(1800)
                        text=page.locator('body').inner_text()
                        if blocked(text): result.update(status='blocked',error='Access gate while reading profile details.');break
                        header=page.locator('h1').first
                        if not header.count(): raise ValueError('No readable profile heading')
                        website_el=page.locator('a[data-item-id="authority"]').first
                        website=website_el.get_attribute('href') if website_el.count() else ''
                        if website and domain(website).endswith('google.com'):
                            args=parse_qs(urlsplit(website).query);website=(args.get('q') or args.get('url') or [''])[0]
                        try: website=normalize_url(website) if website else ''
                        except ValueError: website=''
                        phone_el=page.locator('[data-item-id^="phone:"]').first
                        phone_text=phone_el.get_attribute('aria-label') if phone_el.count() else ''
                        addr=page.locator('[data-item-id="address"]').first
                        address=addr.get_attribute('aria-label') if addr.count() else ''
                        name=header.inner_text().strip()
                        canonical=page.url;identity='url'
                        if '/maps/place/' not in canonical and not parse_qs(urlsplit(canonical).query).get('cid'):
                            share=page.get_by_role('button',name='Share',exact=True)
                            if share.count():
                                share.click()
                                try: page.wait_for_function('()=>Array.from(document.querySelectorAll("input")).some(e=>e.value.startsWith("https://maps.app.goo.gl/")||e.value.startsWith("https://www.google.com/maps"))',timeout=6000)
                                except Exception: pass
                                share_values=page.locator('input').evaluate_all('(els)=>els.map(e=>e.value).filter(v=>v.startsWith("https://maps.app.goo.gl/")||v.startsWith("https://www.google.com/maps"))')
                                if share_values:
                                    canonical=share_values[0];identity='share_link'
                                    resolver=context.new_page()
                                    try:
                                        resolver.goto(canonical,wait_until='domcontentloaded',timeout=20000)
                                        resolver.wait_for_url(re.compile(r'https://(?:(?:www|maps)\.)?google\.com/maps(?:/place/|\?.*cid=)'),timeout=12000)
                                    except Exception as exc:
                                        result['identity_resolution_note']=str(exc).splitlines()[0][:150]
                                    finally:
                                        resolved=resolver.url
                                        if domain(resolved) in ('google.com','maps.google.com') and ('/maps/place/' in resolved or parse_qs(urlsplit(resolved).query).get('cid')):
                                            canonical=resolved;identity='resolved_share_link'
                                            try:
                                                identity_capture=capture(resolved,resolver.title(),resolver.locator('body').inner_text(),resolver.content().encode(),'maps_profile_identity')
                                                result['capture_ids'].append(identity_capture)
                                            except Exception: pass
                                        else: result['unresolved_share_destination']=resolved
                                        resolver.close()
                                page.keyboard.press('Escape')
                        if '/maps/search/' in canonical: identity='unresolved'
                        _,cid=save('maps_profile')
                        result['profiles'].append({'key':profile_key(canonical),'profile_url':canonical,'name':name,'identity_source':identity,
                            'website':website,'phone':re.sub(r'^Phone:\s*','',phone_text or ''),
                            'address':re.sub(r'^Address:\s*','',address or ''),
                            'address_state':'displayed' if address else 'not_observed',
                            'capture_id':cid,'observed_at':s.now(),'search_capture_id':search_capture})
                        if identity in ('unresolved','share_link'):
                            result['status']='partial';result['error']='Profile read, but a stable listing identifier could not be resolved.'
                    except Exception as exc:
                        failures+=1;result['error']=str(exc).splitlines()[0][:250]
                if failures and result['status']=='complete': result['status']='partial'
                if not result['profiles'] and result['status'] not in ('cancelled','blocked'): result['status']='failed'
                return result
            finally:
                context.close();browser.close()
    except Exception as exc:
        result.update(status='failed',error=str(exc).splitlines()[0][:350]);return result
    finally:
        result['finished_at']=s.now()

def website_aliases(raw,source_url,capture_id):
    """Publisher-provided site names are search leads, never identity proof."""
    from bs4 import BeautifulSoup
    soup=BeautifulSoup(raw,'html.parser')
    names=[m.get('content','') for m in soup.select('meta[property="og:site_name"]')]
    # Page titles frequently contain slogans, locations and navigation labels.
    # Only explicit site-name metadata is eligible as an alias source.
    return [{'name':n.strip(),'source_url':source_url,'capture_id':capture_id}
            for n in dict.fromkeys(names) if usable_alias(n)]


def usable_alias(name):
    words=set(re.findall(r'[a-z0-9]+',name.lower()))
    generic=set('best local seo digital marketing agency company services service home page about us contact all of united states usa california ca ai search website web design in the and areas we serve'.split())
    return 3<=len(name.strip())<=90 and bool(words-generic) and not re.search(r'https?://|\$|off first|,\s*[A-Z]{2}\b',name)

def network_view(profiles,business,root_phones=()):
    """Show exact identifier edges without merging distinct profile IDs or claiming branches."""
    linked=[p for p in profiles if p.get('match_status')=='identifier_match' and p.get('identity_source') not in ('unresolved','share_link')]
    edges=[]
    for p in linked:
        if domain(p.get('website',''))==domain(business.get('website','')) and domain(business.get('website','')):
            edges.append({'from':'business','to':p['key'],'kind':'domain','value':domain(p['website']),'capture_id':p['capture_id']})
        if phone(p.get('phone','')) in root_phones:
            edges.append({'from':'business','to':p['key'],'kind':'phone','value':phone(p['phone']),'capture_id':p['capture_id']})
    for i,a in enumerate(linked):
        for b in linked[i+1:]:
            for kind,value in [('phone',phone(a.get('phone',''))),('domain',domain(a.get('website','')))]:
                other=phone(b.get('phone','')) if kind=='phone' else domain(b.get('website',''))
                if value and value==other:edges.append({'from':a['key'],'to':b['key'],'kind':kind,'value':value,'capture_ids':[a['capture_id'],b['capture_id']]})
    names={p.get('name','').strip().casefold() for p in linked}
    numbers={phone(p.get('phone','')) for p in linked}-{''}
    return {'profile_count':len(linked),'name_count':len(names),'phone_count':len(numbers),'edges':edges,
            'summary':f'{len(linked)} connected profiles · {len(names)} names · {len(numbers)} phone numbers',
            'meaning':'Shared identifiers connect these profiles. Each claimed location still needs its own evidence.'}

def investigate(business,identifiers,report,cancelled,capture,search=search_maps,seeds=None,aliases=None,max_searches=12,location=''):
    phones={x['value'] for x in identifiers if x['kind']=='phone' and x['role']=='displayed_contact'}
    number=phone(business.get('phone',''))
    if number:phones.add(number)
    root_phones=set(phones)
    result={'profiles':[],'searches':[],'started_at':s.now(),'matching_version':'1.1','alias_sources':aliases or [],
            'limits':f'Up to {max_searches} searches and 12 profiles per search; follows connected names and phones. Name-only candidates are not confirmed connections.'}
    queue=[('website_reference',p['profile_url']) for p in (seeds or [])[:2]]
    if business.get('profile_url'):queue.insert(0,('discovered_profile',business['profile_url']))
    queue.extend([('name',name_query(business['name'],location)),('domain',identity_domain(business['website']))])
    core=' '.join(brand_tokens(business['name'],location))
    if core and name_tokens(core)!=name_tokens(business['name']):
        queue.append(('brand_name',name_query(core)))
    queue.extend(('phone',number) for number in sorted(phones)[:3])
    queue.extend(('website_name',name_query(a['name'],location)) for a in (aliases or [])[:4] if usable_alias(a['name']))
    seen=set();profiles={p['key']:{**p,'capture_ids':list(p['capture_ids']),'queries':[]} for p in (seeds or [])[:2]}
    stop_reason='Search budget reached or investigation cancelled.'
    expanded=set()
    while queue and len(seen)<max_searches:
        kind,query=queue.pop(0)
        if not query or query.casefold() in {q.casefold() for _,q in seen}: continue
        if cancelled(): break
        seen.add((kind,query))
        outcome=search(query,12,report,cancelled,capture);outcome['kind']=kind
        result['searches'].append(outcome)
        for profile in outcome['profiles']:
            evidence=match_profile(profile,business['name'],business['website'],phones,location)
            key=profile_key(profile['profile_url']) if profile['key'].startswith('cid:') else profile['key']
            if key not in profiles: profiles[key]={**profile,**evidence,'queries':[],'capture_ids':[]}
            stored=profiles[key];stored['queries'].append({'kind':kind,'query':query})
            if stored.get('identity_source') in ('website_embed','website_link') and profile.get('identity_source') not in ('unresolved','share_link'):
                references={k:stored[k] for k in ('queries','capture_ids','embedded_url','source_url') if k in stored}
                stored.update(profile);stored.update(evidence);stored.update(references)
            stored['capture_ids'].append(profile['capture_id'])
            stored['matched_by']=sorted(set(stored['matched_by']+evidence['matched_by']))
            if any(x in stored['matched_by'] for x in ('domain','phone')): stored['match_status']='identifier_match'
            # Only use numbers from an identifier-matched profile for expansion.
            number=phone(profile.get('phone',''))
            if evidence['match_status']=='identifier_match' and number and number not in phones:
                phones.add(number);queue.append(('phone',number))
            # Follow alternate names only after a shared identifier connects the profile.
            # Revisit earlier candidates when a newly found number connects them.
        changed=True
        while changed:
            changed=False
            for p in profiles.values():
                evidence=match_profile(p,business['name'],business['website'],phones,location)
                if evidence['match_status']!='identifier_match':continue
                if p.get('identity_source') in ('website_embed','website_link'):continue
                p.update(evidence)
                number=phone(p.get('phone',''))
                if number and number not in phones:
                    phones.add(number);queue.append(('phone',number));changed=True
                if p['key'] not in expanded:
                    expanded.add(p['key'])
                    if p.get('name') and p['name'].casefold()!=business['name'].casefold():
                        queue.append(('connected_name',name_query(p['name'],p.get('address') or location)))
        if outcome['status']=='blocked':
            stop_reason='Not searched: Maps displayed an access gate. Further Maps collection stopped.'
            break
    for kind,query in queue:
        if query.casefold() not in {q.casefold() for _,q in seen}:
            seen.add((kind,query))
            result['searches'].append({'kind':kind,'query':query,'status':'not_searched','profiles':[],'capture_ids':[],'error':stop_reason})
    for item in profiles.values():
        # A profile's own newly discovered number is not corroboration of itself.
        other_phones=root_phones | {phone(p.get('phone','')) for p in profiles.values()
            if p['key']!=item['key'] and p.get('match_status')=='identifier_match'
            and p.get('identity_source') not in ('unresolved','share_link')}
        current=match_profile(item,business['name'],business['website'],other_phones,location)
        if item.get('identity_source') not in ('website_embed','website_link'):item.update(current)
    result['profiles']=list(profiles.values())
    result['network']=network_view(result['profiles'],business,root_phones)
    if not any(q['kind']=='phone' for q in result['searches']):
        result['searches'].append({'kind':'phone','query':'','status':'not_searched','profiles':[],
            'capture_ids':[],'error':'No usable business phone was collected, or the search budget/cancellation prevented a phone search.'})
    if cancelled(): result['status']='cancelled'
    else: result['status']='complete' if result['searches'] and all(q['status']=='complete' for q in result['searches']) else 'incomplete'
    result['finished_at']=s.now()
    return relevant_profiles(result)
