"""Export public repository contents without copying private data or Git history."""
from pathlib import Path
import hashlib
import json
import sys

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_release import package_files,ROOT


def repository_files(root):
    files=package_files(root)
    extra=['.gitignore','requirements-dev.txt','tools/build_release.py',
           'tools/build_public_repo.py','docs/DOWNLOAD_README.md',
           'docs/CONTRIBUTING.md','docs/SECURITY.md']
    extra += [p.relative_to(root).as_posix() for p in (root/'tests').glob('test_*.py')]
    for name in extra:
        path=root/name
        if path.is_symlink() or not path.resolve().is_relative_to(root.resolve()):
            raise ValueError('Public input escapes source directory')
        files[name]=path.read_bytes()
    for name in ('LICENSE','THIRD_PARTY_NOTICES.md'):
        if (root/name).is_file():files[name]=(root/name).read_bytes()
    files['.github/workflows/tests.yml']=b'''name: Tests
on: [push, pull_request]
permissions:
  contents: read
jobs:
  tests:
    runs-on: windows-latest
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: '3.12'
      - run: python -m pip install -r requirements.txt -r requirements-dev.txt
      - run: python -m pytest tests -q
      - run: python tools/build_public_repo.py
'''
    return files


def build(root=ROOT):
    root=Path(root).resolve()
    files=repository_files(root)
    target=root/'dist'/'pinspector-repository'
    # Refuse to overwrite a previous export or a reviewer-modified checkout.
    if target.exists():raise FileExistsError(f'Export already exists: {target}')
    target.mkdir(parents=True)
    for name,data in files.items():
        path=target/name;path.parent.mkdir(parents=True,exist_ok=True);path.write_bytes(data)
    manifest={n:hashlib.sha256(data).hexdigest() for n,data in sorted(files.items())}
    (root/'dist'/'pinspector-repository-manifest.json').write_text(json.dumps(manifest,indent=2),encoding='utf-8')
    print(f'Exported {len(files)} public source files to {target}')
    if 'LICENSE' not in files:print('Draft only: license decision is pending. Nothing was published.')
    return target


if __name__=='__main__':build()
