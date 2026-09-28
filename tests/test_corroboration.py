import json
from app import corroboration as c, storage as s
from app.conclusion import combine
from app.net import Fetched

def test_combined_collection_preserves_provenance_and_failures(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path)
    raw=b'<blockquote>They built a wonderful site for our business.</blockquote><a href="https://client.example">Client website</a>'
    (tmp_path/'home.html').write_bytes(raw)
    saved=[]
    def save(*args):saved.append(args);return str(len(saved))
    monkeypatch.setattr(s,'save_capture',save)
    class Collector:
        def get(self,url):return Fetched(url,url,200,b'<footer>Website powered by <a href="https://agency.example">Our Agency</a></footer>','text/html')
    def search(query,save):return {'query':query,'status':'blocked','urls':[],'error':'Access challenge'}
    def api(url,**kw):
        data={'events':[{'eventAction':'registration','eventDate':'2014-01-01'}]} if 'rdap.org' in url else {'archived_snapshots':{}}
        return Fetched(url,url,200,json.dumps(data).encode(),'application/json')
    result=c.investigate({'id':'b','scan_id':'s','name':'Our Agency','website':'https://agency.example'},
        [{'id':'home','source_type':'website','artifact':'home.html','final_url':'https://agency.example'}],{},[],lambda _:None,lambda:False,Collector(),search,api)
    assert {e['kind'] for e in result['evidence']}=={'testimonial','work_credit','domain_registration'}
    assert len(result['searches'])==1
    assert next(x for x in result['checks'] if x['check']=='External discovery')['status']=='limited'
    assert all(e['capture_id'] for e in result['evidence'])
    assert not any(x['check']=='Legal entity records' for x in result['checks'])

def assessment(*roles):return {'status':'assessed','claims':[{'dimension':'business_role','interpretation':r} for r in roles]}

def test_deep_collection_follows_bounded_second_hop(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path)
    (tmp_path/'home').write_text('<a href="https://one.example">Insulation</a>')
    monkeypatch.setattr(s,'save_capture',lambda *args:'capture')
    visited=[]
    class Collector:
        def get(self,url):
            visited.append(url)
            target='two.example' if 'one.example' in url else 'three.example'
            return Fetched(url,url,200,f'<a href="https://{target}">Roofing</a>'.encode(),'text/html')
    def search(*args):return {'query':'q','status':'complete','urls':[]}
    def api(url,**kw):return Fetched(url,url,200,b'{}','application/json')
    c.investigate({'id':'b','scan_id':'s','name':'Business','website':'https://business.example'},
        [{'id':'home','source_type':'website','artifact':'home','final_url':'https://business.example'}],{},[],lambda _:None,lambda:False,Collector(),search,api,deep=True)
    assert visited==['https://one.example','https://two.example']

def test_credits_support_but_do_not_override_intermediary_role():
    external={'evidence':[{'kind':'work_credit','url':'https://client.example'}]}
    assert combine(assessment('direct_provider'),external,{})['label']=='Unlikely to be a disguised lead-gen operation'
    assert combine(assessment('direct_provider','intermediary'),external,{})['label']=='Mixed service and referral roles'
    assert combine(assessment('intermediary'),external,{})['label']=='Likely lead-gen or referral operation'

def test_missing_records_not_suspicion_and_backlinks_not_work_proof():
    external={'evidence':[{'kind':'backlink','url':'https://unrelated.example'}],
              'checks':[{'check':'Archive availability','status':'failed','detail':'Unavailable'}]}
    result=combine(assessment('direct_provider'),external,{})
    assert result['label']=='Not enough evidence to assess lead-gen risk'
    assert not result['concerns'] and result['gaps']

def test_link_must_target_business_and_credit_must_be_explicit():
    assert not c.external_evidence(b'<footer>Powered by Our Agency</footer>','https://client.example','agency.example')
    items=c.external_evidence(b'<p>Useful link <a href="https://agency.example">Agency</a></p>','https://client.example','agency.example')
    assert items[0]['kind']=='backlink'

def test_negative_review_excluded_but_draft_omission_does_not_erase_work_account():
    a=assessment('direct_provider')
    e={'evidence':[{'kind':'customer_review','url':'https://google.com/maps','capture_id':'r','quote':'They never completed the work.'}]}
    a['claims'].append({'dimension':'corroboration','interpretation':'other_claim','capture_id':'r'})
    assert combine(a,e,{})['label']=='Not enough evidence to assess lead-gen risk'
    e['evidence'][0]['quote']='They completed the work and installed the roof.'
    assert combine(a,e,{})['label']=='Unlikely to be a disguised lead-gen operation'
    a['claims'].pop()
    assert combine(a,e,{})['label']=='Unlikely to be a disguised lead-gen operation'

def test_failed_search_and_no_license_do_not_cancel_positive_evidence():
    a=assessment('direct_provider')
    e={'evidence':[{'kind':'customer_review','capture_id':'review','url':'https://google.com/maps','quote':'I am happy I chose Jeff to design my website.'}],
       'checks':[{'check':'External discovery','status':'failed','detail':'Access challenge'},
                 {'check':'Official licensing','status':'not_triggered','detail':'No number published.'}]}
    result=combine(a,e,{'status':'incomplete'})
    assert result['label']=='Unlikely to be a disguised lead-gen operation'
    assert result['supporting_capture_ids']==['review']
    assert not result['concerns']
    assert not any(g['check']=='Official licensing' for g in result['gaps'])
    assert combine(assessment(),e,{})['label']=='Not enough evidence to assess lead-gen risk'
