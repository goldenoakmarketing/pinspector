"""Source-linked screening leads, never inferred legal ownership or proven fraud."""
import re

EXPLANATIONS='Possible explanations include rebranding, franchises, a shared dispatch service, or an authorized shared license. These are hypotheses unless captured evidence establishes them.'

def name_key(value):return re.sub(r'[^a-z0-9]','',value.lower())

def cross_references(detail):
    """Readable, source-bound links; attribution is kept separate from identity."""
    from .gbp import domain
    from .extract import phone
    from difflib import SequenceMatcher
    businesses=detail.get('businesses',[]);out={b['id']:[] for b in businesses}
    captures={c['id']:c for c in detail.get('captures',[])}
    def add(bid,kind,text,refs,meaning):
        refs=list(dict.fromkeys(r for r in refs if r in captures))
        if not refs:return
        item={'kind':kind,'text':text,'meaning':meaning,'capture_ids':refs}
        if not any(x['kind']==kind and x['text']==text for x in out[bid]):out[bid].append(item)
    index={};partners=[]
    for i in detail.get('identifiers',[]):
        if i['kind'] not in ('phone','license') or i.get('capture_id') not in captures:continue
        cap=captures[i['capture_id']]
        if cap.get('source_type')!='website' or i['role'] in ('third_party','privacy_contact'):continue
        value=phone(i['value']) if i['kind']=='phone' else i['value']
        if value:index.setdefault((i['kind'],value),[]).append((i['business_id'],i['capture_id']))
    latest={}
    for a in detail.get('assessments',[]):latest.setdefault(a['business_id'],a['result'])
    for bid,a in latest.items():
        for sig in a.get('combined',{}).get('site_context',{}).get('signals',[]):
            if sig['kind']!='partner_number':continue
            number=re.search(r'#\s*(\d{5,9})',sig['quote'])
            if number:partners.append((bid,number.group(1),sig))
    for b in businesses:
        bid=b['id'];refs=[c['id'] for c in captures.values() if c.get('business_id')==bid and c.get('source_type')=='website']
        own_domain=domain(b.get('website',''))
        for other in businesses:
            if other['id']==bid:continue
            other_refs=[c['id'] for c in captures.values() if c.get('business_id')==other['id'] and c.get('source_type')=='website']
            if own_domain and own_domain==domain(other.get('website','')):
                add(bid,'domain',b['name']+' and '+other['name']+' both use '+own_domain+'.',refs[:1]+other_refs[:1],'Same website; location legitimacy is assessed separately.')
            # Distinctive first-name similarity creates a search lead, never a merge.
            first=lambda n:re.sub(r'[^a-z]','',n.lower().split()[0]) if n.split() else ''
            x,y=first(b['name']),first(other['name'])
            if min(len(x),len(y))>=5 and x!=y and SequenceMatcher(None,x,y).ratio()>=.85 and own_domain!=domain(other.get('website','')):
                add(bid,'similar_name',b['name']+' resembles '+other['name']+', but they use different websites ('+own_domain+' and '+domain(other.get('website',''))+').',refs[:1]+other_refs[:1],'Name similarity only; do not treat them as the same business.')
        for (kind,value),entries in index.items():
            if not any(owner==bid for owner,_ in entries):continue
            others=[o for o in businesses if o['id']!=bid and any(owner==o['id'] for owner,_ in entries)]
            for other in others:
                add(bid,kind,b['name']+' and '+other['name']+' both publish '+('license number ' if kind=='license' else 'phone number ')+value+'.',[cid for owner,cid in entries if owner in (bid,other['id'])],'Published identifier match; this does not establish ownership or authorization.')
        discovery=next((d['result'] for d in detail.get('profile_discoveries',[]) if d['business_id']==bid),{})
        for p in discovery.get('profiles',[]):
            if p.get('match_status')!='identifier_match' or p.get('identity_source') in ('unresolved','share_link'):continue
            if own_domain and domain(p.get('website',''))==own_domain:
                add(bid,'domain','Google profile “'+p['name']+'” links to '+own_domain+' and lists '+(p.get('phone','').strip() or 'no captured phone')+'.',[p.get('capture_id')],'Connected through the same website.')
            elif 'phone' in p.get('matched_by',[]):
                add(bid,'phone','Google profile “'+p['name']+'” uses a matching phone number, '+p.get('phone','').strip()+', but a different or uncaptured website.',[p.get('capture_id')],'Phone connection; this does not establish a shared owner.')
        for owner,number,sig in partners:
            matches=[o for o in businesses if o['id']!=owner and any(who==o['id'] for who,_ in index.get(('license',number),[]))]
            if bid==owner and not matches:
                add(bid,'partner_license',b['name']+' says “'+' '.join(sig['quote'].split())+'”.',[sig['capture_id']],
                    'The number is attributed to the named partner. No matching partner website has been captured in this scan.')
            for other in matches:
                if bid not in (owner,other['id']):continue
                publisher=next((o for o in businesses if o['id']==owner),None)
                if not publisher:continue
                add(bid,'partner_license',publisher['name']+' says “'+' '.join(sig['quote'].split())+'”. '+other['name']+' publishes the same license number, '+number+', on its own website.',[sig['capture_id']]+[cid for who,cid in index[('license',number)] if who==other['id']],
                    'This connects the marketing site to the named service partner. A paid lead-sale arrangement is inferred, not established by this wording alone.')
    return out

def signals(business,detail,discovery):
    out=[]; valid={c['id'] for c in detail.get('captures',[])}
    def add(kind,description,refs,review=True):
        refs=list(dict.fromkeys(r for r in refs if r in valid))
        if refs:out.append({'kind':kind,'description':description,'capture_ids':refs,'requires_review':review,
            'alternative_explanations':EXPLANATIONS if kind=='shared_identifier' else 'A mailing or non-customer-facing base may be normal for a service-area business. Match the statement to the exact claimed location and public representation before inferring a false location.'})
    network=discovery.get('network',{})
    if network.get('profile_count',0)>1 and (network.get('name_count',0)>1 or network.get('phone_count',0)>1):
        linked=[p for p in discovery.get('profiles',[]) if p.get('match_status')=='identifier_match' and p.get('identity_source') not in ('unresolved','share_link')]
        add('shared_identifier',network['summary']+'. Compare each profile’s published address and contact details; these are connected listings, not independent corroboration.',[p.get('capture_id') for p in linked])
    from .extract import phone
    website_ids={c['id'] for c in detail.get('captures',[]) if c.get('business_id')==business['id'] and c.get('source_type')=='website'}
    site_phones=[i for i in detail.get('identifiers',[]) if i['business_id']==business['id'] and i['kind']=='phone' and i['role']=='displayed_contact' and i.get('capture_id') in website_ids]
    reported=phone(business.get('phone',''))
    values={phone(i['value']) for i in site_phones}-{''}
    if reported and values and reported not in values:
        add('shared_identifier','Listing phone '+reported+' differs from website contact number(s): '+', '.join(sorted(values))+'. Tracking numbers, changed contact details, or a different operator are possible; the mismatch needs reconciliation.',[i['capture_id'] for i in site_phones])
    for connection in detail.get('connections',[]):
        if connection['kind'] not in ('phone','license'):continue
        refs=[x for x in connection['sources'] if x.get('role') not in ('third_party','privacy_contact') and x.get('capture_id') in valid]
        if not any(x['business_id']==business['id'] for x in refs):continue
        names=list(dict.fromkeys(x['name'] for x in refs))
        if len({name_key(n) for n in names})<2:continue
        add('shared_identifier',f'Differently named businesses share displayed {connection["kind"]} {connection["value"]}: '+', '.join(names),[x['capture_id'] for x in refs])
    seen=set()
    for profile in discovery.get('profiles',[]):
        if profile.get('match_status')!='identifier_match' or 'phone' not in profile.get('matched_by',[]):continue
        if profile.get('name_matches') is not False or not profile.get('name'):continue
        key=(name_key(profile['name']),profile.get('phone',''))
        if key in seen:continue
        seen.add(key)
        own_refs=[i['capture_id'] for i in detail.get('identifiers',[]) if i['business_id']==business['id'] and i['kind']=='phone' and i['role'] not in ('third_party','privacy_contact')]
        add('shared_identifier',f'Phone-matched profile uses a different name: {profile["name"]}; displayed phone {profile.get("phone", "")}. This is an identity-resolution lead, not proof of a duplicate or common ownership.',[profile.get('capture_id')]+own_refs)
    for finding in detail.get('findings',[]):
        if finding['business_id']!=business['id'] or finding['dimension']!='location' or finding['strength']!='direct_statement':continue
        # No customer reception is compatible with ordinary service-area operation.
        review='No customer reception' not in finding['title']
        add('location_statement',finding['title']+': '+finding['quote'],[finding['capture_id']],review)
    return out
