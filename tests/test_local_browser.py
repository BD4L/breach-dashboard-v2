"""Pure boundary tests plus opt-in real Chrome redirect/subresource proof."""
from collections import Counter
from datetime import date,datetime,timedelta,timezone
from http.server import BaseHTTPRequestHandler,ThreadingHTTPServer
import json
import os
from pathlib import Path
import tempfile
from threading import Thread
import unittest
from unittest.mock import Mock,patch
from urllib.parse import urlsplit

from ingestion import local_browser as p
from ingestion.models import Collection,Report,SourceError
from ingestion.rediscovered_northeast import nh_api_url
from ingestion.rediscovered_sec import search_url
from ingestion.rediscovered_nj import HOMEPAGE
from ingestion import rediscovered_nj as nj


class BoundaryTests(unittest.TestCase):
    def test_only_actual_publication_paths_and_fixed_queries_are_allowed(self):
        today=datetime.now(timezone.utc).date()
        urls={'new_hampshire':nh_api_url(1),'new_jersey':HOMEPAGE,
              'sec':search_url(today-timedelta(days=30),today,100)}
        for source,url in urls.items():
            p.approved_url(source,url)
            for bad in (url.replace('https:','http:'),url.replace('https://','https://name:password@'),url+'#section',url+'&extra=1',url+'\n'):
                with self.subTest(source=source,bad=bad),self.assertRaises(SourceError):p.approved_url(source,bad)
        for url in (nh_api_url(1).replace('2146','9999'),nh_api_url(201),nh_api_url(1).replace('size=25','size=500')):
            with self.assertRaises(SourceError):p.approved_url('new_hampshire',url)

    def test_bad_method_headers_and_url_fail_before_browser_start(self):
        client=p.LocalBrowserClient('new_hampshire')
        with patch.object(client,'_start') as start:
            for kwargs in ({'data':'body'},{'headers':{'Authorization':'secret'}},{'headers':{'User-Agent':'other'}}):
                with self.assertRaises(SourceError):client.request(nh_api_url(1),**kwargs)
            with self.assertRaises(SourceError):client.request('https://example.invalid/')
            start.assert_not_called()

    def test_cdp_allows_one_main_get_and_blocks_redirect_before_continue(self):
        client=p.LocalBrowserClient('new_hampshire');client._cdp=Mock();client._frame='main'
        client._expected=p.approved_url('new_hampshire',nh_api_url(1))
        event={'requestId':'a','frameId':'main','resourceType':'Document','request':{'method':'GET','url':nh_api_url(1),'headers':{}}}
        client._paused(event)
        client._cdp.send.assert_called_once_with('Fetch.continueRequest',{'requestId':'a'})
        event.update(requestId='b',redirectedRequestId='a')
        client._paused(event)
        self.assertEqual(client._cdp.send.call_args.args[0],'Fetch.failRequest')
        with self.assertRaisesRegex(SourceError,'redirect'):client._remaining()

    def test_cdp_blocks_frames_assets_and_auth_without_credentials(self):
        for frame,kind in [('child','Document'),('main','Image'),('main','Script')]:
            client=p.LocalBrowserClient('new_hampshire');client._cdp=Mock();client._frame='main'
            client._expected=p.approved_url('new_hampshire',nh_api_url(1))
            client._paused({'requestId':'a','frameId':frame,'resourceType':kind,'request':{'method':'GET','url':nh_api_url(1),'headers':{}}})
            client._cdp.send.assert_called_once_with('Fetch.failRequest',{'requestId':'a','errorReason':'BlockedByClient'})
        client._auth({'requestId':'auth'})
        self.assertEqual(client._cdp.send.call_args.args[1]['authChallengeResponse'],{'response':'CancelAuth'})

    def test_byte_and_request_limits_stop_without_starting_another_navigation(self):
        client=p.LocalBrowserClient('new_hampshire',max_response_bytes=10);client._cdp=Mock()
        client._received({'dataLength':11})
        with self.assertRaisesRegex(SourceError,'byte budget'):client.request(nh_api_url(1))
        client=p.LocalBrowserClient('new_hampshire',max_requests=1);client.requests=1
        with patch.object(client,'_start') as start,self.assertRaisesRegex(SourceError,'request budget'):
            client.request(nh_api_url(1))
        start.assert_not_called()

    def test_local_parser_injection_records_transport_and_closes_client(self):
        result=Collection('new_hampshire',[Report('new_hampshire','1','Example','https://www.doj.nh.gov/')],1,complete=False)
        client=Mock(requests=1,bytes=100)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false'}),patch.object(p,'LocalBrowserClient',return_value=client),patch('ingestion.rediscovered_northeast.collect_nh_documents',return_value=result) as collect:
            actual=p.collect_local('new_hampshire',max_pages=1)
        collect.assert_called_once_with(client,max_pages=1,today=datetime.now(timezone.utc).date());client.close.assert_called_once()
        self.assertEqual(actual.evidence['transport'],p.TRANSPORT)
        self.assertIn('does not establish GitHub runner access',actual.message)

    def test_hosted_collection_identifies_actions_without_changing_transport_or_coverage(self):
        result=Collection('new_hampshire',[Report('new_hampshire','1','Example','https://www.doj.nh.gov/')],1,
                          complete=False,message='More published pages remain.')
        client=Mock(requests=1,bytes=100)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_OS':'Linux'}), \
                patch.object(p,'LocalBrowserClient',return_value=client) as factory, \
                patch('ingestion.rediscovered_northeast.collect_nh_documents',return_value=result):
            actual=p.collect_local('new_hampshire',max_pages=1)
        factory.assert_called_once_with('new_hampshire')
        client.close.assert_called_once()
        self.assertEqual(actual.evidence['transport'],'github_actions_headed_chrome_javascript_disabled')
        self.assertEqual(actual.evidence['executionEnvironment'],'github_actions')
        self.assertEqual(actual.evidence['runnerOS'],'Linux')
        self.assertIn('Collected in GitHub Actions (Linux)',actual.message)
        self.assertNotIn('Collected locally',actual.message)
        self.assertIn('More published pages remain.',actual.message)
        self.assertFalse(actual.complete)

    def test_execution_context_uses_only_fixed_labels_and_never_environment_payloads(self):
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'true','RUNNER_OS':'untrusted arbitrary text'}):
            evidence,message=p.transport_context()
        self.assertEqual(evidence['runnerOS'],'unspecified')
        self.assertNotIn('untrusted',message)
        with patch.dict(os.environ,{'GITHUB_ACTIONS':'false','RUNNER_OS':'Linux'}):
            evidence,message=p.transport_context()
        self.assertEqual(evidence['transport'],p.TRANSPORT)
        self.assertEqual(evidence['executionEnvironment'],'local')
        self.assertNotIn('runnerOS',evidence)

    def test_nj_collection_uses_utc_date_when_local_day_is_earlier(self):
        current=(Path(__file__).parent/'fixtures/rediscovered_nj_current.html').read_bytes()
        client=Mock(requests=1,bytes=len(current))
        client.request.return_value=p.Response(HOMEPAGE,current,'text/html')
        with patch.object(p,'LocalBrowserClient',return_value=client),patch.object(p,'datetime') as clock,patch.object(nj,'date') as local_day:
            clock.now.return_value=datetime(2026,8,20,0,30,tzinfo=timezone.utc)
            local_day.today.return_value=date(2026,8,19)
            result=p.collect_local('new_jersey',max_pages=1)
        clock.now.assert_called_once_with(timezone.utc)
        self.assertEqual(result.reports[0].published_date,'2026-08-20')
        client.close.assert_called_once()

    def test_sec_url_end_date_uses_utc_today(self):
        with patch.object(p,'datetime') as clock:
            clock.now.return_value=datetime(2030,1,2,0,30,tzinfo=timezone.utc)
            p.approved_url('sec',search_url(date(2030,1,1),date(2030,1,2),0))
            with self.assertRaises(SourceError):
                p.approved_url('sec',search_url(date(2030,1,1),date(2030,1,3),0))
        self.assertTrue(all(call.args == (timezone.utc,) for call in clock.now.call_args_list))

    def test_timeout_produces_only_local_failure_envelope(self):
        with tempfile.TemporaryDirectory() as directory:
            output=Path(directory)/'local.json'
            with patch.object(p,'supervise',side_effect=SourceError('hard deadline exceeded')):
                self.assertEqual(p.fetch('sec',output,timeout=1),1)
            value=json.loads(output.read_text())
            self.assertEqual(value['sourceId'],'sec');self.assertIn('hard deadline',value['error'])
            self.assertNotIn('collection',value)


@unittest.skipUnless(os.environ.get('BREACH_RUN_BROWSER_TESTS')=='1','Opt-in local Chrome network proof')
class RealChromeTests(unittest.TestCase):
    def setUp(self):
        self.hits=Counter();self.cookies=[];outer=self
        class Handler(BaseHTTPRequestHandler):
            def log_message(self,*args):pass
            def do_GET(self):
                outer.hits[self.path]+=1;outer.cookies.append(self.headers.get('Cookie'))
                if self.path in ('/redirect302','/redirect307'):
                    self.send_response(302 if self.path.endswith('302') else 307)
                    self.send_header('Location','/target');self.end_headers();return
                if self.path=='/assets':
                    content=(f'<html><body>listing<img src="/image"><script src="/script"></script>'
                             f'<iframe src="http://localhost:{self.server.server_port}/frame"></iframe></body></html>').encode()
                    kind='text/html'
                else:content=b'{"ok":true}';kind='application/json'
                self.send_response(200);self.send_header('Content-Type',kind)
                self.send_header('Content-Length',str(len(content)));self.send_header('Set-Cookie','temporary=1')
                self.end_headers();self.wfile.write(content)
        self.server=ThreadingHTTPServer(('127.0.0.1',0),Handler)
        self.thread=Thread(target=self.server.serve_forever,daemon=True);self.thread.start()
        self.base=f'http://127.0.0.1:{self.server.server_port}'
        # Test transport interception on loopback HTTP without installing a CA.
        # Production's independent HTTPS/source gate is tested above unchanged.
        self.patch=patch.object(p,'approved_url',side_effect=lambda source,url:(urlsplit(url).netloc,urlsplit(url).path,urlsplit(url).query))
        self.patch.start()

    def tearDown(self):
        self.patch.stop();self.server.shutdown();self.server.server_close();self.thread.join(2)

    def test_real_redirect_targets_receive_zero_requests(self):
        for code in (302,307):
            client=p.LocalBrowserClient('new_hampshire',deadline_seconds=20)
            try:
                with self.assertRaisesRegex(SourceError,'redirect'):
                    client.request(self.base+f'/redirect{code}')
            finally:client.close()
        self.assertEqual(self.hits['/redirect302'],1);self.assertEqual(self.hits['/redirect307'],1)
        self.assertEqual(self.hits['/target'],0)

    def test_real_subresources_frames_and_cookie_carry_are_blocked(self):
        client=p.LocalBrowserClient('new_hampshire',deadline_seconds=20)
        try:
            self.assertIn(b'listing',client.request(self.base+'/assets').content)
            self.assertEqual(client.request(self.base+'/ok').content,b'{"ok":true}')
        finally:client.close()
        self.assertEqual(self.hits['/assets'],1);self.assertEqual(self.hits['/ok'],1)
        for path in ('/image','/script','/frame'):self.assertEqual(self.hits[path],0)
        self.assertTrue(all(value is None for value in self.cookies))


if __name__=='__main__':unittest.main()
