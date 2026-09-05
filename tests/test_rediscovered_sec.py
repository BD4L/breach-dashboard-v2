from copy import deepcopy
from datetime import date
import json
from pathlib import Path
import unittest
from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.rediscovered_sec import collect_with_client, parse_search_page, search_url

FIXTURE=Path(__file__).parent/'fixtures'/'rediscovered_sec_search.json'
START=date(2026,8,6)
END=date(2026,9,5)

class Client:
    def __init__(self, pages): self.pages=iter(pages); self.requests=0; self.bytes=0; self.urls=[]
    def request(self,url):
        self.requests+=1
        self.urls.append(url)
        value=next(self.pages)
        if isinstance(value,Exception):raise value
        data=json.dumps(value).encode();self.bytes+=len(data)
        return Response(url,data,'application/json')

class SecSearchTests(unittest.TestCase):
    def setUp(self): self.data=json.loads(FIXTURE.read_text())
    def parse(self,data):return parse_search_page(json.dumps(data),start=START,end=END)
    def test_actual_item_metadata_yields_filings_and_excludes_generic_exhibit(self):
        reports,ids,total,relation=self.parse(self.data)
        self.assertEqual(len(reports),2)
        self.assertEqual(total,3)
        self.assertEqual(len(ids),3)
        self.assertEqual(reports[0].native_id,'0001104659-26-104300')
        self.assertEqual(reports[0].published_date,'2026-09-01')
        self.assertEqual(reports[0].source_url,'https://www.sec.gov/Archives/edgar/data/2069604/000110465926104300/park-20260828x8k.htm')
        self.assertIsNone(reports[0].breach_start)
        self.assertIsNone(reports[0].affected_count)
    def test_missing_items_never_turn_into_successful_empty_feed(self):
        del self.data['hits']['hits'][0]['_source']['items']
        with self.assertRaisesRegex(SourceError,'filing items'):self.parse(self.data)
    def test_unsafe_or_mismatched_accession_and_bad_dates_are_rejected(self):
        for mutate in [lambda h:h.update(_id='0001104659-26-104300:../file.htm'),
                       lambda h:h['_source'].update(adsh='0000000000-26-000000'),
                       lambda h:h['_source'].update(file_date='2026-09-06')]:
            d=deepcopy(self.data);mutate(d['hits']['hits'][0])
            with self.assertRaises(SourceError):self.parse(d)
    def test_timeout_or_failed_search_shards_never_publish_partial_search_as_valid(self):
        for mutate in [lambda d:d.update(timed_out=True),lambda d:d['_shards'].update(failed=1)]:
            d=deepcopy(self.data);mutate(d)
            with self.assertRaisesRegex(SourceError,'shards'):self.parse(d)
    def test_fully_scanned_window_retains_explicit_historical_limit(self):
        r=collect_with_client(Client([self.data]),today=END)
        self.assertEqual(len(r.reports),2)
        self.assertFalse(r.complete)
        self.assertTrue(r.evidence['windowReconciled'])
        self.assertEqual(r.parsed,2)
    def test_verified_empty_and_unverified_short_page_differ(self):
        d=deepcopy(self.data);d['hits']['hits']=[];d['hits']['total']['value']=0
        r=collect_with_client(Client([d]),today=END)
        self.assertTrue(r.empty_is_valid)
        d['hits']['total']['value']=100
        with self.assertRaisesRegex(SourceError,'declared total'):collect_with_client(Client([d]),today=END)
    def test_missing_search_schema_and_noninteger_totals_are_rejected(self):
        for d in [{}, {'hits':None}, dict(self.data,hits={'hits':[],'total':{'value':True,'relation':'eq'}})]:
            with self.assertRaises(SourceError):self.parse(d)
    def test_report_date_range_and_offset_follow_public_search_contract(self):
        u=search_url(START,END,100)
        self.assertIn('forms=8-K',u);self.assertIn('from=100',u)
        self.assertIn('startdt=2026-08-06',u)

    def pages(self):
        first=deepcopy(self.data)
        first['hits']['total']['value']=101
        first['hits']['hits']=first['hits']['hits'][:2]
        for number in range(98):
            hit=deepcopy(first['hits']['hits'][0])
            accession=f'0000000001-26-{number:06d}'
            hit['_id']=accession+':example.htm'
            hit['_source'].update(adsh=accession,items=[])
            first['hits']['hits'].append(hit)
        second=deepcopy(self.data)
        second['hits']['total']['value']=101
        second['hits']['hits']=second['hits']['hits'][2:3]
        return first,second

    def test_two_page_search_uses_offset_and_reconciles_documents_not_just_matches(self):
        client=Client(self.pages())
        result=collect_with_client(client,today=END)
        self.assertEqual(result.evidence['searchHitCount'],101)
        self.assertTrue(result.evidence['windowReconciled'])
        self.assertEqual(len(result.reports),2)
        self.assertIn('from=100',client.urls[1])

    def test_repeated_page_or_later_denial_retains_valid_first_page_as_incomplete(self):
        first,_=self.pages()
        for later in (first,SourceError('HTTP 403')):
            result=collect_with_client(Client([first,later]),today=END)
            self.assertEqual(len(result.reports),2)
            self.assertFalse(result.evidence['windowReconciled'])
            self.assertFalse(result.complete)
