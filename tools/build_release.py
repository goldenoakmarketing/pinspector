"""Build a review-only source beta from an allowlist, never from the working folder."""
from pathlib import Path
import hashlib
import json
import zipfile

ROOT=Path(__file__).resolve().parents[1]
FILES=['LICENSE','THIRD_PARTY_NOTICES.md','bootstrap.py','requirements.txt','Start PinSpector.cmd','Stop PinSpector.cmd',
       'Install Browser.cmd','Diagnostics.cmd','Detect Local Model.ps1','app/constitution.md',
       'app/static/app.js','app/static/index.html','app/static/style.css',
       'docs/CONTRIBUTING.md','docs/SECURITY.md','docs/LOCAL_MODEL_SETUP.md']

def package_files(root):
    root=root.resolve()
    names=FILES+[p.relative_to(root).as_posix() for p in (root/'app').glob('*.py')]
    names += [p.relative_to(root).as_posix() for p in (root/'fixtures').glob('*.html')]
    files={}
    for name in sorted(set(names)):
        p=root/name
        if not p.resolve().is_relative_to(root) or p.is_symlink():raise ValueError('Package input escapes release root')
        files[name]=p.read_bytes()
    files['README.md']=(root/'docs'/'DOWNLOAD_README.md').read_bytes()
    return files

def build(root=ROOT):
    files=package_files(root)
    manifest={n:hashlib.sha256(b).hexdigest() for n,b in files.items()}
    files['MANIFEST.sha256.json']=json.dumps(manifest,indent=2).encode()
    target=root/'dist'/'PinSpector-beta-candidate.zip'
    target.parent.mkdir(exist_ok=True)
    with zipfile.ZipFile(target,'w',zipfile.ZIP_DEFLATED) as archive:
        for name,data in files.items():archive.writestr('PinSpector/'+name,data)
    target.with_suffix('.zip.sha256').write_text(hashlib.sha256(target.read_bytes()).hexdigest()+'  '+target.name+'\n',encoding='ascii')
    print(f'Built review-only beta: {len(files)} allowlisted files. No user database, keys, captures, logs, or runtimes included.')
    return target

if __name__=='__main__':build()
