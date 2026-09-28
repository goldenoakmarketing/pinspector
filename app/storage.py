"""Local, isolated SQLite storage. Captures and conclusions are separate records."""
from __future__ import annotations
import contextlib
import hashlib
import json
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
DATA = Path(os.environ.get("BV_DATA_DIR", str(ROOT / "data"))).resolve()

def now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")

def uid() -> str:
    return uuid.uuid4().hex

def fingerprint(value: bytes | str) -> str:
    return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

@contextlib.contextmanager
def db():
    DATA.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DATA / "business-validator.sqlite3", timeout=30)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys=ON")
    conn.execute("PRAGMA secure_delete=ON")
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()

def init():
    for folder in (DATA, DATA / "captures", DATA / "logs", DATA / "imports"):
        folder.mkdir(parents=True, exist_ok=True)
    with db() as c:
        c.execute("PRAGMA journal_mode=WAL")
        c.executescript('''
        CREATE TABLE IF NOT EXISTS settings(key TEXT PRIMARY KEY, value TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS assessments(
          id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, business_id TEXT NOT NULL,
          created_at TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS profile_discoveries(
            id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, business_id TEXT NOT NULL,
            created_at TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS corroborations(
            id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, business_id TEXT NOT NULL,
            created_at TEXT NOT NULL, result TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS scans(
          id TEXT PRIMARY KEY, category TEXT NOT NULL, city TEXT NOT NULL,
          state TEXT NOT NULL DEFAULT 'CA', mode TEXT NOT NULL,
          status TEXT NOT NULL, stage TEXT NOT NULL, created_at TEXT NOT NULL,
          updated_at TEXT NOT NULL, config TEXT NOT NULL, warnings TEXT NOT NULL DEFAULT '[]',
          cancelled INTEGER NOT NULL DEFAULT 0);
        CREATE TABLE IF NOT EXISTS businesses(
          id TEXT PRIMARY KEY, scan_id TEXT NOT NULL REFERENCES scans(id),
          name TEXT NOT NULL, website TEXT, profile_url TEXT, phone TEXT, address TEXT,
          address_state TEXT NOT NULL DEFAULT 'unknown', source TEXT NOT NULL,
          status TEXT NOT NULL DEFAULT 'queued', observed_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS captures(
          id TEXT PRIMARY KEY, scan_id TEXT NOT NULL REFERENCES scans(id),
          business_id TEXT NOT NULL REFERENCES businesses(id), url TEXT NOT NULL,
          final_url TEXT NOT NULL, title TEXT NOT NULL, text TEXT NOT NULL,
          sha256 TEXT NOT NULL, artifact TEXT NOT NULL, observed_at TEXT NOT NULL,
          source_type TEXT NOT NULL, status_code INTEGER NOT NULL, bytes INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS identifiers(
          id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, business_id TEXT NOT NULL,
          capture_id TEXT NOT NULL, kind TEXT NOT NULL, value TEXT NOT NULL,
          role TEXT NOT NULL, context TEXT NOT NULL,
          UNIQUE(capture_id,kind,value,role));
        CREATE TABLE IF NOT EXISTS findings(
          id TEXT PRIMARY KEY, scan_id TEXT NOT NULL, business_id TEXT NOT NULL,
          capture_id TEXT, dimension TEXT NOT NULL, rule TEXT NOT NULL,
          strength TEXT NOT NULL, title TEXT NOT NULL, explanation TEXT NOT NULL,
          quote TEXT NOT NULL, state TEXT NOT NULL DEFAULT 'unreviewed',
          reviewer_note TEXT NOT NULL DEFAULT '', created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS events(
          id INTEGER PRIMARY KEY AUTOINCREMENT, scan_id TEXT NOT NULL,
          level TEXT NOT NULL, message TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registry(
          license TEXT PRIMARY KEY, name TEXT NOT NULL, status TEXT NOT NULL,
          phone TEXT NOT NULL DEFAULT '', address TEXT NOT NULL DEFAULT '', raw TEXT NOT NULL);
        CREATE TABLE IF NOT EXISTS registry_import(
          id INTEGER PRIMARY KEY CHECK(id=1), filename TEXT NOT NULL,
          source_date TEXT NOT NULL, imported_at TEXT NOT NULL,
          sha256 TEXT NOT NULL, records INTEGER NOT NULL);
        CREATE TABLE IF NOT EXISTS reviews(
          id TEXT PRIMARY KEY, finding_id TEXT NOT NULL, state TEXT NOT NULL,
          note TEXT NOT NULL, created_at TEXT NOT NULL);
        CREATE INDEX IF NOT EXISTS capture_scan ON captures(scan_id,business_id);
        CREATE INDEX IF NOT EXISTS finding_scan ON findings(scan_id,business_id);
        CREATE INDEX IF NOT EXISTS identifier_value ON identifiers(scan_id,kind,value);
        ''')
        # Restart recovery is explicit: do not silently rerun network or model work.
        c.execute("UPDATE scans SET status='interrupted',stage='Stopped by application restart; create a new scan to retry.',updated_at=? WHERE status IN ('running','queued')", (now(),))

def read_settings() -> dict:
    with db() as c:
        return {r['key']: json.loads(r['value']) for r in c.execute("SELECT * FROM settings WHERE key != 'carrier_free_key'")}

def read_carrier_key():
    from .secrets import protect,unprotect
    with db() as c:
        row=c.execute("SELECT value FROM settings WHERE key='carrier_free_key'").fetchone()
        if not row:return ''
        value=json.loads(row['value'])
        if isinstance(value,str):
            # Verify protection before replacing legacy data; rollback on failure.
            protected=protect(value)
            if unprotect(protected)!=value:raise ValueError('Phone-key migration failed.')
            c.execute("UPDATE settings SET value=? WHERE key='carrier_free_key'",(json.dumps(protected),))
            return value
        return unprotect(value)

def put_setting(key: str, value: Any):
    if key=='carrier_free_key':
        from .secrets import protect
        value=protect(value)
    with db() as c:
        c.execute('INSERT OR REPLACE INTO settings VALUES (?,?)', (key,json.dumps(value)))

def event(scan_id: str, message: str, level='info'):
    with db() as c:
        c.execute('INSERT INTO events(scan_id,level,message,created_at) VALUES (?,?,?,?)',(scan_id,level,message,now()))

def stage(scan_id: str, text: str, status: str | None = None):
    with db() as c:
        if status:
            c.execute('UPDATE scans SET stage=?,status=?,updated_at=? WHERE id=?',(text,status,now(),scan_id))
        else:
            c.execute('UPDATE scans SET stage=?,updated_at=? WHERE id=?',(text,now(),scan_id))
    event(scan_id,text)

def warn(scan_id: str, text: str):
    with db() as c:
        r=c.execute('SELECT warnings FROM scans WHERE id=?',(scan_id,)).fetchone()
        values=json.loads(r[0])
        if text not in values: values.append(text)
        c.execute('UPDATE scans SET warnings=? WHERE id=?',(json.dumps(values),scan_id))
    event(scan_id,text,'warning')

def is_cancelled(scan_id: str) -> bool:
    with db() as c:
        r=c.execute('SELECT cancelled FROM scans WHERE id=?',(scan_id,)).fetchone()
        return not r or bool(r[0])

def business(scan_id: str, name: str, website='', profile_url='', phone='', address='', address_state='unknown', source='user') -> str:
    bid=uid()
    with db() as c:
        c.execute('INSERT INTO businesses(id,scan_id,name,website,profile_url,phone,address,address_state,source,observed_at) VALUES (?,?,?,?,?,?,?,?,?,?)',
          (bid,scan_id,name,website,profile_url,phone,address,address_state,source,now()))
    return bid

def save_capture(scan_id: str, bid: str, url: str, final_url: str, title: str,
                 text: str, raw: bytes, source_type='website', status_code=200) -> str:
    cid=uid()
    # HTML is saved as data, never rendered in the application's origin.
    artifact=f'captures/{cid}.html'
    (DATA/artifact).write_bytes(raw)
    with db() as c:
        c.execute('INSERT INTO captures VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)',
          (cid,scan_id,bid,url,final_url,title,text,fingerprint(raw),artifact,now(),source_type,status_code,len(raw)))
    return cid

def add_identifier(scan_id,bid,cid,kind,value,role,context):
    with db() as c:
        c.execute('INSERT OR IGNORE INTO identifiers VALUES (?,?,?,?,?,?,?,?)',
           (uid(),scan_id,bid,cid,kind,value,role,context))

def add_finding(scan_id,bid,cid,dimension,rule,strength,title,explanation,quote):
    with db() as c:
        exists=c.execute('SELECT id FROM findings WHERE business_id=? AND rule=? AND quote=?',(bid,rule,quote)).fetchone()
        if not exists:
            c.execute('INSERT INTO findings(id,scan_id,business_id,capture_id,dimension,rule,strength,title,explanation,quote,created_at) VALUES (?,?,?,?,?,?,?,?,?,?,?)',
              (uid(),scan_id,bid,cid,dimension,rule,strength,title,explanation,quote,now()))

def connections(scan_id):
    with db() as c:
        grouped=c.execute('''SELECT kind,value,COUNT(DISTINCT business_id) n FROM identifiers
              WHERE scan_id=? AND role NOT IN ('third_party','privacy_contact')
              GROUP BY kind,value HAVING COUNT(DISTINCT business_id)>1''',(scan_id,)).fetchall()
        out=[]
        for r in grouped:
            refs=[dict(x) for x in c.execute('''SELECT i.business_id,b.name,i.capture_id,i.context,i.role
              FROM identifiers i JOIN businesses b ON b.id=i.business_id
              WHERE i.scan_id=? AND i.kind=? AND i.value=?
              AND i.role NOT IN ('third_party','privacy_contact')''',(scan_id,r['kind'],r['value']))]
            out.append({'kind':r['kind'],'value':r['value'],'business_count':r['n'],'sources':refs,
                'interpretation':'Shared displayed identifier only; does not establish common ownership or misconduct.'})
        return out

def scan_detail(scan_id):
    with db() as c:
        r=c.execute('SELECT * FROM scans WHERE id=?',(scan_id,)).fetchone()
        if not r: return None
        result=dict(r)
        for k in ('config','warnings'): result[k]=json.loads(result[k])
        for table in ('businesses','findings','identifiers'):
            result[table]=[dict(x) for x in c.execute(f'SELECT * FROM {table} WHERE scan_id=?',(scan_id,))]
        result['captures']=[dict(x) for x in c.execute('SELECT id,business_id,url,final_url,title,sha256,observed_at,source_type,bytes FROM captures WHERE scan_id=?',(scan_id,))]
        result['events']=[dict(x) for x in c.execute('SELECT * FROM events WHERE scan_id=? ORDER BY id DESC LIMIT 150',(scan_id,))]
        result['registry_snapshot']=result['config'].get('registry_at_start',{})
        result['assessments']=[dict(x) for x in c.execute('SELECT * FROM assessments WHERE scan_id=? ORDER BY created_at DESC,rowid DESC',(scan_id,))]
        for assessment in result['assessments']: assessment['result']=json.loads(assessment['result'])
        result['profile_discoveries']=[dict(x) for x in c.execute('SELECT * FROM profile_discoveries WHERE scan_id=? ORDER BY created_at DESC,rowid DESC',(scan_id,))]
        for discovery in result['profile_discoveries']: discovery['result']=json.loads(discovery['result'])
        result['corroborations']=[dict(x) for x in c.execute('SELECT * FROM corroborations WHERE scan_id=? ORDER BY created_at DESC,rowid DESC',(scan_id,))]
        for item in result['corroborations']: item['result']=json.loads(item['result'])
    result['connections']=connections(scan_id)
    # Apply current report scope without rewriting historical stored evidence.
    from .conclusion import in_scope,SCOPE
    from .gbp import relevant_profiles
    for discovery in result['profile_discoveries']:
        business=next((b for b in result['businesses'] if b['id']==discovery['business_id']),None)
        location=', '.join(x for x in (result.get('city',''),result.get('state','')) if x and x!='Not specified')
        relevant_profiles(discovery['result'],business,location)
    for item in result['corroborations']:
        item['result']['checks']=[x for x in item['result'].get('checks',[]) if in_scope(x)]
    for item in result['assessments']:
        joint=item['result'].get('combined')
        if joint:
            eligible=[d for d in result['profile_discoveries'] if d['business_id']==item['business_id'] and datetime.fromisoformat(d['created_at'])<=datetime.fromisoformat(item['created_at'])]
            if eligible:
                latest=max(eligible,key=lambda d:datetime.fromisoformat(d['created_at']))
                joint['profile_summary']=latest['result']['summary']
            joint['gaps']=[x for x in joint.get('gaps',[]) if in_scope(x)]
            joint['scope']=SCOPE
            joint['answer']=joint['answer'].replace('a fake-business or disguised lead-generation conclusion','a disguised lead-generation conclusion')
    from .relationships import cross_references
    result['cross_references']=cross_references(result)
    return result
