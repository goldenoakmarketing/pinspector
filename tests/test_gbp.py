from app import gbp

BUSINESS={'id':'business','name':'Golden Oak Local SEO','website':'https://www.goldenoakmarketing.com'}

def profile(key='one',website='https://goldenoakmarketing.com',number='530-555-0100'):
    return {'key':key,'profile_url':'https://www.google.com/maps/place/'+key,'name':BUSINESS['name'],
            'website':website,'phone':number,'capture_id':'capture-'+key,'address':'','address_state':'not_observed'}

def test_name_alone_not_identifier_match():
    result=gbp.match_profile(profile(website='https://different.com'),BUSINESS['name'],BUSINESS['website'],set())
    assert result['match_status']=='name_only'

def test_domain_and_phone_matching():
    result=gbp.match_profile(profile(),BUSINESS['name'],BUSINESS['website'],{'+15305550100'})
    assert result['matched_by']==['domain','phone']
    assert gbp.match_profile(profile(website='https://goldenoakmarketing.com.attacker.net',number=''),BUSINESS['name'],BUSINESS['website'],set())['match_status']=='name_only'

def test_profile_identity_ignores_map_view_changes():
    assert gbp.profile_key('https://www.google.com/maps/place/X/@1,2/data=!1s0xabc:0xdef!8m2!3d1')==gbp.profile_key('https://www.google.com/maps/place/X/@3,4/data=!1s0xabc:0xdef!8m2!3d9')
    assert gbp.profile_key('https://www.google.com/maps/place/X/data=!1s0xabc:0xdef')==gbp.profile_key('https://maps.google.com/maps?cid=3567')

def test_name_domain_phone_searches_and_deduplication():
    calls=[]
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'complete','profiles':[profile()],'capture_ids':['search']}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert calls==[gbp.name_query(BUSINESS['name']),'goldenoakmarketing.com','"golden oak"','+15305550100']
    assert len(result['profiles'])==1
    assert result['status']=='complete'
    assert 'No distinct additional profiles identified' in result['summary']
    assert len(result['profiles'][0]['queries'])==4

def test_additional_profile_is_candidate_not_duplicate_verdict():
    def search(query,*args):
        return {'query':query,'status':'complete','profiles':[profile(),profile('two')],'capture_ids':[]}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert len(result['profiles'])==2
    assert 'Branch/location legitimacy not verified' in result['summary']

def test_other_domain_candidate_is_not_in_confirmed_count():
    matched=[{**profile(str(i)),'match_status':'identifier_match','identity_source':'url'} for i in range(3)]
    other={**profile('union',website='https://other.example',number='916-555-2222'),'name':'Other Union Company','match_status':'unresolved_candidate','identity_source':'url'}
    result=gbp.summary({'profiles':matched+[other],'searches':[{'status':'complete'}]})
    assert result.startswith('3 GBP identifier matches.')
    assert '1 separate candidate(s) not matched' in result

def test_failed_search_never_becomes_no_matches():
    def search(query,*args):return {'query':query,'status':'failed','profiles':[],'capture_ids':[],'error':'layout failed'}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert result['status']=='incomplete'
    assert 'Collection was inconclusive' in result['summary']
    assert 'No additional' not in result['summary']
    assert result['searches'][-1]['status']=='not_searched'

def test_unrelated_phone_not_used_to_expand_search():
    calls=[]
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'complete','profiles':[profile(website='https://unrelated.com')],'capture_ids':[]}
    gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert calls==[gbp.name_query(BUSINESS['name']),'goldenoakmarketing.com','"golden oak"']

def test_missing_address_is_not_storefront_concern():
    result=gbp.match_profile(profile(),BUSINESS['name'],BUSINESS['website'],set())
    assert result['match_status']=='identifier_match'
    assert 'location' not in result

def test_unresolved_share_links_do_not_inflate_distinct_profile_count():
    known={**profile(),'match_status':'identifier_match','identity_source':'resolved_share_link'}
    unresolved={**profile('short-link'),'match_status':'identifier_match','identity_source':'share_link'}
    text=gbp.summary({'profiles':[known,unresolved],'searches':[{'status':'partial'}]})
    assert text=='1 GBP confirmed. No distinct additional profiles identified.'
    assert 'No additional' not in text

def test_access_gate_stops_remaining_maps_queries():
    calls=[]
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'blocked','profiles':[],'capture_ids':[],'error':'Consent gate'}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert calls==[gbp.name_query(BUSINESS['name'])]
    assert result['searches'][1]['kind']=='domain' and result['searches'][1]['status']=='not_searched'

def test_footer_embed_extracts_cid_and_retains_source():
    raw='<iframe src="https://www.google.com/maps/embed?pb=!1m2!1s0xabc%3A0xdef!2sGolden%20Oak%20Local%20SEO!5e1"></iframe>'
    seeds=gbp.website_profiles(raw,BUSINESS['website'],'homepage')
    assert len(seeds)==1 and seeds[0]['key']=='cid:3567'
    assert seeds[0]['name']=='Golden Oak Local SEO' and seeds[0]['capture_id']=='homepage'
    assert seeds[0]['match_status']=='website_reference'
    assert not seeds[0]['address']

def test_embed_survives_blocked_live_search_without_zero_matches():
    seeds=gbp.website_profiles('<iframe src="https://www.google.com/maps?cid=3567"></iframe>',BUSINESS['website'],'home')
    calls=[]
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'blocked','profiles':[],'capture_ids':[],'error':'gate'}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search,seeds)
    assert calls[0]=='https://www.google.com/maps?cid=3567'
    assert 'found on the website. Live verification pending' in result['summary']
    assert '0 distinct' not in result['summary'] and 'No additional' not in result['summary']
    assert result['profiles'][0]['capture_id']=='home'

def test_embed_and_search_resolve_to_one_profile():
    seeds=gbp.website_profiles('<iframe src="https://www.google.com/maps/embed?pb=!1s0xabc:0xdef!2sGolden%20Oak"></iframe>',BUSINESS['website'],'home')
    p={**profile('cid:3567'),'profile_url':'https://www.google.com/maps/place/X/data=!1s0xabc:0xdef','identity_source':'url'}
    def search(query,*args):return {'query':query,'status':'complete','profiles':[p],'capture_ids':[]}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search,seeds)
    assert len(result['profiles'])==1
    assert result['summary'].startswith('1 GBP confirmed.')
    assert 'home' in result['profiles'][0]['capture_ids']

def test_generic_map_coordinates_and_spoofed_google_host_are_not_profiles():
    for url in ('https://www.google.com/maps?ll=39,-121','https://www.google.com.attacker.net/maps?cid=3567'):
        assert not gbp.website_profiles('<iframe src="'+url+'"></iframe>',BUSINESS['website'],'home')

def test_unresolved_matching_observations_not_reported_as_zero():
    p={**profile(),'match_status':'identifier_match','identity_source':'unresolved'}
    text=gbp.summary({'profiles':[p],'searches':[{'status':'partial'}]})
    assert '0 distinct' not in text and 'Matching GBP results found' in text


def test_connected_names_and_numbers_expand_beyond_old_five_query_limit():
    calls=[]
    def search(query,*args):
        calls.append(query)
        p=profile('branch',number='530-555-0200');p['name']='Alternate Branch'
        return {'query':query,'status':'complete','profiles':[p],'capture_ids':[]}
    business={**BUSINESS,'profile_url':'https://www.google.com/maps?cid=123'}
    ids=[{'kind':'phone','role':'displayed_contact','value':'+15305550100'}]
    r=gbp.investigate(business,ids,lambda x:None,lambda:False,lambda *x:None,search,
                      aliases=[{'name':'Published Brand','capture_id':'home'}])
    assert gbp.name_query('Alternate Branch') in calls and '+15305550200' in calls
    assert len(calls)>5 and len(calls)<=12
    assert r['network']['profile_count']==1


def test_unrelated_names_are_not_expansion_seeds():
    calls=[]
    def search(query,*args):
        calls.append(query)
        p={**profile(website='https://other.test'),'name':'Unrelated Company'}
        return {'query':query,'status':'complete','profiles':[p],'capture_ids':[]}
    gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert 'Unrelated Company' not in calls


def test_network_counts_distinct_ids_and_preserves_link_evidence():
    a={**profile('cid:1'),'match_status':'identifier_match'}
    b={**profile('cid:2',number='530-555-0200'),'name':'Other brand','match_status':'identifier_match'}
    unresolved={**a,'key':'short','identity_source':'share_link'}
    n=gbp.network_view([a,b,unresolved],BUSINESS,{' +15305550100'.strip()})
    assert (n['profile_count'],n['name_count'],n['phone_count'])==(2,2,2)
    assert any(e['from']=='cid:1' and e['to']=='cid:2' and e['kind']=='domain' for e in n['edges'])
    assert all(e.get('capture_id') or e.get('capture_ids') for e in n['edges'])


def test_published_alias_keeps_provenance():
    aliases=gbp.website_aliases('<title>Terms of Service - Example EcoShield</title><meta property="og:site_name" content="Example EcoShield">','https://example.test/terms','terms')
    assert aliases==[{'name':'Example EcoShield','source_url':'https://example.test/terms','capture_id':'terms'}]


def test_generic_titles_and_site_names_are_not_aliases():
    for name in ('Best Local','all of United States','About Us','Contact Us','Local SEO & AI Search Marketing','Morgan Hill, CA'):
        assert not gbp.website_aliases('<title>Company - '+name+'</title><meta property="og:site_name" content="'+name+'">','https://example.test','c')
    assert not gbp.website_aliases('<title>Company - Unrelated Slogan</title>','https://example.test','c')


def test_location_scoped_names_preserve_distant_identifier_matches():
    calls=[]
    other={**profile('restaurant',website='https://cafe.test',number='530-555-9999'),'name':"Becca's Cafe"}
    distant={**profile('branch'),'address':'Redding, CA'}
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'complete','profiles':[distant,other],'capture_ids':['original']}
    result=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search,
        aliases=[{'name':'Best Local'},{'name':'About Us'}],location='San Jose, CA')
    assert calls[0]=='"Golden Oak Local SEO" San Jose, CA'
    assert 'goldenoakmarketing.com' in calls
    assert [p['key'] for p in result['profiles']]==['branch']
    assert [p['key'] for p in result['excluded_profiles']]==['restaurant']
    assert other in result['searches'][0]['profiles']
    assert all('Best Local' not in q and 'About Us' not in q for q in calls)
    assert 'Additional candidates need review' not in result['summary']


def test_shared_host_is_not_identity_or_domain_search():
    business={**BUSINESS,'website':'https://sites.google.com/view/my-agency'}
    p=profile(website='https://sites.google.com/view/unrelated-cafe')
    assert gbp.match_profile(p,business['name'],business['website'],set())['matched_by']==[]
    calls=[]
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'complete','profiles':[],'capture_ids':[]}
    gbp.investigate(business,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert 'sites.google.com' not in calls


def test_saved_result_filter_is_idempotent_and_keeps_name_candidates():
    known={**profile(),'match_status':'identifier_match'}
    same={**profile('same'),'match_status':'name_only'}
    unrelated={**profile('other'),'match_status':'unresolved_candidate'}
    result={'profiles':[known,same,unrelated]}
    gbp.relevant_profiles(result)
    gbp.relevant_profiles(result)
    assert result['profiles']==[known,same]
    assert result['excluded_profiles']==[unrelated]


import pytest

@pytest.mark.parametrize('root,candidate,address,expected',[
    ('Best Local SEO','Best Local SEO','Redding, CA','exact_name'),
    ('Social Cali of San Jose','Social Cali of Rocklin','Rocklin, CA','brand_variant'),
    ('Foamers San Jose SEO','Foamers Digital Marketing','Redding, CA','brand_variant'),
    ('Golden Oak Local SEO','Golden Oak Marketing Redding','123 Main St, Redding, CA 96001','brand_variant'),
    ('Foamers SEO','Foammers SEO','','brand_variant'),
    ('Best Local SEO','The Best Little Sandwich Shop','Anderson, CA',''),
    ('Foamers San Jose SEO',"Foamers' Folly Brewing Co.",'British Columbia, Canada',''),
    ('Foamers SEO','Foamers Folly','',''),
    ('Best Local SEO','Nuon Marketing','Redding, CA',''),
    ('All Pro Window Replacement San Jose','All Pro Landscaping','Redding, CA',''),
    ('All Pro Window Replacement','All Pro Windows','Redding, CA',''),
    ('Golden Oak Windows','Golden Oak Landscaping','Redding, CA',''),
    ('SEO Website Design','Redding Website Design','Redding, CA',''),
    ('','', '', ''),
])
def test_name_connection_boundaries(root,candidate,address,expected):
    p={'name':candidate,'address':address}
    assert gbp.name_connection(p,root,'San Jose, CA')[0]==expected


def test_name_candidates_do_not_expand_by_their_phone_or_inflate_network():
    calls=[]
    p={**profile('variant',website='https://other.test',number='530-555-9999'),'name':'Golden Oak Marketing'}
    def search(query,*args):
        calls.append(query)
        return {'query':query,'status':'complete','profiles':[p],'capture_ids':[]}
    r=gbp.investigate(BUSINESS,[],lambda x:None,lambda:False,lambda *x:None,search)
    assert r['profiles'][0]['match_status']=='name_only'
    assert r['profiles'][0]['name_match_kind']=='brand_variant'
    assert '+15305559999' not in calls
    assert r['network']['profile_count']==0
    assert 'No identifier match confirmed' in r['summary']


def test_saved_excluded_name_variant_is_restored_without_restoring_noise():
    variant={**profile('variant'),'name':'Golden Oak Marketing','match_status':'unresolved_candidate'}
    noise={**profile('noise'),'name':"Becca's Cafe",'match_status':'unresolved_candidate'}
    r={'profiles':[],'excluded_profiles':[variant,noise]}
    gbp.relevant_profiles(r,BUSINESS,'San Jose, CA')
    assert [p['key'] for p in r['profiles']]==['variant']
    assert r['profiles'][0]['match_status']=='name_only'
    assert [p['key'] for p in r['excluded_profiles']]==['noise']


def test_conflicting_trade_still_allows_concrete_identifier():
    p={**profile(),'name':'All Pro Landscaping'}
    assert gbp.match_profile(p,'All Pro Window Replacement',BUSINESS['website'],set())['match_status']=='identifier_match'
