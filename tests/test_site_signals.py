import json
import pytest
from app import site_signals as ss,storage as s
from app.conclusion import combine

B={'id':'b','name':'Fremont Insulation Pros','website':'https://business.example'}
@pytest.fixture
def pages(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path)
    def make(raw,url='https://business.example/',kind='website',cid='home'):
        (tmp_path/cid).write_text(raw,encoding='utf-8')
        from bs4 import BeautifulSoup
        return {'id':cid,'business_id':'b','artifact':cid,'final_url':url,'source_type':kind,'text':BeautifulSoup(raw,'html.parser').get_text('\n',strip=True)}
    return make

def test_trade_links_have_exact_edges_and_no_invented_cycle(pages):
    c=pages(''.join(f'<p>Our <a href="https://trade{i}.example/">insulation</a> services</p>' for i in range(5)))
    r=ss.analyze(B,[c])
    assert r['signals'][0]['kind']=='outbound_trade_cluster'
    assert len(r['signals'][0]['edges'])==5 and not r['link_paths']
    a=combine({'status':'assessed','claims':[{'dimension':'business_role','interpretation':'direct_provider'}]},
      {'site_context':r,'evidence':[{'kind':'work_credit','url':'https://client.example','capture_id':'credit'}]}, {})
    assert a['label'].startswith('Possible lead-gen network')

def test_actual_three_domain_cycle(pages):
    caps=[pages('<a href="https://two.example">Insulation</a>'),
      pages('<a href="https://three.example">Roofing</a>','https://two.example','external_page','two'),
      pages('<a href="https://business.example">Heating</a>','https://three.example','external_page','three')]
    paths=ss.analyze(B,caps)['link_paths']
    assert len(paths)==1 and [e['capture_id'] for e in paths[0]]==['home','two','three']

def test_portfolio_and_social_links_not_trade_network(pages):
    c=pages(''.join(f'<p>Our clients <a href="https://trade{i}.example">insulation</a></p>' for i in range(5))+'<a href="https://facebook.com/acme">Facebook</a><a href="https://facebook.com/sharer?u=x">Share</a>')
    r=ss.analyze(B,[c]);assert not r['signals']
    assert len(r['social_profiles'])==1 and not r['link_paths']

def test_explicit_staff_not_review_author(pages):
    data={'@type':'Organization','founder':{'@type':'Person','name':'Jane Doe'},'review':{'author':{'@type':'Person','name':'Customer Name'}}}
    r=ss.analyze(B,[pages('<script type="application/ld+json">'+json.dumps(data)+'</script>')])
    assert [p['name'] for p in r['staff']]==['Jane Doe']

def test_contextual_role_requires_multiple_cues(pages):
    matching='<p>We connect homeowners with qualified local contractors.</p>'
    delivery='<p>All work is performed by independent contractors.</p>'
    r=ss.analyze(B,[pages(matching+delivery)])
    assert {x['kind'] for x in r['signals']}=={'provider_matching','third_party_delivery'}
    a=combine({'status':'unavailable'},{'site_context':r},{})
    assert a['label']=='Likely lead-gen or referral operation'
    r=ss.analyze(B,[pages(delivery)])
    assert not combine({'status':'unavailable'},{'site_context':r},{})['label'].startswith('Likely')

def test_newer_capture_replaces_old_and_other_business_excluded(pages):
    old=pages('<p>We connect homeowners with local contractors.</p>',cid='old')
    new=pages('<p>We install insulation.</p>',cid='new')
    assert not ss.analyze(B,[old,new,{**old,'business_id':'other'}])['signals']

def test_voip_and_pros_name_alone_do_not_change_verdict(pages):
    r=ss.analyze(B,[pages('<p>Quality work</p>')]);r['phone_checks']=[{'line_type':'voip'}]
    a=combine({'status':'unavailable'},{'site_context':r},{})
    assert a['label']=='Analysis not run' and not a['concerns']

@pytest.mark.parametrize('text',['We do not share your information with marketing partners.','Other companies match homeowners with local contractors.'])
def test_negated_or_other_operator_routing_not_flagged(pages,text):
    assert not ss.analyze(B,[pages('<p>'+text+'</p>')])['signals']

def test_partner_number_attributed_to_partner(pages):
    r=ss.analyze(B,[pages('<p>In Partnership with Partner Roofing</p><p>Partner Inc. # 1234567</p>')])
    item=next(x for x in r['signals'] if x['kind']=='partner_number')
    assert '1234567' in item['quote'] and 'not verified or attributed' in item['scope']
