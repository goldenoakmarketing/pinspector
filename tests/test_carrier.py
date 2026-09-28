import pytest
from app import carrier as c

FREE={'plan':'FREE','payg':0,'active':True,'counter':0,'limit':1000}
@pytest.mark.parametrize('account',[{**FREE,'plan':'BASIC'},{**FREE,'payg':1},{**FREE,'counter':1000},{**FREE,'active':False},{}])
def test_no_paid_or_unverified_account(monkeypatch,account):
    monkeypatch.setattr(c,'request',lambda *a,**kw:account)
    with pytest.raises(c.LookupError):c.free_account('secret')

def test_only_static_lookup_and_original_carrier_label(monkeypatch):
    monkeypatch.setattr(c.s,'read_carrier_key',lambda:'secret')
    calls=[]
    def request(path,key,params=None):
        calls.append((path,params))
        return FREE if path=='/credits' else {'status':'success','phone':'+15108803949','carrier':'Example','phone_type':'fixed_line','mode':'static'}
    monkeypatch.setattr(c,'request',request)
    r=c.lookup('+15108803949')
    assert calls[-1][1]['mode']=='static' and r['line_type']=='fixed_line'
    assert 'current VoIP status are not verified' in r['verification']
    assert 'secret' not in str(r)

def test_missing_key_never_calls_provider(monkeypatch):
    monkeypatch.setattr(c.s,'read_carrier_key',lambda:'')
    monkeypatch.setattr(c,'request',lambda *a:pytest.fail('No connection'))
    with pytest.raises(c.LookupError):c.lookup('+15108803949')
