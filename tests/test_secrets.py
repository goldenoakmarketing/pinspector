import json
import os
import pytest
from app import storage as s
from app import secrets

@pytest.fixture
def isolated(tmp_path,monkeypatch):
    monkeypatch.setattr(s,'DATA',tmp_path)
    s.init()

@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI integration')
def test_windows_roundtrip_and_tamper_rejection():
    value=secrets.protect('synthetic-secret-for-test')
    assert 'synthetic-secret' not in json.dumps(value)
    assert secrets.unprotect(value)=='synthetic-secret-for-test'
    value['ciphertext']='AAAA'
    with pytest.raises(secrets.SecretError):secrets.unprotect(value)

@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI integration')
def test_new_key_is_encrypted_and_excluded_from_general_settings(isolated):
    s.put_setting('carrier_free_key','synthetic-key-not-a-real-api-key')
    assert s.read_carrier_key()=='synthetic-key-not-a-real-api-key'
    assert 'carrier_free_key' not in s.read_settings()
    with s.db() as c:stored=c.execute("SELECT value FROM settings WHERE key='carrier_free_key'").fetchone()[0]
    assert 'synthetic-key-not-a-real-api-key' not in stored

@pytest.mark.skipif(os.name!='nt',reason='Windows DPAPI integration')
def test_legacy_key_migrates_without_plaintext_left_in_database(isolated):
    key='synthetic-legacy-secret-for-migration'
    with s.db() as c:c.execute('INSERT INTO settings VALUES (?,?)',('carrier_free_key',json.dumps(key)))
    assert s.read_carrier_key()==key
    assert key.encode() not in (s.DATA/'business-validator.sqlite3').read_bytes()

def test_failed_encryption_preserves_existing_key(isolated,monkeypatch):
    with s.db() as c:c.execute('INSERT INTO settings VALUES (?,?)',('carrier_free_key',json.dumps('synthetic-old-key')))
    def fail(value):raise secrets.SecretError('Failed')
    monkeypatch.setattr(secrets,'protect',fail)
    with pytest.raises(secrets.SecretError):s.read_carrier_key()
    with s.db() as c:assert json.loads(c.execute('SELECT value FROM settings').fetchone()[0])=='synthetic-old-key'

def test_validation_errors_do_not_echo_key(isolated):
    from fastapi.testclient import TestClient
    from app.server import app,PORT
    client=TestClient(app,base_url=f'http://127.0.0.1:{PORT}')
    response=client.post('/api/carrier/connect',headers={'X-BV-Local':'1'},json={'key':'sensitive'*100})
    assert response.status_code==422 and 'sensitive' not in response.text
