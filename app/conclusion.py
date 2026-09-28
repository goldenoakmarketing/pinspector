"""Combine source-bound interpretations with collected corroboration and coverage."""
import re
from .gbp import domain

SCOPE='Screening for lead-generation/intermediary roles and potentially false location claims. A real service business can still have a questionable location; service-delivery evidence does not validate its branches. A service-area business without a public street address is not suspicious for that reason. Legal-entity verification is outside scope. Missing data does not increase suspicion.'

def in_scope(check):
    return not check.get('check','').lower().startswith('legal entity')

def work_account(text):
    """Concrete customer work accounts; praise and estimates alone are insufficient."""
    if re.search(r'\b(?:fake|scam|fraud)\b',text,re.I):return False
    work=r'\b(?:built|designed|installed|installing|installation|repaired|replaced|replacement|completed|performed|delivered|cleaned|cleaning|sealed|removed|sanitized|inspected|rodent.proofed|exterminated|finished|air seal|workmanship)\b'
    for sentence in re.split(r'[.!?\n]+',text):
        if re.search(r'\bhappy\b.{0,25}\bchose\b.{0,45}\bto (?:design|build) my\b',sentence,re.I):return True
        if re.search(work,sentence,re.I) and not re.search(r"\b(?:never|not|didn.t|wasn.t|wouldn.t|failed to|refused to)\b.{0,45}"+work,sentence,re.I):
            if not re.search(r'\b(?:need|needs|needed|plan|planning|estimate|quote|hoping|want|wanted)\b',sentence,re.I):return True
        if re.search(r'\b(?:crew|team|installer)\b.{0,35}\barrived\b|\bjob\b.{0,25}\bdone\b',sentence,re.I) and not re.search(r'\b(?:never|not|didn.t)\b',sentence,re.I):return True
        if re.search(r'\bactual inspection\b.{0,70}\bwrap.up of the project\b',sentence,re.I):return True
        if re.search(r'\bdid\b.{0,30}\b(?:work|job)\b',sentence,re.I) and re.search(r'\b(?:insulation|roof|attic|duct|crawlspace|crawl space|installation|repair|cleaning|rodent.proofing)\b',text,re.I) and not re.search(r'\b(?:never|not|didn.t)\b',sentence,re.I):return True
    return False

def combine(assessment, external, discovery, relationships=None, disclosures=None):
    claims=assessment.get('claims',[]) if assessment.get('status')=='assessed' else []
    roles={c['interpretation'] for c in claims if c['dimension']=='business_role'}
    evidence=external.get('evidence',[])
    credits={domain(e['url']) for e in evidence if e['kind']=='work_credit'}
    # Captured work accounts must not disappear because a four-claim draft omitted them.
    # These remain customer claims, not authenticated transactions.
    reviews=list({e.get('quote','').strip().casefold():e for e in evidence if e['kind']=='customer_review' and e.get('capture_id') and work_account(e.get('quote',''))}.values())
    supporting=[]; concerns=[]
    if 'direct_provider' in roles:supporting.append('Captured statements describe the business performing services directly.')
    if credits:supporting.append(f'Published work attribution links back to this business on {len(credits)} external domain(s). Authorship is unverified.')
    if reviews:supporting.append(f'{len(reviews)} distinct customer review excerpts were captured on an identifier-matched profile; the accounts are not authenticated.')
    if 'intermediary' in roles:
        concerns.append('Captured statements describe an intermediary/referral role. This can be legitimate; whether that role is clearly disclosed matters.')
    if {'direct_provider','intermediary'}<=roles:
        label='Mixed service and referral roles'
        answer='The business describes both performing work and referring it to others.'
    elif 'intermediary' in roles:
        label='Likely lead-gen or referral operation'
        answer='The business describes referring or distributing customer inquiries.'
    elif ('direct_provider' in roles and (credits or reviews)) or len(reviews)>=2:
        label='Unlikely to be a disguised lead-gen operation'
        answer='Service claims are supported by '+('published client work credits' if credits else 'customer accounts describing work performed')+'.'
        if 'direct_provider' not in roles:answer='Multiple customer accounts describe work performed by the business.'
    elif 'direct_provider' in roles:
        label='Not enough evidence to assess lead-gen risk'
        answer='Only the business’s own service claims support direct delivery.'
    else:
        label='Not enough evidence to assess lead-gen risk'
        answer='No clear service-delivery or referral role was established.'
        customer_accounts=[e for e in evidence if e.get('kind')=='customer_review']
        if reviews:
            answer='One customer account describes work, but no clear operator-role evidence was established.'
        elif customer_accounts:
            answer='Captured reviews describe praise or inquiries without enough detail to establish who performs the work.'
        if not any(x.get('source_type')=='website' for x in assessment.get('sources',[])):
            answer+=' No usable website text was available to the assessment.'
    if label.startswith('Not enough') and assessment.get('status')=='failed':
        label='Analysis failed — retry needed'
        answer='The analysis could not be completed. This is an app failure, not a finding about the business.'
    elif label.startswith('Not enough') and assessment.get('status')=='unavailable':
        label='Analysis not run'
        answer='No model assessment is available for these sources.'
    gaps=[{'check':c['check'],'detail':c['detail']} for c in external.get('checks',[]) if in_scope(c) and c['status'] not in ('complete','not_triggered')]
    if not discovery or discovery.get('status')!='complete':gaps.append({'check':'GBP discovery','detail':'Profile searches were incomplete; absence of additional listings is not established.'})
    if assessment.get('status')!='assessed':gaps.append({'check':'Local reasoning','detail':assessment.get('error',assessment.get('conclusion','Assessment not run.'))})
    leads=relationships or []
    actionable=[x for x in leads if x['requires_review']]
    if actionable:
        concerns.extend(x['description']+' '+x['alternative_explanations'] for x in actionable)
        if any(x['kind']=='shared_identifier' for x in actionable) and label.startswith('Unlikely'):
            label='Service evidence found; identity conflicts need review'
    profile_network=discovery.get('network',{})
    network_note=''
    if profile_network.get('profile_count',0)>1 and profile_network.get('phone_count',0)>1:
        network_note='Multiple connected listings with different phone numbers. Each claimed location needs its own verification.'
        if label.startswith(('Unlikely','Not enough','Service evidence found')):
            label='Connected listings; lead-gen role unconfirmed'
            answer='Multiple connected listings with different phone numbers. Lead-generation role unconfirmed.'
    context=external.get('site_context',{})
    pattern=None
    kinds={x['kind'] for x in context.get('signals',[])}
    if 'outbound_trade_cluster' in kinds:
        concerns.append('Service-keyword links point to multiple external businesses; possible promotional link network. See the captured links and observed paths.')
        label='Possible lead-gen network — link pattern needs review'
        answer='The website links service keywords to multiple external business domains; this does not establish who performs the work.'
        if any(p.get('line_type') in ('voip','fixed_voip','non_fixed_voip') for p in context.get('phone_checks',[])):
            concerns.append('The saved phone lookup reports VoIP; its source and current-carrier limitations are retained below.')
    if 'provider_matching' in kinds and kinds & {'inquiry_routing','third_party_delivery'}:
        label='Likely lead-gen or referral operation'
        answer='The site describes matching customers with providers and routing inquiries or having third parties perform the work.'
        concerns.append('Multiple operator statements support a matching/referral role; exact passages are retained.')
    elif kinds & {'provider_matching','inquiry_routing','third_party_delivery'}:
        concerns.append('Provider-matching, inquiry-routing, or third-party delivery wording needs role attribution; ordinary subcontracting is also possible.')
        if label.startswith('Unlikely'):
            label='Provider relationship needs review'
            answer='Service evidence exists alongside wording about other providers; the operator’s role needs clarification.'
    partner=next((x for x in context.get('signals',[]) if x['kind']=='partner_number' and x.get('capture_id')),None)
    network=next((x for x in context.get('signals',[]) if x['kind']=='outbound_trade_cluster' and x.get('capture_id')),None)
    voip=next((p for p in context.get('phone_checks',[]) if p.get('line_type') in ('voip','fixed_voip','non_fixed_voip') and p.get('provider')=='Veriphone' and p.get('capture_id')),None)
    if partner and network and voip:
        label='Likely lead-gen or referral operation'
        answer='Partner contractor attribution, a promotional link pattern, and reported VoIP together suggest a marketing/referral operation.'
        pattern={'summary':answer,'reasons':[
            {'text':'The website publishes a partner business and its contractor number: '+partner['quote'],'capture_id':partner['capture_id']},
            {'text':network['quote'],'capture_id':network['capture_id']},
            {'text':'The phone lookup reports '+voip.get('carrier','an unspecified carrier')+' / VoIP for the original number assignment.','capture_id':voip['capture_id']}],
            'limit':'Strong combined indicators, not confirmed lead sales or unauthorized license use. The phone lookup does not verify the current carrier.'}
    explicit=disclosures or []
    if any(d['kind']=='referral' for d in explicit):
        label='Lead-gen / referral service — explicitly disclosed'
        answer='Its own terms or website describe a referral or matching service.'
        concerns.insert(0,'Explicit operator disclosure takes precedence over marketing claims and customer reviews.')
    elif explicit:
        label='Operator says it does not perform the work'
        answer='Direct-service claims conflict with an explicit non-performance statement.'
    return {'label':label,'answer':answer,'supporting':supporting,'concerns':concerns,'gaps':gaps,'relationship_signals':leads,
            'operator_disclosures':explicit,
            'site_context':context,
            'pattern_explanation':pattern,
            'location_summary':network_note or ('Identity/location evidence needs review.' if actionable else ''),
            'supporting_capture_ids':list(dict.fromkeys(e['capture_id'] for e in evidence if e in reviews or (e['kind']=='work_credit' and e.get('capture_id')))),
            'profile_summary':discovery.get('summary','GBP discovery has not completed.'),
            'scope':SCOPE}
