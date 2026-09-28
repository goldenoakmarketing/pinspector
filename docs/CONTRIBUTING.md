# Contributing

This is a Windows-first local research application. Keep evidence, interpretation,
and uncertainty separate. A possible name connection must never become proof of
shared ownership or a false location.

## Development

Use Python 3.12 on Windows:

```powershell
python -m venv .venv
.venv\Scripts\python.exe -m pip install -r requirements.txt
.venv\Scripts\python.exe -m pip install -r requirements-dev.txt
.venv\Scripts\python.exe -m pytest tests -q
```

Run `Start PinSpector.cmd` to open the app. Tests use synthetic fixtures;
do not commit real investigation databases, captures, customer information, logs,
API keys, model weights, or personal runtime paths. Live Maps collection is
experimental and is not exercised by the unit-test CI workflow.

Include regression tests for changes to matching, attribution, network access,
secret handling, and release packaging. Preserve source provenance and make
incomplete collection visible. Name candidates must not seed identifier networks.

## Distribution

Run `python tools/build_public_repo.py` from the project root to create a clean
source export in `dist/pinspector-repository`. This copies only allowlisted inputs;
it does not copy Git history or publish anything. Review the generated file
manifest before uploading. Contributions to this project are under GPL-3.0-only.
