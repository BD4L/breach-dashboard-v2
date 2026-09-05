"""Regression tests for rediscovered anonymous official publishing resources."""
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import Mock,patch

from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.other_portals import parse_wisconsin
from ingestion.rediscovered_midatlantic import (MD_CATALOG,NJ_RSS,collect,
    collect_maryland,collect_wisconsin,discover_wisconsin_archive,
    maryland_catalog,parse_new_jersey_rss,parse_wisconsin_archive)

F=Path(__file__).parent/'fixtures'
TODAY=date(2026,9,5)
ARCHIVE='https://datcp.wi.gov/Pages/Programs_Services/DataBreachArchive.aspx'

def fixture(name):return (F/name).read_text()
def response(data,url='https://oag.maryland.gov/resources-info/'):
    return Response(url,json.dumps(data).encode(),'application/json')

class RediscoveryTests(unittest.TestCase):
    def test_maryland_real_catalog_discovers_published_counts_without_guessing_2026(self):
        data=json.loads(fixture('rediscovered_midatlantic_catalog.json'))
        self.assertEqual(maryland_catalog(data,today=TODAY),[(2025,257),(2024,1774),(2023,1754),(2022,1476)])
        data['d']['results'].append({'Title':'Security-Breach-Notices-2026','Hidden':True,'ItemCount':99})
        self.assertNotIn(2026,dict(maryland_catalog(data,today=TODAY)))
        data['d']['results'][-1]['Hidden']=False
        self.assertEqual(maryland_catalog(data,today=TODAY)[0],(2026,99))

    def test_maryland_catalog_schema_count_and_pagination_are_validated(self):
        for data in ({}, {'d':{'results':[]}}, {'d':{'results':[{'Title':'Security-Breach-Notices-2026','Hidden':False,'ItemCount':True}]}}, {'d':{'results':[],'__next':'https://example.org'}}):
            with self.assertRaises(SourceError):maryland_catalog(data,today=TODAY)

    def test_maryland_reads_catalog_before_items_and_preserves_existing_ids(self):
        data=json.loads(fixture('state_portals_maryland.json'))
        data['d'].pop('__next',None)
        catalog={'d':{'results':[{'Title':'Security-Breach-Notices-2025','Hidden':False,'ItemCount':len(data['d']['results'])}]}}
        client=Mock(requests=2,bytes=1000)
        client.request.side_effect=[response(catalog),response(data)]
        result=collect_maryland(client,4,today=TODAY)
        self.assertEqual(client.request.call_args_list[0].args[0],MD_CATALOG)
        self.assertTrue(all(r.native_id.startswith('2025:') for r in result.reports))
        self.assertIn('Independent row counts matched for 2025',result.message)
        self.assertIn('No 2026 annual list',result.message)
        self.assertFalse(result.complete)

    def test_maryland_count_mismatch_keeps_records_and_reports_partial(self):
        data=json.loads(fixture('state_portals_maryland.json'));data['d'].pop('__next',None)
        catalog={'d':{'results':[{'Title':'Security-Breach-Notices-2025','Hidden':False,'ItemCount':500}]}}
        client=Mock(requests=2,bytes=1000);client.request.side_effect=[response(catalog),response(data)]
        result=collect_maryland(client,4,today=TODAY)
        self.assertGreater(len(result.reports),0)
        self.assertIn('disagrees',result.message)
        self.assertFalse(result.complete)

    def test_maryland_empty_published_list_fails_as_source_error(self):
        catalog={'d':{'results':[{'Title':'Security-Breach-Notices-2025','Hidden':False,'ItemCount':0}]}}
        client=Mock(requests=2,bytes=1000)
        client.request.side_effect=[response(catalog),response({'d':{'results':[]}})]
        with self.assertRaisesRegex(SourceError,'Maryland.*no valid reports'):
            collect_maryland(client,4,today=TODAY)

    def test_wisconsin_archive_discovered_only_from_official_link(self):
        self.assertEqual(discover_wisconsin_archive('<a href="/Pages/Programs_Services/DataBreachArchive.aspx">data breach archive</a>'),ARCHIVE)
        with self.assertRaises(SourceError):discover_wisconsin_archive('<a href="https://example.org/archive">data breach archive</a>')

    def test_archived_wisconsin_missing_state_count_keeps_report_without_using_national_total(self):
        result=parse_wisconsin_archive(fixture('rediscovered_midatlantic_wisconsin_archive.html'),ARCHIVE)
        self.assertEqual((len(result.reports),result.rejected),(2,0))
        report=next(r for r in result.reports if 'PAL Card' in r.organization)
        self.assertIsNone(report.affected_count)
        self.assertIsNone(report.published_date)
        self.assertIsNone(report.reported_date)
        self.assertEqual(report.source_url,ARCHIVE)
        self.assertIn('166,689',fixture('rediscovered_midatlantic_wisconsin_archive.html'))
        self.assertIn('state_count_unavailable',[f['code'] for f in report.quality_flags])

    def test_current_wisconsin_ids_are_unchanged_when_archive_collection_added(self):
        html=fixture('other_portals_wisconsin.html')+'<a href="/Pages/Programs_Services/DataBreachArchive.aspx">data breach archive</a>'
        client=Mock(requests=2,bytes=2000);client.request.side_effect=[Response('',html.encode(),'text/html'),Response(ARCHIVE,fixture('rediscovered_midatlantic_wisconsin_archive.html').encode(),'text/html')]
        current=parse_wisconsin(html)
        result=collect_wisconsin(client,2)
        for report in current.reports:
            self.assertEqual(asdict(report),asdict(next(r for r in result.reports if r.native_id==report.native_id)))
        self.assertEqual(len(result.reports),4)

    def test_wisconsin_archive_failure_retains_current_page(self):
        html=fixture('other_portals_wisconsin.html')+'<a href="/Pages/Programs_Services/DataBreachArchive.aspx">data breach archive</a>'
        client=Mock(requests=2,bytes=1000);client.request.side_effect=[Response('',html.encode(),'text/html'),SourceError('HTTP403')]
        result=collect_wisconsin(client,2)
        self.assertEqual(len(result.reports),2)
        self.assertIn('archive unavailable',result.message)
        self.assertFalse(result.complete)

    def test_nj_feed_contract_filters_non_breaches_and_uses_explicit_publication_date(self):
        result=parse_new_jersey_rss(fixture('rediscovered_midatlantic_rss_synthetic.xml').encode(),today=TODAY)
        self.assertEqual(len(result.reports),1)
        self.assertEqual(result.reports[0].published_date,'2026-09-04')
        self.assertFalse(result.complete)
        self.assertIsNone(result.reports[0].reported_date)

    def test_nj_ordinary_feed_access_error_has_no_proxy_or_guessed_record_fallback(self):
        client=Mock();client.request.side_effect=SourceError('HTTP403')
        with patch('ingestion.rediscovered_midatlantic.PublicClient',return_value=client):
            with self.assertRaisesRegex(SourceError,'403'):collect('new_jersey')
        self.assertEqual(client.request.call_args.args[0],NJ_RSS)
        self.assertEqual(client.request.call_count,1)
        client.close.assert_called_once()

    def test_nj_challenge_empty_and_entity_documents_are_failures(self):
        for content in (b'<html>Access denied</html>',b'<rss><channel></channel></rss>',b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>'):
            with self.assertRaises(SourceError):parse_new_jersey_rss(content,today=TODAY)

    def test_limits_are_validated_before_network(self):
        with patch('ingestion.rediscovered_midatlantic.PublicClient') as client:
            for value in (True,0,-1,201,1.5):
                with self.assertRaises(SourceError):collect('maryland',max_pages=value)
            client.assert_not_called()

if __name__=='__main__':unittest.main()
