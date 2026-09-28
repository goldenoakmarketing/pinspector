"""Source-linked site relationships. Heuristic patterns are not verified ownership."""
import json
import re
from urllib.parse import urljoin, urlsplit
from bs4 import BeautifulSoup
from .gbp import domain
from . import storage as s

SOCIAL={'facebook.com','instagram.com','linkedin.com','youtube.com','tiktok.com','x.com','twitter.com'}
PLATFORMS=SOCIAL|{'google.com','yelp.com','bbb.org','schema.org','wordpress.org','duda.co','godaddy.com'}
TRADE=re.compile(r'\b(?:insulation|roofing|roofer|hvac|heating|cooling|plumb\w*|concrete|landscap\w*|artificial grass|tree service|electrician|pest control|spray foam|attic|furnace|ac repair)\b',re.I)
def platform(host,hosts):return any(host==x or host.endswith('.'+x) for x in hosts)

def links(raw,url):
    soup=BeautifulSoup(raw,'html.parser');out=[]
    for a in soup.select('a[href]'):
        target=urljoin(url,a['href']).split('#')[0];host=domain(target)
        if urlsplit(target).scheme not in ('http','https') or not host:continue
        label=a.get_text(' ',strip=True)
        context=a.parent.get_text(' ',strip=True)[:900]
        out.append({'url':target,'domain':host,'anchor':label,'context':context})
    return out

def analyze(business,captures):
    own=domain(business.get('website',''));latest={}
    for c in captures:
        if c.get('business_id',business['id'])==business['id'] and c.get('source_type') in ('website','external_page'):
            latest[(c['final_url'],c['source_type'])]=c
    result={'signals':[],'social_profiles':[],'staff':[],'outbound_links':[],'link_paths':[]}
    result['naming_context']='Service/Pros branding is a search clue, not evidence of a referral role.' if re.search(r'\bpros\b',business.get('name',''),re.I) else ''
    graph={};seen=set()
    def add(kind,quote,c,**extra):
        key=(kind,quote)
        if key in seen:return
        seen.add(key);result['signals'].append({'kind':kind,'quote':quote,'capture_id':c['id'],'url':c['final_url'],**extra})
    for c in latest.values():
        try:raw=(s.DATA/c['artifact']).read_bytes()
        except (OSError,KeyError):continue
        host=domain(c['final_url']);first=c['source_type']=='website' and host==own
        soup=BeautifulSoup(raw,'html.parser')
        for item in links(raw,c['final_url']):
            if item['domain']==host:continue
            edge={**item,'from':host,'capture_id':c['id'],'source_url':c['final_url']}
            if not platform(item['domain'],PLATFORMS):graph.setdefault(host,[]).append(edge)
            if not first:continue
            if platform(item['domain'],SOCIAL) and not re.search(r'sharer|share\?|intent/|/share/',item['url'],re.I):
                if not any(x['url']==item['url'] for x in result['social_profiles']):result['social_profiles'].append({**item,'capture_id':c['id'],'scope':'Linked by the business website; profile identity not independently verified.'})
            elif not platform(item['domain'],PLATFORMS):
                if not any(x['url']==item['url'] for x in result['outbound_links']):result['outbound_links'].append(edge)
        if not first:continue
        text=c.get('text',soup.get_text(' ',strip=True))
        partner=re.search(r'In Partnership with[^\n]{1,180}\s*\n[^\n]{1,140}#\s*\d{5,9}',text,re.I)
        if partner:add('partner_number',partner.group(),c,scope='Number published under the named partner; not verified or attributed to the website operator.')
        for line in text.splitlines():
            person=re.search(r'\b(?:Owner|Founder|President|Manager|Meet)\s*[:–—-]?\s+([A-Z][a-z]+(?:\s+[A-Z][a-z]+){1,3})\b',line)
            if person and len(line)<600 and not re.search(r'\b(?:review|testimonial|customer)\b',line,re.I):
                result['staff'].append({'name':person.group(1),'role':line,'capture_id':c['id'],'url':c['final_url'],'scope':'Website-published person/role claim; identity unverified.'})
            if re.search(r'\b(?:in partnership with|operated by|services (?:are )?(?:provided|performed) by)\b',line,re.I):add('operator_relationship',line[:900],c)
            if re.search(r'["“”]|\b(?:example|hypothetical|some companies|other companies|said|says|quoted|testimonial)\b',line,re.I):continue
            if re.search(r'\bwe\s+(?:connect|match)\s+(?:you|homeowners|customers|consumers)\s+with\s+(?:(?:local|independent|qualified|participating|third-party)\s+){0,3}(?:professionals|contractors|providers)',line,re.I):add('provider_matching',line[:900],c)
            if re.search(r'\b(?:we|this (?:site|website))\s+(?:may\s+|will\s+)?(?:share|sell|distribute|forward)\s+.{0,70}\b(?:inquir\w*|request\w*|contact details|information|leads)\b.{0,60}\b(?:with|to)\s+.{0,40}\b(?:marketing partners|contractors|service providers|participating providers)\b',line,re.I) and not re.search(r'\b(?:not|never)\b',line,re.I):add('inquiry_routing',line[:900],c)
            if re.search(r'\b(?:all (?:projects|work|services)|services|work)\s+(?:are|is)\s+(?:performed|provided|fulfilled)\s+by\s+(?:independent|third.party|participating)\s+(?:contractors|providers|businesses)',line,re.I):add('third_party_delivery',line[:900],c)
        # Explicit structured staff attribution only; reviews and arbitrary names are excluded.
        def walk(obj,role='',depth=0):
            if depth>32:return
            if isinstance(obj,list):
                for x in obj:walk(x,role,depth+1)
            elif isinstance(obj,dict):
                if role in ('employee','founder','founders') and obj.get('name') and obj.get('@type')=='Person':
                    item={'name':str(obj['name'])[:150],'role':str(obj.get('jobTitle') or role)[:150],'capture_id':c['id'],'url':c['final_url'],'scope':'Website-published staff claim; identity not independently verified.'}
                    if item not in result['staff']:result['staff'].append(item)
                for k,v in obj.items():walk(v,k,depth+1)
        for node in soup.select('script[type="application/ld+json"]'):
            try:walk(json.loads(node.string or node.get_text()))
            except (ValueError,TypeError):pass
        for node in soup.select('[itemtype$="/Person"]'):
            name=node.select_one('[itemprop="name"]');role=node.select_one('[itemprop="jobTitle"]')
            if name and role:result['staff'].append({'name':name.get_text(' ',strip=True)[:150],'role':role.get_text(' ',strip=True)[:150],'capture_id':c['id'],'url':c['final_url'],'scope':'Website-published person and role; identity unverified.'})
    trade=[e for e in result['outbound_links'] if TRADE.search(e['anchor']) and not re.search(r'portfolio|our clients|case stud|powered by|designed by|manufacturer|supplier',e['context'],re.I)]
    if len({e['domain'] for e in trade})>=4:
        e=trade[0];result['signals'].append({'kind':'outbound_trade_cluster','quote':f'Service-keyword links point to {len({e["domain"] for e in trade})} external domains.','capture_id':e['capture_id'],'url':e['source_url'],'edges':trade,'scope':'Possible promotional link network; unrelated ownership or an exchange agreement is not established.'})
    # Only observed edges can close a path. Never infer a missing return link.
    steps=0
    def paths(node,visited,edges):
        nonlocal steps
        steps+=1
        if len(result['link_paths'])>=12 or steps>3000:return
        for edge in graph.get(node,[])[:80]:
            target=edge['domain']
            if target==own and len(edges)>=1:result['link_paths'].append(edges+[edge])
            elif target not in visited and len(edges)<5:paths(target,visited|{target},edges+[edge])
    if own:paths(own,{own},[])
    return result
