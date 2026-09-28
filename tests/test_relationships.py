from app.relationships import signals
from app.conclusion import combine

B={'id':'a','name':'Acme','website':'https://acme.example'}

def test_website_phone_mismatch_has_source_and_is_not_proof():
    d={'captures':[{'id':'web','business_id':'a','source_type':'website'}],
       'identifiers':[{'business_id':'a','kind':'phone','value':'+15305550100','role':'displayed_contact','capture_id':'web'}]}
    found=signals({**B,'phone':'530-555-0200'},d,{})
    assert len(found)==1 and found[0]['requires_review']
    assert 'differs from website' in found[0]['description']
    assert found[0]['capture_ids']==['web']
    d['identifiers'][0]['role']='third_party'
    assert not signals({**B,'phone':'530-555-0200'},d,{})

def test_network_of_domain_matched_profiles_is_one_review_lead():
    profiles=[{'name':n,'capture_id':n,'match_status':'identifier_match','matched_by':['domain']} for n in ['a','b']]
    d={'captures':[{'id':'a'},{'id':'b'}]}
    network={'profile_count':2,'name_count':2,'phone_count':2,'summary':'2 connected profiles'}
    found=signals(B,d,{'profiles':profiles,'network':network})
    assert len(found)==1 and 'not independent corroboration' in found[0]['description']

def detail(kind='phone'):
    return {'captures':[{'id':'a1'},{'id':'b1'}], 'connections':[{'kind':kind,'value':'5551234567','sources':[
        {'business_id':'a','name':'Acme','capture_id':'a1','role':'operator'},
        {'business_id':'b','name':'Other Name','capture_id':'b1','role':'claimed_license' if kind=='license' else 'operator'}]}]}

def test_phone_and_license_connections_survive_positive_service_evidence():
    for kind in ('phone','license'):
        leads=signals(B,detail(kind),{})
        assert len(leads)==1 and leads[0]['capture_ids']==['a1','b1']
        assessment={'status':'assessed','claims':[{'dimension':'business_role','interpretation':'direct_provider'}]}
        result=combine(assessment,{'evidence':[{'kind':'work_credit','url':'https://client.example'}]}, {'status':'complete'},leads)
        assert 'need review' in result['label'] and result['concerns']
        assert 'hypotheses' in leads[0]['alternative_explanations']

def test_excludes_unrelated_and_third_party_identifiers():
    d=detail();d['connections'][0]['sources'][1]['role']='third_party'
    assert not signals(B,d,{})
    d=detail();d['connections'][0]['sources'][0]['business_id']='elsewhere'
    assert not signals(B,d,{})

def test_name_variant_alone_does_not_create_shared_identifier_lead():
    d=detail();d['connections'][0]['sources'][1]['name']='ACME!'
    assert not signals(B,d,{})

def test_different_name_phone_match_is_lead_even_without_address():
    d={'captures':[{'id':'p'}]}
    profile={'name':'Other Name','match_status':'identifier_match','matched_by':['phone'], 'phone':'5551234567','name_matches':False,'capture_id':'p','address':''}
    leads=signals(B,d,{'profiles':[profile,profile]})
    assert len(leads)==1 and leads[0]['requires_review']
    profile['matched_by']=['domain']
    assert not signals(B,d,{'profiles':[profile]})

def test_no_customer_reception_is_context_not_false_location_finding():
    d={'captures':[{'id':'a1'}],'findings':[{'business_id':'a','dimension':'location','strength':'direct_statement','capture_id':'a1','title':'No customer reception at stated location','quote':'We do not receive customers at this location.'}]}
    leads=signals(B,d,{})
    assert len(leads)==1 and not leads[0]['requires_review']
    assert not combine({}, {}, {}, leads)['concerns']
    d['findings'][0]['title']='Address described as correspondence-only'
    assert signals(B,d,{})[0]['requires_review']

def test_missing_capture_cannot_create_lead():
    d=detail();d['captures']=[]
    assert not signals(B,d,{})
