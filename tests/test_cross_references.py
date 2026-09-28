from app.relationships import cross_references

def data():
    return {'businesses':[
        {'id':'marketing','name':'Fremont Insulation Pros','website':'https://fremont.example'},
        {'id':'contractor','name':'Attical Insulation and Rodents','website':'https://attical.example'},
        {'id':'similar','name':'Atticali EcoShield','website':'https://atticali.example'}],
        'captures':[{'id':n,'business_id':b,'source_type':'website'} for n,b in [('m','marketing'),('c','contractor'),('s','similar')]],
        'identifiers':[{'business_id':'contractor','kind':'license','value':'1126472','role':'claimed_license','capture_id':'c'}],
        'assessments':[{'business_id':'marketing','result':{'combined':{'site_context':{'signals':[
            {'kind':'partner_number','quote':'In Partnership with Attical Insulation and Rodents\nAttical Inc. # 1126472','capture_id':'m'}]}}}}]}

def test_partner_number_links_both_ends_without_reassigning_license():
    refs=cross_references(data())
    for bid in ('marketing','contractor'):
        r=next(x for x in refs[bid] if x['kind']=='partner_license')
        assert set(r['capture_ids'])=={'m','c'}
        assert '1126472' in r['text'] and 'In Partnership with' in r['text']
        assert 'inferred, not established' in r['meaning']
    assert not any(x['kind']=='partner_license' for x in refs['similar'])

def test_similar_name_does_not_merge_different_domains():
    refs=cross_references(data())
    r=next(x for x in refs['similar'] if x['kind']=='similar_name')
    assert 'different websites' in r['text'] and 'Name similarity only' in r['meaning']

def test_shared_phone_and_license_keep_both_sources():
    d=data();d['identifiers'] += [
        {'business_id':'marketing','kind':'license','value':'1126472','role':'claimed_license','capture_id':'m'},
        {'business_id':'marketing','kind':'phone','value':'530-555-0100','role':'displayed_contact','capture_id':'m'},
        {'business_id':'contractor','kind':'phone','value':'+15305550100','role':'displayed_contact','capture_id':'c'}]
    refs=cross_references(d)['marketing']
    assert {'phone','license','partner_license'} <= {x['kind'] for x in refs}
    d['identifiers'][-1]['role']='privacy_contact'
    assert not any(x['kind']=='phone' for x in cross_references(d)['marketing'])

def test_unmatched_partner_stays_attributed():
    d=data();d['identifiers']=[]
    refs=cross_references(d)['marketing']
    assert len(refs)==1 and 'No matching partner website' in refs[0]['meaning']

def test_missing_sources_cannot_create_connection():
    d=data();d['captures']=[]
    assert not any(cross_references(d).values())
