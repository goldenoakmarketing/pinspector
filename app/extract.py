"""Deterministic, deliberately narrow observations. Never a fraud verdict."""
from __future__ import annotations
import json
import re
from urllib.parse import urljoin,urlsplit
from bs4 import BeautifulSoup

RULE_VERSION='2026-09-14.1'

def clean(s): return re.sub(r'\s+',' ',str(s)).strip()

def phone(value):
    value=re.split(r'(?:ext\.?|extension|\bx\b|;ext=)',value,flags=re.I)[0]
    n=re.sub(r'\D','',value)
    if len(n)==11 and n.startswith('1'): n=n[1:]
    if len(n)!=10 or n[0] not in '23456789' or n[3] not in '23456789': return None
    return '+1'+n

PHONE_RE=re.compile(r'(?<!\w)(?:\+?1[ .-]?)?\(?[2-9]\d{2}\)?[ .-]?[2-9]\d{2}[ .-]?\d{4}(?:\s*(?:ext\.?|x)\s*\d{1,6})?(?!\d)',re.I)
LICENSE_RE=re.compile(r'\b(?:CSLB(?:\s+licen[sc]e)?|(?:contractor[’\x27]?s?\s+)?licen[sc]e(?:\s*(?:no\.?|number))?|lic\.)\s*(?:#|:)?\s*(\d{5,9})\b',re.I)
LEGAL_RE=re.compile(r'terms|privacy|disclaimer|legal|contact|about|team|staff|people|locations?|licens|service.area|faq|portfolio|case.stud|results|projects|our.work|clients|services',re.I)
THIRD_RE=re.compile(r'website (?:by|design)|designed by|powered by|web design|privacy (?:officer|contact)',re.I)

# Match explicit first-person statements, not arbitrary third-party mentions.
ROLE_PATTERNS=[
  (r'\bwe\s+(?:are|operate as)\s+(?:an?\s+)?(?:independent\s+)?(?:lead[- ]generation|referral|matching|lead[- ]selling)\s+(?:service|company|business|platform|website|network)', 'Explicit intermediary-business disclosure'),
  (r'\bwe\s+(?:do not|don[’\x27]t)\s+(?:directly\s+)?(?:perform|provide|carry out)\s+(?:(?:any|the|actual|advertised|plumbing|roofing|electrical|construction|contracting|repair|installation)\s+){0,4}(?:services|work)\b', 'Operator says it does not perform the work'),
  (r'\bwe\s+(?:sell|distribute)\s+(?:customer\s+|consumer\s+)?(?:leads|inquiries|enquiries)\s+to\b', 'Lead-distribution disclosure'),
  (r'\bwe\s+(?:connect|match)\s+(?:customers|consumers|homeowners|you)\s+with\s+(?:local\s+)?(?:independent|third[- ]party)\s+(?:contractors|service providers|professionals)', 'Independent-provider referral disclosure'),
]
LOCATION_PATTERNS=[
  (r'\b(?:this (?:address|location|office)|the address(?: above| below)?|our address)\s+is\s+(?:for\s+)?(?:correspondence|mail(?:ing)?)\s+only\b', 'Address described as correspondence-only'),
  (r'\bwe\s+(?:do not|don[’\x27]t)\s+(?:receive|serve|accept|see)\s+(?:customers|clients|visitors)\s+(?:at|in)\s+(?:this|our|the)\s+(?:location|address|office|premises)', 'No customer reception at stated location'),
  (r'\bwe\s+(?:do not|don[’\x27]t)\s+(?:have|maintain|operate)\s+(?:a|an|any)\s+(?:physical\s+|local\s+)?office\s+in\b', 'No local office statement'),
]
NEGATIVE_CONTEXT=re.compile(r'\b(?:example|sample|hypothetical|quote|quoted|beware|avoid companies|some companies|other companies)\b',re.I)


def parse_page(html: str, url: str) -> dict:
    soup=BeautifulSoup(html,'html.parser')
    title=clean(soup.title.get_text(' ',strip=True)) if soup.title else urlsplit(url).hostname or url
    structured=[]
    for script in soup.find_all('script',attrs={'type':'application/ld+json'}):
        try: structured.append(json.loads(script.string or script.get_text()))
        except (ValueError,TypeError): pass
    links=[]; tel=[]
    for a in soup.find_all('a',href=True):
        href=a['href']; label=clean(a.get_text(' ',strip=True))
        if href.lower().startswith('tel:'):
            n=phone(href[4:]); context=clean(a.parent.get_text(' ',strip=True))[:650]
            if n: tel.append((n,context))
        elif href.startswith(('http://','https://','/','?','#')) or not urlsplit(href).scheme:
            target=urljoin(url,href).split('#')[0]
            if urlsplit(target).scheme in ('http','https') and LEGAL_RE.search(label+' '+target):
                links.append({'url':target,'label':label})
    for tag in soup(['script','style','noscript','template','svg','iframe']): tag.decompose()
    for tag in soup.select('blockquote,q,pre,code'): tag.decompose()
    # Preserve inline wording (e.g. 'a <strong>referral</strong> service')
    # while retaining block boundaries and footer attribution context.
    marker='\u241e'
    for block in list(soup.find_all(['p','div','section','article','header','footer','li','h1','h2','h3','h4','br','tr'])):
        block.insert_before(marker)
        block.insert_after(marker)
    text='\n'.join(clean(line) for line in soup.get_text(' ',strip=True).split(marker) if clean(line))
    # Join wrapped text while retaining a paragraph/line-oriented source representation.
    paragraphs=[clean(x) for x in re.split(r'\n+',text) if clean(x)]
    identifiers=[]; seen=set()
    for n,ctx in tel:
        role='third_party' if THIRD_RE.search(ctx) else 'displayed_contact'
        if (n,role) not in seen:
            identifiers.append({'kind':'phone','value':n,'role':role,'context':ctx}); seen.add((n,role))
    for line in paragraphs:
        for m in PHONE_RE.finditer(line):
            n=phone(m.group())
            role='third_party' if THIRD_RE.search(line) else 'displayed_contact'
            if n and (n,role) not in seen:
                identifiers.append({'kind':'phone','value':n,'role':role,'context':line[:650]}); seen.add((n,role))
        for m in LICENSE_RE.finditer(line):
            key=(m.group(1),'license')
            if key not in seen:
                role='third_party' if re.search(r'participating contractors|contractor directory|partner[s’\x27]* licen',line,re.I) else 'claimed_license'
                identifiers.append({'kind':'license','value':m.group(1),'role':role,'context':line[:650]}); seen.add(key)
    return {'title':title,'text':text,'links':list({x['url']:x for x in links}.values()),'identifiers':identifiers,'structured_data':structured}


def observations(text: str) -> list[dict]:
    out=[]; seen=set()
    for line in text.splitlines():
        # Sentences keep generic privacy boilerplate separate from explicit statements.
        for sentence in re.split(r'(?<=[.!?])\s+(?=[A-Z])',clean(line)):
            if len(sentence)<12 or NEGATIVE_CONTEXT.search(sentence): continue
            for dimension,patterns in (('business_role',ROLE_PATTERNS),('location',LOCATION_PATTERNS)):
                for i,(pattern,title) in enumerate(patterns):
                    if re.search(pattern,sentence,re.I):
                        key=(dimension,i,sentence)
                        if key in seen: continue
                        seen.add(key)
                        if dimension=='business_role':
                            explanation='The captured website contains this explicit first-person disclosure. Confirm that it describes the operator and the specific listing under review; it does not itself establish fraud or a GBP violation.'
                        else:
                            explanation='The captured site contains an address/office-role statement. Its exact branch and address scope must be matched by a reviewer. No automatic conclusion about a public pin or location eligibility is made.'
                        out.append({'dimension':dimension,'rule':f'{RULE_VERSION}:{dimension}:{i+1}',
                          'strength':'direct_statement','title':title,'explanation':explanation,'quote':sentence[:1800]})
    return out


def validate_model_proposal(result: dict, text: str) -> dict | None:
    if not isinstance(result,dict): return None
    label=result.get('classification'); quote=clean(result.get('quote',''))
    if label not in ('referral_or_lead_generation','service_provider','location_review','unclear'): return None
    if label=='unclear' or not 20<=len(quote)<=900: return None
    if quote not in clean(text): return None
    if NEGATIVE_CONTEXT.search(quote): return None
    reason=clean(result.get('reason',''))[:1200]
    if not reason: return None
    return {'classification':label,'quote':quote,'reason':reason}
