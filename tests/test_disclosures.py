import pytest
from app.disclosures import collect
from app.conclusion import combine
from app.reasoning import packet

B={'id':'b','name':'Redding Insulation','website':'https://www.reddinginsulation.com/'}
QUOTE='This website is a free referral directory and matching service.'
def cap(text, **kw):
    return dict(id='terms',business_id='b',final_url=B['website']+'terms-and-conditions',text=text,source_type='website',sha256='abc',observed_at='2026-09-16',**kw)

@pytest.mark.parametrize('text',[
    QUOTE,
    'Redding Insulation is a referral and lead-matching service only.',
    'We do not perform construction, insulation, or home improvement services.',
    'Redding Insulation operates solely as a referral service.',
])
def test_explicit_wording(text):
    found=collect(B,[cap(text)])
    assert found and found[0]['quote']==text and found[0]['capture_id']=='terms'

@pytest.mark.parametrize('text',[
    'We are not a referral service.',
    'We get referrals from satisfied customers.',
    'We provide lead generation services to our agency clients.',
    'For example, we are a referral service.',
    'Other companies say we are a referral service.',
    'A customer said "we are a referral service."',
])
def test_does_not_turn_unrelated_text_into_disclosure(text):
    assert collect(B,[cap(text)])==[]

def test_source_attribution_and_latest_capture():
    c=cap(QUOTE)
    assert not collect(B,[{**c,'business_id':'other'}])
    assert not collect(B,[{**c,'final_url':'https://elsewhere.com/terms'}])
    assert not collect(B,[{**c,'source_type':'customer_review'}])
    assert not collect(B,[c,{**c,'id':'new','text':'We install insulation ourselves.'}])

def test_late_disclaimer_and_later_page_enter_model_packet():
    pages=[{**cap('Marketing '*500),'id':str(i),'final_url':B['website']+str(i)} for i in range(4)]
    pages.append(cap('Navigation '*400+'\n'+QUOTE))
    assert collect(B,pages)[0]['quote']==QUOTE
    assert QUOTE in packet(B,pages)[0]['text']

@pytest.mark.parametrize('assessment',[
    {'status':'assessed','claims':[{'dimension':'business_role','interpretation':'direct_provider'}]},
    {'status':'failed','error':'Model unavailable'},
    {'status':'assessed','claims':[]},
])
def test_disclosure_survives_reviews_and_model_omission(assessment):
    result=combine(assessment,{'evidence':[{'kind':'customer_review','capture_id':'review','quote':'They installed insulation.'}]},{},disclosures=collect(B,[cap(QUOTE)]))
    assert result['label']=='Lead-gen / referral service — explicitly disclosed'
    assert result['operator_disclosures'][0]['quote']==QUOTE
