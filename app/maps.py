"""Small, visible-browser Maps collector. Experimental selectors, no API fees.
Stops at CAPTCHA/consent/access gates. No accounts, profiles, proxies, or stealth.
"""
from __future__ import annotations
import re
import os
import time
from urllib.parse import quote,urlsplit,urljoin
from .net import normalize_url, public_addresses, UnsafeURL

class DiscoveryError(Exception): pass


def browser_launch(p,headless=False):
    errors=[]
    for channel in ('msedge','chrome',None):
        try:
            kwargs={'headless':headless,'timeout':15000}
            if channel: kwargs['channel']=channel
            return p.chromium.launch(**kwargs)
        except Exception as e: errors.append(str(e).splitlines()[0])
    raise DiscoveryError('No compatible browser could start. Close a failed browser window and run Install Browser.cmd. '+ '; '.join(errors)[:280])


def discover(category: str, city: str, state: str, limit: int, report, cancelled, headless=False) -> list[dict]:
    from .storage import DATA
    os.environ['PLAYWRIGHT_BROWSERS_PATH']=str(DATA/'browser')
    try: from playwright.sync_api import sync_playwright
    except ImportError as e: raise DiscoveryError('Playwright is not installed. Run Start PinSpector.cmd again.') from e
    query=f'{category} in {city}, {state}, United States'
    url='https://www.google.com/maps/search/'+quote(query,safe='')+'?hl=en'
    results=[]; deadline=time.monotonic()+max(100,limit*14)
    with sync_playwright() as p:
        browser=browser_launch(p,headless)
        context=browser.new_context(locale='en-US',viewport={'width':1280,'height':900},accept_downloads=False,service_workers='block')
        def gate(route):
            # Maps collection has a narrow Google-only origin allowlist; external
            # business sites are later fetched by the IP-pinned HTTP collector.
            u=urlsplit(route.request.url)
            host=(u.hostname or '').lower()
            allowed=any(host==d or host.endswith('.'+d) for d in ('google.com','gstatic.com','googleapis.com','googleusercontent.com','ggpht.com'))
            if u.scheme not in ('http','https') or not allowed:
                route.abort(); return
            try: public_addresses(host,u.port or (443 if u.scheme=='https' else 80))
            except Exception: route.abort(); return
            route.continue_()
        context.route('**/*',gate)
        page=context.new_page(); page.set_default_timeout(6000)
        def blocked():
            text=page.locator('body').inner_text(timeout=4000)[:14000].lower()
            return any(s in text for s in ('unusual traffic','verify you are human','before you continue to google','our systems have detected','access denied'))
        try:
            report('Opening public Maps results in a separate browser. No Google sign-in is used.')
            page.goto(url,wait_until='domcontentloaded',timeout=30000)
            page.wait_for_timeout(2200)
            if blocked(): raise DiscoveryError('Maps displayed a consent, CAPTCHA, or access gate. Collection stopped; no bypass was attempted. Website-input mode remains available.')
            links={}; stagnant=0
            for _ in range(8):
                if cancelled() or time.monotonic()>deadline: break
                for x in page.locator('a[href*="/maps/place/"]').evaluate_all('(els)=>els.map(e=>({url:e.href,name:e.getAttribute("aria-label")||e.textContent||""}))'):
                    if x['url'].startswith('https://www.google.com/maps/place/'):
                        links.setdefault(x['url'],x['name'].strip())
                if len(links)>=limit: break
                feed=page.locator('[role="feed"]').first
                if not feed.count(): break
                before=len(links); feed.evaluate('(e)=>e.scrollBy(0,1300)'); page.wait_for_timeout(1000)
                stagnant=stagnant+1 if len(links)==before else 0
                if stagnant>=4: break
            if not links and '/maps/place/' in page.url: links[page.url]=''
            if not links: raise DiscoveryError('Maps returned no readable profile links. This can be a source-layout or access issue, not an empty market. Use Website URLs mode or retry after checking the browser.')
            report(f'Found {min(limit,len(links))} candidate profiles; reading their visible business details.')
            for i,(link,fallback) in enumerate(list(links.items())[:limit]):
                if cancelled() or time.monotonic()>deadline: break
                try:
                    page.goto(link,wait_until='domcontentloaded',timeout=25000); page.wait_for_timeout(850)
                    if blocked():
                        report('Maps access gate encountered; keeping only the profiles already collected.'); break
                    h=page.locator('h1').first
                    name=h.inner_text(timeout=4000).strip() if h.count() else fallback
                    site=page.locator('a[data-item-id="authority"]').first
                    website=site.get_attribute('href') if site.count() else ''
                    if website:
                        try: website=normalize_url(website)
                        except UnsafeURL: website=''
                    phone_el=page.locator('button[data-item-id^="phone:"]').first
                    phone=phone_el.get_attribute('aria-label') if phone_el.count() else ''
                    address_el=page.locator('button[data-item-id="address"]').first
                    address=address_el.get_attribute('aria-label') if address_el.count() else ''
                    # Absence of the selector is UNKNOWN, not definitely hidden.
                    results.append({'name':name or fallback or 'Unnamed profile','profile_url':link,
                       'website':website or '', 'phone':re.sub(r'^Phone:\s*','',phone or ''),
                       'address':re.sub(r'^Address:\s*','',address or ''),'address_state':'displayed' if address else 'unknown',
                       'source':'public_maps_visible_browser'})
                    report(f'Collected profile {len(results)}: {name or fallback}')
                except Exception as e:
                    report('A profile could not be read: '+str(e).splitlines()[0][:180])
            if not results: raise DiscoveryError('No profile details could be collected. Source structure/access needs live verification.')
            return results
        finally:
            context.close(); browser.close()
