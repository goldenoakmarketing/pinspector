import hashlib
import json
import zipfile
from pathlib import Path
from tools.build_release import FILES,build,package_files

def test_release_allowlist_excludes_private_files_and_manifest_matches(tmp_path):
    for name in FILES+['app/server.py','docs/DOWNLOAD_README.md','fixtures/demo.html',
        'data/business-validator.sqlite3','.env','Start Local Model.ps1','ATTICALI_NETWORK.md','.venv/secret.py']:
        p=tmp_path/name;p.parent.mkdir(parents=True,exist_ok=True);p.write_text('SYNTHETIC '+name)
    archive=build(tmp_path)
    with zipfile.ZipFile(archive) as z:
        names=z.namelist()
        assert not any('/data/' in n or '.env' in n or 'Start Local Model' in n or 'ATTICALI' in n or '.venv' in n for n in names)
        manifest=json.loads(z.read('PinSpector/MANIFEST.sha256.json'))
        assert all(hashlib.sha256(z.read('PinSpector/'+n)).hexdigest()==h for n,h in manifest.items())
        assert len(names)==len(manifest)+1

def test_actual_release_contains_no_personal_runtime_script():
    root=Path(__file__).resolve().parents[1]
    files=package_files(root)
    assert 'Detect Local Model.ps1' in files
    assert 'Start Local Model.ps1' not in files
    assert not any(b'C:\\Users\\' in content for content in files.values())


def test_public_repository_excludes_private_inputs(tmp_path):
    from tools.build_public_repo import repository_files
    root=Path(__file__).resolve().parents[1]
    public=repository_files(root)
    for name in public:
        assert not any(part in {'.git','data','.venv','__pycache__'} for part in Path(name).parts)
    assert 'LICENSE' in public and b'GNU GENERAL PUBLIC LICENSE' in public['LICENSE']
    assert 'Start Local Model.ps1' not in public
    assert 'ATTICALI_NETWORK.md' not in public
    assert '.github/workflows/tests.yml' in public
    assert 'tests/test_gbp.py' in public
    # An unexpected file under app must not enter either distribution.
    import uuid
    for name,data in public.items():
        path=tmp_path/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    marker=uuid.uuid4().hex.encode()
    (tmp_path/'app'/'private.env').write_bytes(marker)
    assert all(marker not in data for data in repository_files(tmp_path).values())
