import copy
import httpx
import pytest
from app import reasoning as r

BUSINESS={'id':'business','name':'Example','website':'https://example.com'}
TEXT='Our team performs the roofing work directly for our customers.'
CAP={'id':'capture','business_id':'business','final_url':'https://example.com/about',
     'text':TEXT,'sha256':'abc','observed_at':'2026-09-14'}
SETTINGS={'kind':'ollama','model':'existing-7b','endpoint':'http://127.0.0.1:11434'}

def draft():
    return {'claims':[{'id':'one','dimension':'business_role','interpretation':'direct_provider',
             'statement':'The website describes direct roofing service delivery.',
             'capture_id':'capture','quote':TEXT,'limitation':'Website self-description; operation not independently verified.'}]}

def mock_passes(monkeypatch,first=None,second=None):
    proposed=copy.deepcopy(first or draft())
    for claim in proposed['claims']:
        claim.pop('quote',None);claim.pop('capture_id',None);claim['evidence_id']='E1'
    responses=iter([proposed,second if second is not None else {'accepted_ids':['one']}])
    monkeypatch.setattr(r,'complete',lambda *args:next(responses))

def test_positive_assessment_and_provenance(monkeypatch):
    mock_passes(monkeypatch)
    result=r.assess(BUSINESS,[CAP],SETTINGS)
    assert result['status']=='assessed'
    assert 'delivering services directly' in result['conclusion']
    assert result['sources'][0]['sha256']=='abc'
    assert result['constitution_sha256']==r.POLICY_HASH

@pytest.mark.parametrize('change',[{'quote':'This fabricated quotation does not occur in the source.'},
    {'capture_id':'another-business'},{'dimension':'license'},{'unexpected':'field'},
    {'limitation':'The quote does not explicitly support this statement.'}])
def test_invalid_proposals_never_publish(monkeypatch,change):
    value=draft();value['claims'][0].update(change)
    with pytest.raises(ValueError):r.validate_draft(value,r.packet(BUSINESS,[CAP]))

def test_unknown_evidence_reference_rejected():
    value=draft();claim=value['claims'][0];claim.pop('quote');claim.pop('capture_id');claim['evidence_id']='invented'
    sources=r.packet(BUSINESS,[CAP])
    with pytest.raises(ValueError):r.resolve_evidence(value,r.evidence_index(sources),sources)

def test_quote_is_attached_from_original_source():
    value=draft();claim=value['claims'][0];claim.pop('quote');claim.pop('capture_id');claim['evidence_id']='E1'
    sources=r.packet(BUSINESS,[CAP])
    resolved=r.resolve_evidence(value,r.evidence_index(sources),sources)
    assert resolved.claims[0].quote==TEXT and resolved.claims[0].capture_id=='capture'

def test_critic_rejection_removes_conclusion(monkeypatch):
    mock_passes(monkeypatch,second={'accepted_ids':[]})
    result=r.assess(BUSINESS,[CAP],SETTINGS)
    assert not result['claims'] and 'do not support a clear conclusion' in result['conclusion']

def test_critic_cannot_approve_unsupported_website_absence(monkeypatch):
    value=draft();value['claims'][0]['statement']='The website does not provide evidence of business ownership.'
    mock_passes(monkeypatch,value)
    result=r.assess(BUSINESS,[CAP],SETTINGS)
    assert result['claims']==[] and result['rejected_claim_count']==1

def test_critic_cannot_add_claim(monkeypatch):
    mock_passes(monkeypatch,second={'accepted_ids':['invented']})
    assert r.assess(BUSINESS,[CAP],SETTINGS)['status']=='failed'

def test_mixed_roles_not_automatically_contradiction(monkeypatch):
    value=draft();extra=copy.deepcopy(value['claims'][0]);extra.update(id='two',interpretation='intermediary')
    value['claims'].append(extra);mock_passes(monkeypatch,value,{'accepted_ids':['one','two']})
    assert 'contradiction is not established' in r.assess(BUSINESS,[CAP],SETTINGS)['conclusion']

def test_packet_excludes_other_business_and_third_party():
    caps=[CAP,{**CAP,'business_id':'other'},{**CAP,'final_url':'https://third-party.com/terms'}]
    assert len(r.packet(BUSINESS,caps))==1
    caps=[{**CAP,'id':str(i),'text':'x'*8000} for i in range(12)]
    sources=r.packet(BUSINESS,caps)
    assert len(sources)<=4 and sum(len(s['text']) for s in sources)<=6000

def test_missing_model_no_inference(monkeypatch):
    monkeypatch.setattr(r,'complete',lambda *args:pytest.fail('must not call model'))
    assert r.assess(BUSINESS,[CAP],{})['status']=='unavailable'

def test_cancellation_no_publication(monkeypatch):
    mock_passes(monkeypatch)
    assert r.assess(BUSINESS,[CAP],SETTINGS,lambda:True)['status']=='failed'

@pytest.mark.parametrize('kind',['ollama','openai'])
def test_local_transport_contract(monkeypatch,kind):
    real=httpx.Client
    def handler(req):
        assert req.url.host=='127.0.0.1'
        if kind=='ollama':return httpx.Response(200,json={'message':{'content':'{"claims":[]}'}})
        return httpx.Response(200,json={'choices':[{'message':{'content':'{"claims":[]}'}}]})
    monkeypatch.setattr(r.httpx,'Client',lambda **kw:real(transport=httpx.MockTransport(handler),**kw))
    assert r.complete({**SETTINGS,'kind':kind},'Policy',{},r.Draft.model_json_schema(),100)=={'claims':[]}

def test_failed_runtime_keeps_captured_evidence(monkeypatch):
    def fail(*args):raise httpx.ConnectError('offline')
    monkeypatch.setattr(r,'complete',fail)
    result=r.assess(BUSINESS,[CAP],SETTINGS)
    assert result['status']=='failed' and result['sources'][0]['text']==TEXT
