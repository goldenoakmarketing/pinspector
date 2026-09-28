"""User-imported CSLB CSV snapshots. Missing records are never invalid licenses."""
from __future__ import annotations
import csv,json,re
from pathlib import Path
from .storage import db,now,fingerprint


def key(s): return re.sub(r'[^a-z0-9]','',s.lower())
ALIASES={
 'license':{'license','licenseno','licensenumber','licno','licenseid'},
 'name':{'businessname','name','primaryname','licensename'},
 'status':{'status','licensestatus','licstatus','primarystatus'},
 'phone':{'phone','phonenumber','businessphone'},
 'address':{'address','businessaddress','mailingaddress','streetaddress','address1'}}


def import_csv(path: Path,filename: str,source_date: str) -> dict:
    if not re.fullmatch(r'\d{4}-\d{2}-\d{2}',source_date): raise ValueError('Supply the actual source/download date as YYYY-MM-DD.')
    from datetime import date
    d=date.fromisoformat(source_date)
    if d>date.today(): raise ValueError('Source date cannot be in the future.')
    sha=fingerprint(path.read_bytes())
    count=0
    with path.open('r',encoding='utf-8-sig',errors='replace',newline='') as f,db() as c:
        sample=f.read(4096); f.seek(0)
        try: dialect=csv.Sniffer().sniff(sample,delimiters=',\t|')
        except csv.Error: dialect=csv.excel
        reader=csv.DictReader(f,dialect=dialect)
        headers=reader.fieldnames or []
        mapping={field:next((h for h in headers if key(h) in names),None) for field,names in ALIASES.items()}
        if not mapping['license'] or not mapping['name']:
            raise ValueError('CSV requires license-number and business-name columns. Found: '+', '.join(headers[:15]))
        c.execute('DELETE FROM registry')
        for row in reader:
            license=str(row.get(mapping['license'],'')).strip()
            if not re.fullmatch(r'\d{5,9}',license): continue
            values={k:str(row.get(h,'') or '').strip() if h else '' for k,h in mapping.items()}
            if not values['name']: continue
            c.execute('INSERT OR REPLACE INTO registry VALUES (?,?,?,?,?,?)',
              (license,values['name'],values['status'],values['phone'],values['address'],json.dumps(row)))
            count+=1
        if not count: raise ValueError('No usable license rows; existing registry was not replaced.')
        c.execute('INSERT OR REPLACE INTO registry_import VALUES (1,?,?,?,?,?)',
                  (filename,source_date,now(),sha,count))
    return {'records':count,'source_date':source_date,'filename':filename,'sha256':sha}


def lookup(license: str):
    with db() as c:
        meta=c.execute('SELECT * FROM registry_import WHERE id=1').fetchone()
        if not meta: return {'status':'not_configured'}
        row=c.execute('SELECT * FROM registry WHERE license=?',(license,)).fetchone()
        return {'status':'found' if row else 'not_found_in_snapshot',
                'record':dict(row) if row else None,'snapshot':dict(meta)}
