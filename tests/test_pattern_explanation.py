import copy
import pytest
from app.conclusion import combine

CTX={'signals':[
    {'kind':'partner_number','quote':'In Partnership with Acme. Acme #1234567','capture_id':'partner'},
    {'kind':'outbound_trade_cluster','quote':'Service links point to 26 external domains.','capture_id':'links'}],
    'phone_checks':[{'provider':'Veriphone','line_type':'voip','carrier':'Example','capture_id':'phone'}]}

def test_combined_pattern_has_three_exact_source_references():
    r=combine({'status':'unavailable'},{'site_context':CTX},{})
    assert r['label']=='Likely lead-gen or referral operation'
    assert [x['capture_id'] for x in r['pattern_explanation']['reasons']]==['partner','links','phone']
    assert 'not confirmed' in r['pattern_explanation']['limit']

@pytest.mark.parametrize('missing',['partner_number','outbound_trade_cluster','phone'])
def test_incomplete_pattern_does_not_trigger_joint_verdict(missing):
    ctx=copy.deepcopy(CTX)
    if missing=='phone':ctx['phone_checks']=[]
    else:ctx['signals']=[x for x in ctx['signals'] if x['kind']!=missing]
    assert combine({'status':'unavailable'},{'site_context':ctx},{})['pattern_explanation'] is None

def test_landline_and_manual_reports_do_not_trigger_pattern():
    for change in ({'line_type':'fixed_line'},{'provider':'manual'},{'capture_id':''}):
        ctx=copy.deepcopy(CTX);ctx['phone_checks'][0].update(change)
        assert combine({'status':'unavailable'},{'site_context':ctx},{})['pattern_explanation'] is None

def test_explicit_disclosure_remains_stronger():
    r=combine({'status':'unavailable'},{'site_context':CTX},{},disclosures=[{'kind':'referral'}])
    assert 'explicitly disclosed' in r['label']
