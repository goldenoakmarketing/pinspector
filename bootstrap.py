"""Windows-friendly self-contained launcher. No admin rights or token prompts.
Only this folder's .venv, data, and child process are touched.
"""
from __future__ import annotations
import argparse
import contextlib
import hashlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import time
import urllib.error
import urllib.request
import webbrowser

ROOT=Path(__file__).resolve().parent
PORT=int(os.environ.get('BV_PORT','8768'))
BASE=f'http://127.0.0.1:{PORT}'
APP_ID='business-validator-hp-local'
INSTANCE=hashlib.sha256(str(ROOT).encode()).hexdigest()[:16]


def request(path,post=False):
    # Ignore system proxy settings for loopback traffic.
    op=urllib.request.build_opener(urllib.request.ProxyHandler({}))
    req=urllib.request.Request(BASE+path,data=b'{}' if post else None,
          headers={'Content-Type':'application/json','X-BV-Local':'1'})
    with op.open(req,timeout=2) as r: return json.load(r)


def health():
    try: return request('/api/health')
    except Exception: return None


def port_busy():
    with socket.socket(socket.AF_INET,socket.SOCK_STREAM) as sock:
        sock.settimeout(.8)
        return sock.connect_ex(('127.0.0.1',PORT))==0


def venv_python():
    return ROOT/'.venv'/('Scripts/python.exe' if os.name=='nt' else 'bin/python')


def install():
    if sys.version_info<(3,10): raise RuntimeError('Python 3.10 or newer is required. Install a supported Python from python.org, then run this launcher again.')
    py=venv_python()
    if not py.exists():
        print('Creating a private Python environment in this application folder...',flush=True)
        subprocess.run([sys.executable,'-m','venv',str(ROOT/'.venv')],check=True)
    req=ROOT/'requirements.txt'; digest=hashlib.sha256(req.read_bytes()).hexdigest()
    stamp=ROOT/'.venv'/'.bv-requirements'
    probe=subprocess.run([str(py),'-c','import fastapi,uvicorn,httpx,bs4,pydantic,playwright'],capture_output=True)
    if not stamp.exists() or stamp.read_text()!=digest or probe.returncode:
        print('Installing the application dependencies into its private environment. Existing apps and models are not modified.',flush=True)
        subprocess.run([str(py),'-m','pip','install','--disable-pip-version-check','-r',str(req)],check=True,cwd=ROOT)
        stamp.write_text(digest)
    return py


@contextlib.contextmanager
def startup_lock():
    """Serialize setup/launch attempts from this folder, including double clicks."""
    handle=(ROOT/'.startup.lock').open('a+b')
    locked=False
    try:
        handle.seek(0,2)
        if handle.tell()==0: handle.write(b'0');handle.flush()
        handle.seek(0)
        try:
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_NBLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_EX|fcntl.LOCK_NB)
            locked=True
        except OSError:
            print('Setup/startup is already in progress for this folder. No duplicate process was started.',flush=True)
        yield locked
    finally:
        if locked:
            handle.seek(0)
            if os.name=='nt':
                import msvcrt
                msvcrt.locking(handle.fileno(),msvcrt.LK_UNLCK,1)
            else:
                import fcntl
                fcntl.flock(handle.fileno(),fcntl.LOCK_UN)
        handle.close()


def main():
    parser=argparse.ArgumentParser(); parser.add_argument('--stop',action='store_true');parser.add_argument('--diagnostics',action='store_true');parser.add_argument('--install-browser',action='store_true');parser.add_argument('--no-browser',action='store_true')
    args=parser.parse_args()
    if not (ROOT/'app'/'server.py').exists():
        raise RuntimeError('Extract the ENTIRE ZIP first. Do not run the launcher from inside the ZIP preview.')
    if args.diagnostics:
        print('PinSpector local diagnostics\nFolder:',ROOT,'\nPython:',sys.executable,'\nVersion:',sys.version,'\nHealth:',health(),'\nPort occupied:',port_busy())
        print('Logs:',ROOT/'data'/'logs')
        return
    existing=health()
    if args.stop:
        if not existing: print('PinSpector is not running on this port. No process was killed.');return
        if existing.get('app')!=APP_ID or existing.get('instance')!=INSTANCE:
            raise RuntimeError('The port belongs to a different application/folder. Nothing was stopped.')
        print(request('/api/shutdown',True)['message']);return
    if args.install_browser:
        py=install();print('Installing the isolated Playwright Chromium browser. Your personal browser profile is not used.',flush=True)
        browser_env=os.environ.copy();browser_env['PLAYWRIGHT_BROWSERS_PATH']=str(ROOT/'data'/'browser')
        subprocess.run([str(py),'-m','playwright','install','chromium'],check=True,cwd=ROOT,env=browser_env);return
    if existing:
        if existing.get('app')==APP_ID and existing.get('instance')==INSTANCE:
            print('Already running. Opening its dashboard; no duplicate worker was started.')
            if not args.no_browser:webbrowser.open(BASE)
            return
        raise RuntimeError(f'Port {PORT} belongs to a different application or copy of this tool. Nothing was stopped. Close the other copy or set BV_PORT to a free port.')
    if port_busy(): raise RuntimeError(f'Port {PORT} is already in use. No unrelated process was stopped.')
    py=install()
    logs=ROOT/'data'/'logs';logs.mkdir(parents=True,exist_ok=True)
    logfile=logs/'launcher.log'
    cmd=[str(py),'-m','app.server']
    flags=0
    if os.name=='nt': flags=subprocess.CREATE_NO_WINDOW
    print('Starting PinSpector on',BASE,flush=True)
    env=os.environ.copy();env['PYTHONUNBUFFERED']='1';env['PYTHONIOENCODING']='utf-8'
    with logfile.open('a',encoding='utf-8') as out:
        proc=subprocess.Popen(cmd,cwd=ROOT,stdout=out,stderr=subprocess.STDOUT,env=env,creationflags=flags)
    for _ in range(80):
        status=health()
        if status and status.get('app')==APP_ID and status.get('instance')==INSTANCE:
            print('Dashboard is ready. Local data:',ROOT/'data')
            if not args.no_browser:webbrowser.open(BASE)
            return
        if proc.poll() is not None:break
        time.sleep(.25)
    # We only terminate the specific child launched here, never a name/PID search.
    if proc.poll() is None:
        proc.terminate()
        try:proc.wait(timeout=5)
        except subprocess.TimeoutExpired:proc.kill()
    tail=logfile.read_text(encoding='utf-8',errors='replace')[-6000:]
    raise RuntimeError('The dashboard did not become healthy. Startup log:\n'+tail+'\nFull log: '+str(logfile))

if __name__=='__main__':
    try:
        with startup_lock() as acquired:
            if acquired: main()
    except Exception as e:
        print('\nSTARTUP ERROR:',e,file=sys.stderr,flush=True)
        sys.exit(1)
