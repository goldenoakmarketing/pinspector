import csv
import hashlib
import json
import socket
from pathlib import Path
from unittest.mock import patch
import pytest
from fastapi.testclient import TestClient
from app import storage as s,extract,models,registry,worker
from app.net import normalize_url,public_addresses,UnsafeURL
from app.server import app

@pytest.fixture(autouse=True)
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path/'data')
    monkeypatch.setattr(worker,'submit',lambda sid:None)
    monkeypatch.setattr(worker,'discover_profiles',lambda *args:None)
    monkeypatch.setattr(worker,'corroborate_business',lambda *args:None)
    worker.STOP.clear();s.init()
    yield
    worker.STOP.clear()

@pytest.fixture
def client():
    with TestClient(app,base_url='http://127.0.0.1:8768') as c: yield c

H={'X-BV-Local':'1'}

@pytest.mark.parametrize('name,urls', [('', ['https://example.com']), ('Test', []), ('Test', ['https://example.com', 'https://example.org']), ('Test', ['http://127.0.0.1'])])
def test_single_requires_name_and_one_public_url(client,name,urls):
    response=client.post('/api/scans',headers=H,json={'mode':'single','business_name':name,'urls':urls,'source_ack':True})
    assert response.status_code==400

def test_single_preserves_user_name_and_collects_evidence(client,monkeypatch):
    from app.net import Fetched
    class FixtureFetcher:
        def get(self,url):
            return Fetched(url,url,200,b'<title>Different website title</title><p>We are a referral service.</p>','text/html')
    monkeypatch.setattr(worker,'PoliteFetcher',FixtureFetcher)
    response=client.post('/api/scans',headers=H,json={'mode':'single','business_name':'Named Business','urls':['https://example.com'],'source_ack':True,'use_model':False})
    assert response.status_code==200
    sid=response.json()['id'];worker.run(sid)
    detail=client.get('/api/scans/'+sid).json()
    assert detail['category']=='Named Business'
    assert len(detail['businesses'])==1
    assert detail['businesses'][0]['name']=='Named Business'
    assert detail['businesses'][0]['source']=='user_named_website'
    assert len(detail['captures'])==1
    assert any(f['dimension']=='business_role' for f in detail['findings'])
    verdict=detail['assessments'][0]['result']['combined']
    assert verdict['label']=='Lead-gen / referral service — explicitly disclosed'
    assert verdict['operator_disclosures'][0]['quote']=='We are a referral service.'
    report=client.get('/api/scans/'+sid+'/report').text
    assert verdict['label'] in report and 'Operator disclosure:' in report

def demo_scan(client):
    r=client.post('/api/scans',headers=H,json={'mode':'demo','category':'Roofing','city':'Test City','use_model':False})
    assert r.status_code==200,r.text
    sid=r.json()['id'];worker.run(sid)
    return client.get('/api/scans/'+sid).json()

def test_deep_scan_preserves_parent_profile_and_expands_pages(client):
    parent=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'use_model':False}).json()['id']
    bid=s.business(parent,'Local Pros',website='https://example.com/',phone='530-555-0100',profile_url='https://www.google.com/maps?cid=123')
    s.stage(parent,'Done','ready')
    r=client.post('/api/scans',headers=H,json={'parent_scan_id':parent,'parent_business_id':bid,'use_model':False})
    assert r.status_code==200,r.text
    d=client.get('/api/scans/'+r.json()['id']).json()
    assert d['mode']=='single' and d['config']['max_pages']==12
    assert d['config']['seed_profile']['phone']=='530-555-0100'
    assert d['config']['seed_profile']['profile_url'].endswith('123')
    assert d['config']['parent_scan_id']==parent
    bad=client.post('/api/scans',headers=H,json={'parent_scan_id':parent,'parent_business_id':'other'})
    assert bad.status_code==404

def test_carrier_observation_attributed_and_landline_not_voip(client):
    sid=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'use_model':False}).json()['id']
    bid=s.business(sid,'Example',website='https://example.com/',phone='530-555-0100')
    s.stage(sid,'Done','ready')
    body={'phone':'530-555-0100','carrier':'Example Telecom','line_type':'landline','source_text':'Example Telecom reports landline.'}
    url=f'/api/scans/{sid}/businesses/{bid}/carrier'
    r=client.post(url,headers=H,json=body);assert r.status_code==200,r.text
    cap=client.get('/api/captures/'+r.json()['capture_id']).json()
    result=json.loads(cap['text'])
    assert cap['source_type']=='carrier_lookup_manual' and result['line_type']=='landline'
    assert 'User-entered' in result['verification']
    assert client.post(url,headers=H,json={**body,'line_type':'voip'}).status_code==400
    assert client.post(url,headers=H,json={**body,'phone':'5305550123'}).status_code==400

def test_automatic_carrier_saves_provider_evidence(client,monkeypatch):
    from app import carrier
    sid=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'use_model':False}).json()['id']
    bid=s.business(sid,'Example',website='https://example.com/',phone='530-555-0100')
    s.stage(sid,'Done','ready')
    monkeypatch.setattr(carrier,'lookup',lambda number:{'phone':number,'carrier':'Example','line_type':'fixed_line','source_url':'https://api.veriphone.io/v3/verify','observed_at':s.now(),'verification':'Original assignment only.'})
    response=client.post(f'/api/scans/{sid}/businesses/{bid}/carrier/lookup',headers=H,json={'phone':'530-555-0100'})
    assert response.status_code==200,response.text
    cap=client.get('/api/captures/'+response.json()['capture_id']).json()
    assert cap['source_type']=='carrier_lookup_api'
    assert json.loads(cap['text'])['phone']=='+15305550100'

def test_market_runs_expanded_checks_even_without_website(client,monkeypatch):
    from app import maps
    monkeypatch.setattr(maps,'discover',lambda *args:[{'name':'With site','website':'https://example.com'}, {'name':'No site','website':''}])
    calls=[]
    monkeypatch.setattr(worker,'crawl_business',lambda *args:calls.append('crawl'))
    monkeypatch.setattr(worker,'discover_profiles',lambda sid,b:calls.append(('profiles',b['name'])))
    monkeypatch.setattr(worker,'corroborate_business',lambda sid,b:calls.append(('external',b['name'])))
    monkeypatch.setattr(worker,'assess_business',lambda sid,b,cfg:calls.append(('assess',b['name'])))
    sid=client.post('/api/scans',headers=H,json={'mode':'maps','category':'Roofing','city':'Test','use_model':False}).json()['id']
    worker.run(sid)
    assert calls==['crawl',('profiles','With site'),('external','With site'),('assess','With site'),('profiles','No site'),('external','No site'),('assess','No site')]

def test_market_refresh_is_available_and_demo_stays_offline(client,monkeypatch):
    queued=[]
    monkeypatch.setattr(worker.POOL,'submit',lambda fn,*args:queued.append(fn))
    sid=client.post('/api/scans',headers=H,json={'mode':'maps','category':'Roofing','city':'Test','use_model':False}).json()['id']
    with s.db() as c:c.execute("UPDATE scans SET status='ready' WHERE id=?",(sid,))
    assert client.post('/api/scans/'+sid+'/investigate',headers=H,json={}).status_code==200
    assert queued==[worker.investigate_saved]

def test_failed_profile_collection_does_not_skip_external_checks(client,monkeypatch):
    d=demo_scan(client);calls=[]
    def fail(*args):raise ValueError('layout failure')
    monkeypatch.setattr(worker,'discover_profiles',fail)
    monkeypatch.setattr(worker,'corroborate_business',lambda *args:calls.append('external'))
    monkeypatch.setattr(worker,'assess_business',lambda *args:calls.append('assessment'))
    worker.enrich_business(d['id'],d['businesses'][0],{})
    assert calls==['external','assessment']

@pytest.mark.parametrize('value,expected',[
 ('(530) 555-0100','+15305550100'),('+1 530-555-0100 ext 22','+15305550100'),
 ('12345',None),('1234567890',None),('5305550100;ext=3','+15305550100')])
def test_phone(value,expected):assert extract.phone(value)==expected

@pytest.mark.parametrize('text',[
 'We are not a referral service.',
 'We share data with service providers who operate our website.',
 'Visits are by appointment only.',
 'Our company operates from a residential address.',
 'We do not perform unlicensed roofing work.',
 'We do not perform background checks on service providers.',
 'Some companies say we are a referral service.',
 'For example: we are a referral service.',
 'Mailing address: 12 Main Street.',
 'Independent contractors provide some of our specialist work.',
 'We use third-party service providers to host our website.',
 'Our customer reception is staffed during business hours.',
])
def test_negative_controls(text):assert extract.observations(text)==[]

@pytest.mark.parametrize('text',[
 'We are a referral service.', 'We are a lead-generation company.',
 'We do not perform roofing work.', 'We connect homeowners with independent contractors.',
 'We sell customer inquiries to participating contractors.'
])
def test_referral_disclosures(text):
    out=extract.observations(text);assert out
    assert all(x['dimension']=='business_role' for x in out)
    assert all(x['quote'] in text for x in out)

@pytest.mark.parametrize('text',[
 'This address is for correspondence only.',
 'We do not receive customers at this location.',
 'We do not maintain a physical office in Denver.'
])
def test_location_statements_require_review(text):
    out=extract.observations(text);assert out
    assert all(x['dimension']=='location' for x in out)
    assert all('reviewer' in x['explanation'] for x in out)


def test_legal_footer_is_not_lost():
    page=extract.parse_page('<html><title>A</title><p>Hi</p><footer>We are a referral service. <a href="/terms">Terms</a><a href="tel:5305550100">Call</a></footer></html>','https://example.com/')
    assert 'We are a referral service.' in page['text']
    assert page['links'][0]['url']=='https://example.com/terms'
    assert any(x['value']=='+15305550100' for x in page['identifiers'])


def test_quoted_example_not_operator_statement():
    p=extract.parse_page('<p>Actual business</p><blockquote>We are a referral service.</blockquote>','https://example.com')
    assert not extract.observations(p['text'])


def test_third_party_footer_phone_role():
    p=extract.parse_page('<footer>Website designed by WebCo, <a href="tel:5305550100">(530) 555-0100</a></footer>','https://example.com')
    assert all(x['role']=='third_party' for x in p['identifiers'])


def test_license_claim_context():
    p=extract.parse_page('<p>Contractor license #1234567.</p>','https://example.com')
    assert p['identifiers'][0]['kind']=='license';assert p['identifiers'][0]['value']=='1234567'


def test_model_rejects_invented_quote():
    result={'classification':'referral_or_lead_generation','quote':'We are a referral service and do not do the work.','reason':'Role statement.'}
    assert extract.validate_model_proposal(result,'We are a roofing company.') is None


def test_model_accepts_only_sourced_suggestion():
    text='We are a referral service and do not perform roofing work.'
    result={'classification':'referral_or_lead_generation','quote':text,'reason':'Role statement.'}
    assert extract.validate_model_proposal(result,text)['quote']==text

@pytest.mark.parametrize('url',['https://api.example.com','http://192.168.1.2:11434','http://127.0.0.1:11434/evil','file:///etc/passwd','http://u:p@localhost:11434','http://localhost:11434?x=1'])
def test_model_remote_endpoint_blocked(url):
    with pytest.raises(ValueError):models.endpoint(url)


def test_model_local_endpoint():assert models.endpoint('http://127.0.0.1:1234/v1')=='http://127.0.0.1:1234'

@pytest.mark.parametrize('ip',['127.0.0.1','10.1.2.3','192.168.1.1','169.254.169.254','::1','224.0.0.1','0.0.0.0'])
def test_private_dns_blocked(ip):
    with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(ip,80))]):
        with pytest.raises(UnsafeURL):public_addresses('some-domain.test',80)


def test_mixed_dns_blocked():
    rows=[(socket.AF_INET,socket.SOCK_STREAM,6,'',(x,80)) for x in ('8.8.8.8','127.0.0.1')]
    with patch('socket.getaddrinfo',return_value=rows):
        with pytest.raises(UnsafeURL):public_addresses('some-domain.test',80)


def test_public_dns_allowed():
    with patch('socket.getaddrinfo',return_value=[(socket.AF_INET,socket.SOCK_STREAM,6,'',('8.8.8.8',443))]):
        assert public_addresses('some-domain.test',443)==['8.8.8.8']

@pytest.mark.parametrize('url',['file:///etc/passwd','ftp://example.com','http://user:pass@example.com','https://example.com:8080'])
def test_unsafe_urls(url):
    with pytest.raises(UnsafeURL):normalize_url(url)


def test_url_normalization():assert normalize_url('example.com/terms#section')=='https://example.com/terms'


def test_registry_import_and_missing(tmp_path):
    p=tmp_path/'registry.csv';p.write_text('License Number,Business Name,Status\n1234567,Test Roofing Inc,ACTIVE\n')
    result=registry.import_csv(p,'registry.csv','2026-09-01')
    assert result['records']==1
    assert registry.lookup('1234567')['record']['name']=='Test Roofing Inc'
    assert registry.lookup('7654321')['status']=='not_found_in_snapshot'


def test_failed_registry_import_rolls_back(tmp_path):
    p=tmp_path/'registry.csv';p.write_text('License Number,Business Name\n1234567,Test Roofing\n')
    registry.import_csv(p,'registry.csv','2026-09-01')
    p.write_text('License Number,Business Name\ninvalid,Nope\n')
    with pytest.raises(ValueError):registry.import_csv(p,'bad.csv','2026-09-01')
    assert registry.lookup('1234567')['status']=='found'


def test_api_health(client):
    r=client.get('/api/health');assert r.status_code==200
    assert r.json()['mode']=='local_only'


def test_foreign_host_blocked(client):assert client.get('/api/scans',headers={'host':'evil.example'}).status_code==403

def test_cross_origin_blocked(client):assert client.post('/api/scans',headers={**H,'origin':'https://evil.example'},json={'mode':'demo'}).status_code==403

def test_mutation_requires_local_header(client):assert client.post('/api/scans',json={'mode':'demo'}).status_code==403

def test_live_starts_without_acknowledgment(client):assert client.post('/api/scans',headers=H,json={'category':'Roofing','city':'Redding'}).status_code==200

def test_job_limits(client):assert client.post('/api/scans',headers=H,json={'mode':'demo','max_pages':999}).status_code==422


def test_end_to_end_fictional_scan(client):
    d=demo_scan(client)
    assert d['status']=='ready_with_gaps',d['events']
    assert len(d['businesses'])==3
    assert len(d['captures'])==4
    assert len(d['findings'])>=5
    legit=next(b for b in d['businesses'] if b['name'].startswith('Honest'))
    assert not [f for f in d['findings'] if f['business_id']==legit['id']]
    assert {c['kind'] for c in d['connections']}=={'phone','license'}
    assert all('does not establish' in c['interpretation'] for c in d['connections'])
    c=client.get('/api/captures/'+d['captures'][0]['id']).json()
    raw=client.get('/api/captures/'+c['id']+'/download')
    assert hashlib.sha256(raw.content).hexdigest()==c['sha256']
    assert 'attachment' in raw.headers['content-disposition']


def test_review_and_exports(client):
    d=demo_scan(client);f=d['findings'][0]
    r=client.post('/api/findings/'+f['id']+'/review',headers=H,json={'state':'explained','note':'Fictional training example; not a real allegation.'})
    assert r.status_code==200
    export=client.get('/api/scans/'+d['id']+'/export.json').json()
    assert next(x for x in export['findings'] if x['id']==f['id'])['state']=='explained'
    with s.db() as c:assert c.execute('SELECT COUNT(*) FROM reviews').fetchone()[0]==1
    report=client.get('/api/scans/'+d['id']+'/report')
    assert report.status_code==200
    assert 'FICTIONAL DEMONSTRATION' in report.text
    assert 'No report has been submitted anywhere.' in report.text


def test_xss_escaped_in_report(client):
    d=demo_scan(client)
    with s.db() as c:c.execute('UPDATE businesses SET name=? WHERE id=?',('<script>alert(1)</script>',d['businesses'][0]['id']))
    r=client.get('/api/scans/'+d['id']+'/report')
    assert '<script>alert(1)</script>' not in r.text
    assert '&lt;script&gt;' in r.text


def test_restart_state(client):
    r=client.post('/api/scans',headers=H,json={'mode':'demo'})
    s.init()
    d=client.get('/api/scans/'+r.json()['id']).json()
    assert d['status']=='interrupted'


def test_queue_bound(client):
    for _ in range(3):assert client.post('/api/scans',headers=H,json={'mode':'demo'}).status_code==200
    assert client.post('/api/scans',headers=H,json={'mode':'demo'}).status_code==429


def test_frontend_loads(client):
    r=client.get('/');assert r.status_code==200 and 'PinSpector' in r.text
    assert client.get('/static/app.js').status_code==200
    assert client.get('/static/style.css').status_code==200
    assert "frame-ancestors 'none'" in r.headers['content-security-policy']


def test_inline_disclosure_not_split():
    p=extract.parse_page('<p>We are a <strong>referral service</strong>.</p>','https://example.com')
    assert extract.observations(p['text'])


def test_ollama_adapter_contract(monkeypatch):
    import httpx
    text='We are a referral service and do not perform roofing work.'
    seen=[]
    real_client=httpx.Client
    def handler(request):
        seen.append(json.loads(request.content))
        assert request.url.path=='/api/chat'
        return httpx.Response(200,json={'message':{'content':json.dumps({'classification':'referral_or_lead_generation','quote':text,'reason':'Explicit role disclosure.'})}})
    monkeypatch.setattr(models.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
    result,error=models.analyze(text,{'endpoint':'http://127.0.0.1:11434','kind':'ollama','model':'existing-7b'})
    assert not error and result['quote']==text
    assert seen[0]['format']==models.SCHEMA
    assert seen[0]['stream'] is False
    assert seen[0]['model']=='existing-7b'


def test_openai_local_adapter_contract(monkeypatch):
    import httpx
    text='We are a referral service and do not perform roofing work.'
    real_client=httpx.Client
    def handler(request):
        assert request.url.path=='/v1/chat/completions'
        return httpx.Response(200,json={'choices':[{'message':{'content':json.dumps({'classification':'referral_or_lead_generation','quote':text,'reason':'Operator statement.'})}}]})
    monkeypatch.setattr(models.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
    result,error=models.analyze(text,{'endpoint':'http://127.0.0.1:1234','kind':'openai','model':'existing-7b'})
    assert result and not error


def test_model_timeout_is_visible(monkeypatch):
    import httpx
    real_client=httpx.Client
    def handler(request):raise httpx.ReadTimeout('test timeout',request=request)
    monkeypatch.setattr(models.httpx,'Client',lambda **kwargs:real_client(transport=httpx.MockTransport(handler),**kwargs))
    result,error=models.analyze('This is a website source.',{'endpoint':'http://127.0.0.1:11434','kind':'ollama','model':'existing-7b'})
    assert result is None and 'unavailable' in error


def test_website_workflow_with_fixture_transport(client,monkeypatch):
    from app.net import Fetched
    documents={
      'https://example.com/':'<title>Test Roofer</title><h1>Test Roofer</h1><p>Phone (530) 555-0100.</p><a href="/terms">Terms</a>',
      'https://example.com/terms':'<h1>Terms</h1><p>We are a referral service.</p>'}
    class FixtureFetcher:
        def get(self,url):return Fetched(url,url,200,documents[url].encode(),'text/html')
    monkeypatch.setattr(worker,'PoliteFetcher',FixtureFetcher)
    r=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'source_ack':True,'use_model':False})
    worker.run(r.json()['id'])
    d=client.get('/api/scans/'+r.json()['id']).json()
    assert d['status']=='ready_with_gaps',d['events']
    assert d['assessments'][0]['result']['status']=='unavailable'  # Model intentionally disabled.
    assert d['assessments'][0]['result']['combined']['label']=='Lead-gen / referral service — explicitly disclosed'
    assert len(d['captures'])==2
    assert any(f['dimension']=='business_role' for f in d['findings'])


def test_source_failure_not_fake(client,monkeypatch):
    from app.net import FetchError
    class FailedFetcher:
        def get(self,url):raise FetchError('Access blocked; no bypass attempted.')
    monkeypatch.setattr(worker,'PoliteFetcher',FailedFetcher)
    r=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'source_ack':True,'use_model':False})
    worker.run(r.json()['id']);d=client.get('/api/scans/'+r.json()['id']).json()
    assert d['status']=='ready_with_gaps'
    assert d['findings']==[]
    assert d['businesses'][0]['status']=='source_unavailable'


def test_external_policy_requires_attribution(client,monkeypatch):
    from app.net import Fetched
    documents={
      'https://example.com/':'<h1>Our company</h1><a href="https://policy.example/privacy">Privacy policy</a>',
      'https://policy.example/privacy':'<p>We are a referral service.</p>'}
    class FixtureFetcher:
        def get(self,url):return Fetched(url,url,200,documents[url].encode(),'text/html')
    monkeypatch.setattr(worker,'PoliteFetcher',FixtureFetcher)
    r=client.post('/api/scans',headers=H,json={'mode':'websites','urls':['https://example.com/'],'source_ack':True,'use_model':False})
    worker.run(r.json()['id']);d=client.get('/api/scans/'+r.json()['id']).json()
    assert len(d['findings'])==1
    assert d['findings'][0]['strength']=='unresolved'
    assert 'externally linked document' in d['findings'][0]['explanation']


def test_import_does_not_replace_mid_investigation(client):
    client.post('/api/scans',headers=H,json={'mode':'demo'})
    r=client.post('/api/registry/import',headers={**H,'x-source-date':'2026-09-01'},content='License Number,Business Name\n1234567,Test\n')
    assert r.status_code==409


def test_queued_cancellation(client):
    r=client.post('/api/scans',headers=H,json={'mode':'demo'})
    sid=r.json()['id'];client.post('/api/scans/'+sid+'/cancel',headers=H,json={})
    worker.run(sid);d=client.get('/api/scans/'+sid).json()
    assert d['status']=='cancelled'
    assert not d['captures']

def test_saved_assessment_requires_model(client):
    d=demo_scan(client)
    response=client.post('/api/scans/'+d['id']+'/assess',headers=H,json={})
    assert response.status_code==400

def test_saved_assessment_preserves_sources_history_and_exports(client,monkeypatch):
    from app import reasoning
    d=demo_scan(client);sid=d['id']
    s.put_setting('model',{'kind':'ollama','endpoint':'http://127.0.0.1:11434','model':'test-model'})
    monkeypatch.setattr(reasoning,'complete',lambda settings,system,data,schema,tokens:
        {'claims':[]} if 'claims' in schema['properties'] else {'accepted_ids':[]})
    monkeypatch.setattr(worker.POOL,'submit',lambda fn,*args:fn(*args))
    for _ in range(2):
        response=client.post('/api/scans/'+sid+'/assess',headers=H,json={})
        assert response.status_code==200
    updated=client.get('/api/scans/'+sid).json()
    assert len(updated['assessments'])==6
    assert updated['captures']==d['captures']
    assert all(a['result']['status']=='assessed' for a in updated['assessments'])
    assert len(client.get('/api/scans/'+sid+'/export.json').json()['assessments'])==6
    assert 'Business assessment' in client.get('/api/scans/'+sid+'/report').text
