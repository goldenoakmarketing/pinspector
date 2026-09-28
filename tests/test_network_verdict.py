from app.conclusion import combine

def test_network_is_specific_without_claiming_lead_sales():
    r=combine({'status':'assessed','claims':[]},{},{'network':{'profile_count':3,'phone_count':3}})
    assert r['label']=='Connected listings; lead-gen role unconfirmed'
    assert 'different phone numbers' in r['answer']

def test_explicit_referral_overrides_network_uncertainty():
    r=combine({'status':'assessed','claims':[]},{},{'network':{'profile_count':3,'phone_count':3}},
              disclosures=[{'kind':'referral','quote':'We refer customers to contractors.'}])
    assert r['label']=='Lead-gen / referral service — explicitly disclosed'

def test_one_profile_does_not_get_network_label():
    r=combine({'status':'assessed','claims':[]},{},{'network':{'profile_count':1,'phone_count':1}})
    assert not r['label'].startswith('Connected listings')
