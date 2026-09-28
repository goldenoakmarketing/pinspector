"""Full-text, operator-attributed disclosures, independent of model excerpt limits."""
import re
from .gbp import domain

VERSION='1.0'

def collect(business,captures):
    own=domain(business.get('website',''))
    if not own:return []
    newest={}
    for cap in captures:
        if cap['business_id']==business['id'] and cap.get('source_type','website')=='website' and domain(cap['final_url'])==own:
            newest[cap['final_url']]=cap
    names=[r'we',r'this\s+(?:website|site|company|business)',r'our\s+(?:website|site|company|business)',r'the\s+(?:website|site)']
    name=business.get('name','').strip()
    if name:names.append(re.escape(name).replace(r'\ ',r'\s+'))
    subject=r'(?<!\w)(?:'+ '|'.join(names)+r')\s+'
    role=r'(?:is|are|operate(?:s)?\s+(?:solely\s+)?as|acts?\s+as)\s+(?:(?:a|an|the|free|independent|solely|only|online)\s+){0,4}'
    patterns=[('referral',re.compile(subject+role+r'(?:referral(?:\s+(?:directory|and))?|lead[- ](?:generation|matching|selling)|matching)(?:\s+(?:and|lead[- ]matching|matching|referral|directory)){0,4}\s+(?:service|platform|directory|network|business|company)\b',re.I)),
      ('nonperformance',re.compile(subject+r'(?:do(?:es)?\s+not|don[’\x27]t|doesn[’\x27]t)\s+(?:directly\s+)?(?:perform|provide|carry\s+out)\s+(?:(?:construction|insulation|home|improvement|roofing|plumbing|electrical|contracting|repair|installation|actual|advertised|any|the|or|and)\b[, ]*){0,12}(?:services|work)\b',re.I))]
    out=[];seen=set()
    for cap in newest.values():
        for sentence in re.split(r'(?<=[.!?])\s+|\n+',cap['text']):
            sentence=sentence.strip()
            if not sentence or re.search(r'\b(?:example|sample|hypothetical|quoted|beware|avoid companies|some companies|other companies)\b',sentence,re.I):continue
            for kind,pattern in patterns:
                match=pattern.search(sentence)
                if not match:continue
                # Reject statements attributed to a speaker/quotation, not the operator.
                prefix=sentence[:match.start()]
                if re.search(r'["“”]|\b(?:says?|said|wrote|claims?|claimed)\b',prefix,re.I):continue
                quote=sentence if len(sentence)<=700 else sentence[match.start():match.end()]
                if quote not in cap['text'] or (kind,quote) in seen:continue
                seen.add((kind,quote))
                out.append({'kind':kind,'quote':quote,'capture_id':cap['id'],'url':cap['final_url'],
                    'rule_version':VERSION,'observed_at':cap.get('observed_at','')})
    return out
