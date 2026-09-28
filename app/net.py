"""Public HTTP only: resolve and pin public addresses; revalidate redirects.
No proxy environment, credentials, local-network crawling, or bypass attempts.
"""
from __future__ import annotations
import http.client
import ipaddress
import socket
import ssl
import time
import urllib.parse
import urllib.robotparser
from dataclasses import dataclass

UA='BusinessEvidenceResearch/0.1 (+bounded-public-source-research)'
MAX_BYTES=2_500_000

class FetchError(Exception): pass
class UnsafeURL(FetchError): pass

@dataclass
class Fetched:
    requested: str
    url: str
    status: int
    content: bytes
    content_type: str
    @property
    def text(self):
        # Most sites are UTF-8; preserve raw bytes separately for audit.
        return self.content.decode('utf-8',errors='replace')

def normalize_url(url: str) -> str:
    url=url.strip()
    if not url: raise UnsafeURL('Empty website URL.')
    if not urllib.parse.urlsplit(url).scheme:
        url='https://'+url
    p=urllib.parse.urlsplit(url)
    if p.scheme not in ('http','https') or not p.hostname or p.username or p.password:
        raise UnsafeURL('Only public http/https URLs without credentials are allowed.')
    try: port=p.port
    except ValueError: raise UnsafeURL('Invalid URL port.')
    if port not in (None,80,443): raise UnsafeURL('Website collection is limited to ports 80 and 443.')
    host=p.hostname.encode('idna').decode('ascii').lower().rstrip('.')
    if '%' in host or '\\' in url or any(ord(c)<32 for c in url): raise UnsafeURL('Invalid URL.')
    netloc=f'[{host}]' if ':' in host else host
    if port: netloc+=':'+str(port)
    path=urllib.parse.quote(urllib.parse.unquote(p.path or '/'),safe="/:@!$&'()*+,;=-._~")
    return urllib.parse.urlunsplit((p.scheme,netloc,path,p.query,''))

def public_addresses(host: str, port: int) -> list[str]:
    try:
        addresses=list(dict.fromkeys(r[4][0] for r in socket.getaddrinfo(host,port,type=socket.SOCK_STREAM)))
    except OSError as e: raise FetchError(f'DNS lookup failed for {host}: {e}') from e
    if not addresses: raise UnsafeURL('No public address found.')
    for value in addresses:
        ip=ipaddress.ip_address(value)
        if not ip.is_global or ip.is_multicast or ip.is_unspecified:
            raise UnsafeURL('Private, loopback, reserved, and mixed public/private targets are blocked.')
        if getattr(ip,'ipv4_mapped',None) and not ip.ipv4_mapped.is_global:
            raise UnsafeURL('Mapped private address is blocked.')
    return addresses

class PinnedHTTP(http.client.HTTPConnection):
    def __init__(self,host,port,ip,timeout):
        super().__init__(host,port,timeout=timeout); self.ip=ip
    def connect(self):
        self.sock=socket.create_connection((self.ip,self.port),self.timeout)

class PinnedHTTPS(http.client.HTTPSConnection):
    def __init__(self,host,port,ip,timeout):
        super().__init__(host,port,timeout=timeout,context=ssl.create_default_context()); self.ip=ip
    def connect(self):
        sock=socket.create_connection((self.ip,self.port),self.timeout)
        try: self.sock=self._context.wrap_socket(sock,server_hostname=self.host)
        except Exception: sock.close(); raise

def fetch(url: str, limit=MAX_BYTES, timeout=12, max_redirects=5, allow_redirect=None) -> Fetched:
    requested=normalize_url(url); current=requested
    deadline=time.monotonic()+max(15,timeout*2)
    for _ in range(max_redirects+1):
        p=urllib.parse.urlsplit(current); port=p.port or (443 if p.scheme=='https' else 80)
        ips=public_addresses(p.hostname,port)
        conn=None; last=None
        for ip in ips[:2]:
            if time.monotonic()>deadline: raise FetchError('Fetch time budget exceeded.')
            cls=PinnedHTTPS if p.scheme=='https' else PinnedHTTP
            conn=cls(p.hostname,port,ip,timeout)
            try:
                conn.request('GET',urllib.parse.urlunsplit(('', '',p.path or '/',p.query,'')),
                    headers={'User-Agent':UA,'Accept':'text/html,text/plain;q=0.9,*/*;q=0.1','Accept-Encoding':'identity'})
                res=conn.getresponse(); break
            except (OSError,http.client.HTTPException) as e:
                conn.close(); last=e
        else: raise FetchError(f'Connection failed: {last}')
        try:
            if res.status in (301,302,303,307,308):
                loc=res.getheader('Location')
                if not loc: raise FetchError('Redirect has no target.')
                target=normalize_url(urllib.parse.urljoin(current,loc))
                if allow_redirect is not None and not allow_redirect(target):
                    raise FetchError('Redirect target is not approved by robots.txt; target not fetched.')
                current=target; continue
            if res.status in (401,403,407,429):
                raise FetchError(f'Access/rate limit response {res.status}; no bypass attempted.')
            declared=res.getheader('Content-Length')
            if declared and declared.isdigit() and int(declared)>limit: raise FetchError('Page exceeds collection size limit.')
            if res.getheader('Content-Encoding','identity').lower() not in ('identity',''):
                raise FetchError('Unexpected compressed response; collection skipped.')
            chunks=[]; count=0
            while True:
                if time.monotonic()>deadline: raise FetchError('Fetch time budget exceeded.')
                part=res.read(min(65536,limit+1-count))
                if not part: break
                count+=len(part)
                if count>limit: raise FetchError('Page exceeds collection size limit.')
                chunks.append(part)
            content=b''.join(chunks)
            return Fetched(requested,current,res.status,content,res.getheader('Content-Type',''))
        except (OSError,http.client.HTTPException) as e: raise FetchError(str(e)) from e
        finally: conn.close()
    raise FetchError('Redirect limit reached.')

class PoliteFetcher:
    def __init__(self):
        self.robots={}; self.last={}
    def allowed(self,url):
        p=urllib.parse.urlsplit(url); origin=f'{p.scheme}://{p.netloc}'
        if origin not in self.robots:
            try:
                r=fetch(origin+'/robots.txt',limit=256_000,timeout=8)
                if r.status in (404,410): self.robots[origin]=(None,True)
                elif 200<=r.status<300:
                    parser=urllib.robotparser.RobotFileParser(); parser.parse(r.text.splitlines())
                    self.robots[origin]=(parser,True)
                else: self.robots[origin]=(None,False)
            except FetchError: self.robots[origin]=(None,False)
        parser,ok=self.robots[origin]
        return ok and (parser is None or parser.can_fetch(UA,url))
    def get(self,url):
        url=normalize_url(url)
        if not self.allowed(url): raise FetchError('robots.txt disallows this path or could not be verified.')
        host=urllib.parse.urlsplit(url).netloc
        delay=1.2-(time.monotonic()-self.last.get(host,0))
        if delay>0: time.sleep(delay)
        self.last[host]=time.monotonic()
        result=fetch(url,allow_redirect=self.allowed)
        # Redirect target requires its own robots permission before any retained use.
        if result.url!=url and not self.allowed(result.url):
            raise FetchError('Redirect target is not approved by robots.txt; capture discarded.')
        return result
