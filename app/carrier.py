"""Free-plan-only, numbering-plan lookup. No paid/current-carrier mode."""
import httpx
from . import storage as s

BASE='https://api.veriphone.io/v3'
class LookupError(ValueError):pass

def request(path,key,params=None):
    try:
        with httpx.Client(timeout=15,trust_env=False,follow_redirects=False) as client:
            r=client.get(BASE+path,headers={'Authorization':'Bearer '+key},params=params)
        if r.status_code==429:raise LookupError('Free lookup rate limit reached. Try again later.')
        if r.status_code==402:raise LookupError('Free allowance exhausted. No paid lookup was attempted.')
        if r.status_code in (401,403):raise LookupError('The provider did not accept the connection key.')
        if r.status_code!=200:raise LookupError('Phone provider unavailable. Try again later.')
        return r.json()
    except (httpx.HTTPError,ValueError) as e:
        if isinstance(e,LookupError):raise
        raise LookupError('Phone provider could not be reached or returned an invalid response.') from None

def free_account(key):
    account=request('/credits',key)
    if str(account.get('plan','')).upper()!='FREE' or account.get('payg',0)!=0:
        raise LookupError('Free-only mode: this connection must use the FREE plan with no paid credits.')
    if not account.get('active'):raise LookupError('Activate the free provider account first.')
    if not isinstance(account.get('limit'),(int,float)) or not isinstance(account.get('counter'),(int,float)):
        raise LookupError('Could not verify the free allowance; lookup stopped.')
    if account['counter']>=account['limit']:raise LookupError('Free monthly allowance exhausted. Wait for its reset; no upgrade is needed.')
    return account

def lookup(number):
    try:key=s.read_carrier_key()
    except ValueError:raise LookupError('Phone key could not be unlocked. Reconnect it in Settings.') from None
    if not key:raise LookupError('Connect the free Veriphone account below once, then this button works here.')
    free_account(key)
    data=request('/verify',key,{'phone':number,'mode':'static','record':'false'})
    if data.get('status')!='success' or data.get('mode','static')!='static':raise LookupError('Provider returned no usable standard lookup.')
    if data.get('e164',data.get('phone'))!=number:raise LookupError('Provider returned a different phone number; result rejected.')
    return {'phone':number,'carrier':data.get('carrier') or 'Not reported','line_type':data.get('phone_type') or 'unknown',
        'source_url':BASE+'/verify','observed_at':s.now(),'verification':'Automatically retrieved from Veriphone. Original number-range assignment; current carrier and current VoIP status are not verified.',
        'provider':'Veriphone','mode':'static','provider_response':data}
