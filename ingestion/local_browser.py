"""Bounded Chrome collection for NH, NJ and SEC; never publishes results itself.

Chrome uses a new nonpersistent context, JavaScript disabled and strict TLS.
CDP pauses every page request before network: only one approved main-frame GET
is permitted per navigation. Redirect hops, frames and subresources are blocked.
No browser profile, credentials, custom user agent or proxy is supplied.
"""
from __future__ import annotations

import argparse
from dataclasses import asdict
from datetime import date,datetime,timezone
import json
import math
import os
from pathlib import Path
import re
import sys
import tempfile
import time
from urllib.parse import parse_qsl, urlsplit

from .models import SourceError
from .network import Response
from .runner import atomic_json, decode_collection, read_json, supervise
from .validation import timestamp

LOCAL_SOURCES = ('new_hampshire', 'new_jersey', 'sec')
TRANSPORT = 'local_headed_chrome_javascript_disabled'
_CHALLENGE = re.compile(rb'<title[^>]*>\s*(?:Access Denied|Request Rejected|Just a moment)|Request unsuccessful\. Incapsula|Your Request Originates from an Undeclared Automated Tool', re.I)


def transport_context():
    """Describe execution only; never change browser/network behavior."""
    if os.environ.get('GITHUB_ACTIONS') == 'true':
        runner = os.environ.get('RUNNER_OS')
        runner = runner if runner in ('Linux', 'macOS', 'Windows') else 'unspecified'
        return ({'transport': 'github_actions_headed_chrome_javascript_disabled',
                 'executionEnvironment': 'github_actions', 'runnerOS': runner},
                f' Collected in GitHub Actions ({runner}) in a fresh ordinary headed Chrome session with JavaScript disabled.')
    return ({'transport': TRANSPORT, 'executionEnvironment': 'local'},
            ' Collected locally in a fresh ordinary Chrome session with JavaScript disabled; this does not establish GitHub runner access.')


def approved_url(source, url):
    if not isinstance(url, str) or any(ord(c) < 33 for c in url):
        raise SourceError('Local browser URL has invalid characters')
    try:
        parts = urlsplit(url)
        pairs = parse_qsl(parts.query, keep_blank_values=True, strict_parsing=True)
        query = dict(pairs)
        safe = (parts.scheme == 'https' and not parts.username and not parts.password
                and parts.port in (None, 443) and not parts.fragment and len(query) == len(pairs))
        if source == 'new_hampshire':
            fixed = {'iterate_nodes': 'true', 'q': '@field_document_category|=|2146', 'textsearch': '',
                     'sort': 'field_date_posted|desc|ALLOW_NULLS', 'filter_mode': 'inclusive', 'type': 'document', 'size': '25'}
            safe = safe and parts.hostname == 'www.doj.nh.gov' and parts.path == '/content/api/documents'
            safe = safe and set(query) == {*fixed, 'page'} and all(query.get(k) == v for k,v in fixed.items())
            safe = safe and query.get('page', '').isdigit() and 1 <= int(query['page']) <= 200
        elif source == 'new_jersey':
            from .rediscovered_nj import listing_identity
            safe = safe and parts.hostname == 'www.cyber.nj.gov' and not parts.query
            base='/threat-landscape/public-data-breaches'
            safe = safe and (parts.path == base or parts.path.startswith(base+'/'))
            if safe: listing_identity(url)
        elif source == 'sec':
            safe = safe and parts.hostname == 'efts.sec.gov' and parts.path == '/LATEST/search-index'
            safe = safe and set(query) == {'dateRange','category','forms','startdt','enddt','from'}
            safe = safe and query.get('dateRange') == 'custom' and query.get('category') == 'custom' and query.get('forms') == '8-K'
            start, end = date.fromisoformat(query.get('startdt','')), date.fromisoformat(query.get('enddt',''))
            safe = safe and 0 <= (end - start).days <= 30 and end <= datetime.now(timezone.utc).date()
            safe = safe and query.get('from','').isdigit() and 0 <= int(query['from']) <= 9900 and int(query['from']) % 100 == 0
        else:
            safe = False
    except (ValueError, SourceError):
        safe = False
    if not safe:
        raise SourceError('URL is outside this local collector’s exact public source paths and query contract')
    return parts.hostname, parts.path, tuple(sorted(pairs))


class LocalBrowserClient:
    def __init__(self, source, *, max_requests=205, max_bytes=35_000_000, deadline_seconds=600,
                 max_response_bytes=6_000_000):
        if source not in LOCAL_SOURCES:
            raise SourceError('Unknown local browser source')
        if any(type(v) is not int or v <= 0 for v in (max_requests,max_bytes,max_response_bytes)):
            raise SourceError('Local browser request/byte budgets must be positive integers')
        if not isinstance(deadline_seconds,(int,float)) or not math.isfinite(deadline_seconds) or deadline_seconds <= 0:
            raise SourceError('Local browser deadline must be finite and positive')
        self.source, self.max_requests, self.max_bytes = source, max_requests, max_bytes
        self.max_response_bytes = max_response_bytes
        self.requests = self.bytes = 0
        self.deadline = time.monotonic() + deadline_seconds
        self._last = None
        self._manager = self._browser = self._context = self._page = self._cdp = None
        self._frame = self._expected = None
        self._seen_document = False
        self._request_bytes = 0
        self._request_deadline = self.deadline
        self._failure = None
        self._closed = False

    def _remaining(self):
        if self._closed: raise SourceError('Local browser client is closed')
        if self._failure: raise SourceError(self._failure)
        remaining = min(self.deadline,self._request_deadline) - time.monotonic()
        if remaining <= 0: raise SourceError('Local browser time budget exhausted')
        return remaining

    def _stop(self, message):
        self._failure = self._failure or message
        if self._cdp:
            try: self._cdp.send('Page.stopLoading')
            except Exception: pass

    def _paused(self, event):
        request = event['request']
        allow = False
        try:
            main_document = event.get('resourceType') == 'Document' and event.get('frameId') == self._frame
            if main_document and (self._seen_document or event.get('redirectedRequestId')):
                self._failure = 'Local browser blocked a redirect or additional document navigation before network'
            elif main_document and self._expected is not None and request.get('method') == 'GET':
                allow = approved_url(self.source,request['url']) == self._expected
                self._remaining()
                allow = allow and not any(k.lower() in ('authorization','proxy-authorization','cookie') for k in request.get('headers',{}))
            if allow:
                self._seen_document = True
                self._cdp.send('Fetch.continueRequest',{'requestId':event['requestId']})
                return
        except SourceError:
            pass
        self._cdp.send('Fetch.failRequest',{'requestId':event['requestId'],'errorReason':'BlockedByClient'})

    def _auth(self, event):
        self._failure = 'Local browser stopped at an authentication request'
        self._cdp.send('Fetch.continueWithAuth',{'requestId':event['requestId'], 'authChallengeResponse':{'response':'CancelAuth'}})

    def _received(self, event):
        length = event.get('dataLength',0)
        if isinstance(length,(int,float)) and length > 0:
            self._request_bytes += int(length); self.bytes += int(length)
        if self._request_bytes > self.max_response_bytes or self.bytes > self.max_bytes:
            self._stop('Local browser byte budget exhausted')
        elif time.monotonic() >= min(self.deadline,self._request_deadline):
            self._stop('Local browser time budget exhausted')

    def _start(self):
        if self._context is not None: return
        try:
            from playwright.sync_api import sync_playwright
        except ImportError as exc:
            raise SourceError('Optional browser dependencies are missing; install requirements-browser.lock') from exc
        try:
            self._manager = sync_playwright().start()
            # A fresh hosted Chrome can exceed 15 seconds before its first request.
            # Startup shares the worker budget; each later navigation still has 30s.
            self._browser = self._manager.chromium.launch(channel='chrome',headless=False,timeout=min(60000,int(self._remaining()*1000)))
            self._context = self._browser.new_context(java_script_enabled=False,service_workers='block',
                                                      accept_downloads=False,ignore_https_errors=False)
        except Exception as exc:
            self.close()
            raise SourceError(f'Local Chrome could not start ({type(exc).__name__})') from exc

    def _prepare_page(self):
        self._context.clear_cookies()
        self._page = self._context.new_page()
        self._cdp = self._context.new_cdp_session(self._page)
        self._frame = self._cdp.send('Page.getFrameTree')['frameTree']['frame']['id']
        self._cdp.on('Fetch.requestPaused',self._paused)
        self._cdp.on('Fetch.authRequired',self._auth)
        self._cdp.on('Network.dataReceived',self._received)
        self._cdp.send('Network.enable')
        self._cdp.send('Network.setCacheDisabled',{'cacheDisabled':True})
        self._cdp.send('Fetch.enable',{'patterns':[{'urlPattern':'*','requestStage':'Request'}], 'handleAuthRequests':True})

    def request(self, url, *, data=None, headers=None):
        expected = approved_url(self.source,url)
        if data is not None or headers:
            raise SourceError('Local browser permits GET with ordinary browser headers only')
        self._request_deadline = self.deadline
        self._remaining()
        if self.requests >= self.max_requests: raise SourceError('Local browser request budget exhausted')
        if self._last is not None:
            pause = max(0,1 - (time.monotonic()-self._last))
            if pause >= self._remaining(): raise SourceError('Local browser time budget exhausted')
            time.sleep(pause)
        self._start()
        self._expected = expected
        self._seen_document = False
        self._request_bytes = 0
        self._request_deadline = min(self.deadline,time.monotonic()+30)
        self._last = time.monotonic()
        self.requests += 1
        before = self.bytes
        try:
            self._prepare_page()
            response = self._page.goto(url,wait_until='domcontentloaded',timeout=max(1,int(self._remaining()*1000)))
            self._remaining()
            if response is None: raise SourceError('Local browser navigation had no response')
            if response.status != 200:
                self._stop(f'HTTP {response.status}; local browser stopped without retry')
                raise SourceError(self._failure)
            if approved_url(self.source,response.url) != expected:
                raise SourceError('Local browser returned an unexpected publication URL')
            content_type = response.headers.get('content-type','')
            if not any(kind in content_type.lower() for kind in ('json','html')):
                raise SourceError('Local browser supports only public JSON/HTML listings; downloads are not collected')
            content = response.body()
            self._remaining()
            self.bytes = max(self.bytes,before+len(content))
            if not content or len(content) > self.max_response_bytes or self.bytes > self.max_bytes:
                self._stop('Local browser returned an empty or oversized response')
                raise SourceError(self._failure)
            if _CHALLENGE.search(content) or (b'_Incapsula_Resource' in content and len(content)<5000):
                self._stop('Local browser received an access challenge; no challenge was solved')
                raise SourceError(self._failure)
            return Response(response.url,content,content_type)
        except SourceError:
            raise
        except Exception as exc:
            self._remaining()
            raise SourceError(f'Local browser navigation failed ({type(exc).__name__}); no retry attempted') from exc
        finally:
            self._expected = None
            if self._page:
                try: self._page.close()
                except Exception: pass
            self._page = self._cdp = None

    def close(self):
        self._closed = True
        for name,method in [('_context','close'),('_browser','close'),('_manager','stop')]:
            resource = getattr(self,name)
            if resource:
                try: getattr(resource,method)()
                except Exception: pass
                setattr(self,name,None)


def collect_local(source, *, max_pages=None):
    if source not in LOCAL_SOURCES: raise SourceError('Unknown local browser source')
    if source == 'new_jersey':
        from .rediscovered_nj import collect
        result = collect(source,max_pages=max_pages,client_factory=lambda **kw:LocalBrowserClient(source,**kw),
                         today=datetime.now(timezone.utc).date())
    else:
        client = LocalBrowserClient(source)
        try:
            if source == 'new_hampshire':
                from .rediscovered_northeast import collect_nh_documents
                result = collect_nh_documents(client,max_pages=max_pages,today=datetime.now(timezone.utc).date())
            else:
                from .rediscovered_sec import collect_with_client
                result = collect_with_client(client,max_pages=max_pages,today=datetime.now(timezone.utc).date())
            result.evidence.update({'requests':client.requests,'bytes':client.bytes})
        finally: client.close()
    evidence, message = transport_context()
    result.evidence.update(evidence)
    result.message += message
    return result


def fetch(source, output, *, timeout=600, max_pages=None):
    if source not in LOCAL_SOURCES or not math.isfinite(timeout) or not 0 < timeout <= 900:
        raise ValueError('Choose an approved local source and a deadline in (0,900] seconds')
    envelope={'schemaVersion':1,'sourceId':source,'attemptedAt':timestamp()}
    try:
        with tempfile.TemporaryDirectory(prefix='breach-local-browser-') as directory:
            result_path=Path(directory)/'worker.json'
            command=[sys.executable,'-m','ingestion.local_browser','_worker','--source',source,'--output',str(result_path)]
            if max_pages is not None: command += ['--max-pages',str(max_pages)]
            status=supervise(command,timeout=timeout)
            value=read_json(result_path) if result_path.is_file() else {}
            if status != 0 or value.get('error') or 'collection' not in value:
                raise SourceError(str(value.get('error',f'Local browser worker exited {status} without a collection')))
            collection=decode_collection(value['collection'],source)
            envelope['collection']=asdict(collection)
            code=0 if collection.complete and not collection.rejected and (collection.reports or collection.empty_is_valid) else 1
    except Exception as exc:
        envelope['error']=f'{type(exc).__name__}: {exc}'[:2000];code=1
    envelope['completedAt']=timestamp();atomic_json(Path(output),envelope)
    print(f'{source}: browser result artifact saved to {output}; this command does not publish')
    return code


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command',choices=('fetch','_worker'))
    parser.add_argument('--source',choices=LOCAL_SOURCES,required=True)
    parser.add_argument('--output',type=Path,required=True)
    parser.add_argument('--max-pages',type=int)
    parser.add_argument('--timeout',type=float,default=600)
    args=parser.parse_args(argv)
    if args.command=='fetch': return fetch(args.source,args.output,timeout=args.timeout,max_pages=args.max_pages)
    try:
        result=collect_local(args.source,max_pages=args.max_pages)
        atomic_json(args.output,{'collection':asdict(result)});return 0
    except Exception as exc:
        atomic_json(args.output,{'error':f'{type(exc).__name__}: {exc}'[:2000]});return 1


if __name__=='__main__':raise SystemExit(main())
