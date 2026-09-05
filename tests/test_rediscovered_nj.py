from copy import deepcopy
from dataclasses import asdict
from datetime import date
from pathlib import Path
import unittest
from unittest.mock import patch

from bs4 import BeautifulSoup
from ingestion import rediscovered_nj as p
from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.runner import decode_collection

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)
CURRENT_TWO = p.HOMEPAGE + '/-npage-2'
ARCHIVE = p.HOMEPAGE + '/-arch-1'
ARCHIVE_TWO = ARCHIVE + '/-npage-2'


def fixture(name): return (FIXTURES / ('rediscovered_nj_' + name + '.html')).read_text()


class Client:
    def __init__(self,routes):self.routes,self.calls,self.closed=routes,[],False
    def request(self,url,**kwargs):
        self.calls.append(url); value=self.routes[url]
        if isinstance(value,Exception):raise value
        return Response(url,value.encode(),'text/html')
    def close(self):self.closed=True


class NewJerseyTests(unittest.TestCase):
    def test_real_current_listing_identity_date_and_pagination(self):
        page=p.parse_page(fixture('current'),today=TODAY)
        self.assertEqual((page.parsed,page.rejected,page.start,page.end,page.total),(20,0,1,20,21))
        self.assertEqual(page.next_url,CURRENT_TWO);self.assertEqual(page.archive_url,ARCHIVE)
        first=page.reports[0]
        self.assertEqual((first.native_id,first.organization,first.published_date),('news-2120','Paylogix','2026-08-20'))
        self.assertIsNone(first.reported_date);self.assertIsNone(first.breach_start);self.assertIsNone(first.affected_count)

    def test_real_current_terminal_page_query_is_not_identity(self):
        page=p.parse_page(fixture('page2'),CURRENT_TWO,today=TODAY)
        self.assertEqual((page.parsed,page.start,page.end,page.total),(1,21,21,21))
        self.assertIsNone(page.next_url)
        self.assertEqual(page.reports[0].native_id,'news-1802')
        self.assertNotIn('?',page.reports[0].source_url)
        self.assertEqual(page.reports[0].published_date,'2025-09-18')

    def test_real_archive_has_its_own_total_and_scope(self):
        page=p.parse_page(fixture('archive'),ARCHIVE,today=TODAY)
        self.assertTrue(page.archived);self.assertEqual(page.total,35)
        self.assertEqual(page.next_url,ARCHIVE_TWO)
        self.assertEqual(page.reports[0].native_id,'news-1787')
        self.assertNotIn('?',page.reports[0].source_url)

    def test_real_archive_publication_timestamp_preserves_calendar_date(self):
        page=p.parse_page(fixture('archive'),ARCHIVE,today=TODAY)
        self.assertEqual((len(page.reports),page.parsed,page.rejected),(20,20,0))
        timed=next(r for r in page.reports if r.organization=='Mint Mobile')
        self.assertEqual(timed.published_date,'2023-12-28')

    def test_missing_widget_is_unavailable_not_empty(self):
        for html in ('<h1>Access Denied</h1>','<h1>Public Data Breaches</h1><p>Loading</p>'):
            with self.assertRaises(SourceError):p.parse_page(html)

    def test_page_count_and_terminal_control_must_agree(self):
        with self.assertRaises(SourceError):p.parse_page(fixture('current').replace('1 - 20 of 21 items','1 - 19 of 21 items'))
        with self.assertRaises(SourceError):p.parse_page(fixture('current').replace('1 - 20 of 21 items','1 - 20 of 20 items'))
        with self.assertRaises(SourceError):p.parse_page(fixture('page2'),p.HOMEPAGE)

    def test_pagination_cannot_skip_change_scope_or_leave_host(self):
        for url in (p.HOMEPAGE+'/-npage-3',ARCHIVE_TWO,'https://example.com/-npage-2'):
            with self.assertRaises(SourceError):p.parse_page(fixture('current').replace('/threat-landscape/public-data-breaches/-npage-2',url))
        with self.assertRaises(SourceError):p.listing_identity(p.HOMEPAGE+'/-npage-201')
        with self.assertRaises(SourceError):p.listing_identity(p.HOMEPAGE+'/-arch-1/-arch-1')

    def test_notice_host_component_and_return_query_are_validated(self):
        for replacement in ('https://example.com/News/2120/216','/Home/Components/News/News/2120/999','/Home/Components/News/News/2120/216?token=example'):
            with self.assertRaises(SourceError):p.parse_page(fixture('current').replace('/Home/Components/News/News/2120/216',replacement))
        with self.assertRaises(SourceError):p.parse_page(fixture('page2').replace('?npage=2','?npage=3'),CURRENT_TWO)

    def test_conflicting_visible_and_accessible_dates_withhold_only_row(self):
        page=p.parse_page(fixture('current').replace('published on 08/20/2026','published on 08/21/2026'))
        self.assertEqual((len(page.reports),page.parsed,page.rejected),(19,20,1))

    def test_unknown_or_future_date_not_replaced_with_retrieval_date(self):
        page=p.parse_page(fixture('current').replace('08/20/2026','08/20/2027'),today=TODAY)
        self.assertIsNone(page.reports[0].published_date)
        self.assertIn('unparsed_date',{flag['code'] for flag in page.reports[0].quality_flags})

    def test_source_failure_stops_without_retry_and_closes(self):
        client=Client({p.HOMEPAGE:SourceError('HTTP 403')})
        with patch.object(p,'PublicClient',return_value=client),self.assertRaisesRegex(SourceError,'403'):p.collect()
        self.assertEqual(client.calls,[p.HOMEPAGE]);self.assertTrue(client.closed)

    def test_two_page_budget_covers_current_but_not_archive(self):
        client=Client({p.HOMEPAGE:fixture('current'),CURRENT_TWO:fixture('page2')})
        with patch.object(p,'PublicClient',return_value=client):c=p.collect(max_pages=2)
        self.assertEqual((len(c.reports),c.parsed,c.rejected),(21,21,0));self.assertFalse(c.complete)
        self.assertEqual(c.evidence['finished_scopes'],['current'])
        self.assertIn('More published pages remain',c.message)
        decode_collection(asdict(c),'new_jersey')

    def test_all_four_actual_pages_reconcile_current_and_archive_totals(self):
        client=Client({p.HOMEPAGE:fixture('current'),CURRENT_TWO:fixture('page2'),
                       ARCHIVE:fixture('archive'),ARCHIVE_TWO:fixture('archive-page2')})
        with patch.object(p,'PublicClient',return_value=client):c=p.collect()
        self.assertEqual(client.calls,[p.HOMEPAGE,CURRENT_TWO,ARCHIVE,ARCHIVE_TWO])
        self.assertEqual((len(c.reports),c.parsed,c.rejected),(56,56,0))
        self.assertTrue(c.complete)
        self.assertEqual(c.evidence['scope_totals'],{'current':21,'archive':35})
        self.assertEqual(c.evidence['finished_scopes'],['archive','current'])
        self.assertEqual(len({r.native_id for r in c.reports}),56)
        self.assertTrue(client.closed);decode_collection(asdict(c),'new_jersey')

    def test_archive_failure_retains_current_with_explicit_partial(self):
        client=Client({p.HOMEPAGE:fixture('current'),CURRENT_TWO:fixture('page2'),ARCHIVE:SourceError('HTTP 403')})
        with patch.object(p,'PublicClient',return_value=client):c=p.collect()
        self.assertEqual(len(c.reports),21);self.assertFalse(c.complete);self.assertIn('403',c.message)
        self.assertTrue(client.closed)

    def test_range_overlap_and_changing_total_stop_at_valid_page(self):
        for second in (fixture('page2').replace('21 - 21 of 21 items','20 - 20 of 21 items'),fixture('page2').replace('21 - 21 of 21 items','22 - 22 of 22 items')):
            client=Client({p.HOMEPAGE:fixture('current'),CURRENT_TWO:second})
            with patch.object(p,'PublicClient',return_value=client):c=p.collect()
            self.assertEqual(len(c.reports),20);self.assertFalse(c.complete)

    def test_duplicate_conflicts_reconcile_and_do_not_choose_title(self):
        reports=p.parse_page(fixture('current')).reports[:2]
        conflicting=deepcopy(reports[0]);conflicting.organization='Conflicting synthetic title'
        c=p.finalize([reports[0],conflicting,reports[1]],3,0,complete=True,message='fixture',evidence={})
        self.assertEqual((len(c.reports),c.parsed,c.rejected),(1,3,2));self.assertFalse(c.complete)
        decode_collection(asdict(c),'new_jersey')

    def test_invalid_budget_does_not_start_client(self):
        for limit in (True,0,-1,201,'2'):
            with self.assertRaises(SourceError):p.collect(max_pages=limit)


if __name__=='__main__':unittest.main()
