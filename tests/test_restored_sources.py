from dataclasses import asdict
from datetime import datetime, timezone
from pathlib import Path
import tempfile
import unittest
from unittest.mock import Mock, patch

from ingestion.additional_sources import COMPANY_PAGES, FEEDS
from ingestion.models import ACTIVE_SOURCE_IDS, Collection, Report, SOURCES, SourceError
from ingestion.restored_sources import parse_breachsense, parse_hibp, parse_state
from ingestion import restored_sources, syndicated_sources
from ingestion.runner import decode_collection
from ingestion.scheduling import plan_sources, RECENT_CRON
from ingestion.store import Store
from ingestion.syndicated_sources import article_date, parse_cybernews, parse_feed
from ingestion.validation import InvalidReport, normalize_report

NOW = datetime(2026, 9, 12, 16, tzinfo=timezone.utc)
VT_HEADER = '<thead><tr><th>Date Reported to AGO</th><th>Reporting Organization Name</th><th>Reporting Organization Type</th><th>Number of VT Residents Affected</th><th>Categories of Data Breached</th></tr></thead>'
HI_HEADER = '<thead><tr><th>Date Notified</th><th>Case Number</th><th>Breached Entity Name</th><th>Breach type</th><th>Hawaii Residents Impacted</th><th>Link to Letter</th></tr></thead>'


def table(header, rows):
    return '<table>' + header + '<tbody>' + ''.join('<tr>' + ''.join(f'<td>{cell}</td>' for cell in row) + '</tr>' for row in rows) + '</tbody></table>'


def rss(items):
    return ('<rss><channel><title>News</title><pubDate>Sat, 12 Sep 2026 15:00:00 GMT</pubDate>' + ''.join(items) + '</channel></rss>').encode()


def item(title='Example Company data breach', date='Fri, 11 Sep 2026 15:00:00 GMT', link='https://www.bleepingcomputer.com/news/example', guid='example'):
    return f'<item><title>{title}</title><link>{link}</link><guid>{guid}</guid>' + (f'<pubDate>{date}</pubDate>' if date else '') + '</item>'


class RestoredSourceTests(unittest.TestCase):
    def test_cybernews_uses_publisher_card_dates_and_excludes_unrelated_navigation(self):
        html = '<title>Cybernews</title><a href="/leak-check/">Data leak checker</a><article data-block-item="featured"><a href="https://cybernews.com/news/example/"><h3>Example data breach</h3><span class="category-block__meta-item">September 11, 2026</span></a></article>'
        result = parse_cybernews(html, now=NOW)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(result.reports[0].published_date, '2026-09-11')
        self.assertEqual(result.reports[0].signal_type, 'secondary_report')
        self.assertIsNone(result.reports[0].source_observed_at)
        self.assertFalse(result.complete)
        alternate = html.replace('data-block-item="featured"', 'class="separated-list__item"').replace('category-block__meta-item', 'meta-item').replace('Example data breach', 'Example breach')
        self.assertEqual(len(parse_cybernews(alternate, now=NOW).reports), 1)
        with self.assertRaises(SourceError): parse_cybernews('<title>Cybernews</title>No cards', now=NOW)

    def test_article_byline_date_does_not_invent_a_timestamp_or_use_navigation_dates(self):
        html = '<div class="bis-cpanel-item-date">September 12, 2026</div><article id="generic-article"><h1>Example data breach</h1><span class="article-byline"><span class="text-nowrap">September 11, 2026</span></span></article>'
        dated = article_date(html)
        result = parse_feed('news_bleepingcomputer', rss([item(date=None)]), now=NOW, date_lookup=lambda _: dated)
        self.assertEqual(result.reports[0].published_date, '2026-09-11')
        self.assertIsNone(result.reports[0].source_observed_at)
        self.assertTrue(result.complete)
        self.assertIsNone(article_date('<div class="bis-cpanel-item-date">September 12, 2026</div>'))

    def test_breachsense_retains_current_month_when_previous_month_is_unavailable(self):
        page = '<article class="blog-card"><h3><a href="/breaches/example/">Example</a></h3><p>Threat Actor Example Group Date Discovered Sep 11, 2026</p></article>'
        client = Mock(requests=2, bytes=100)
        client.request.side_effect = [Mock(text=page), SourceError('HTTP 403; access denied')]
        with patch.object(restored_sources, 'PublicClient', return_value=client):
            result = restored_sources.collect('breachsense', now=NOW)
        self.assertEqual(len(result.reports), 1)
        self.assertFalse(result.complete)
        self.assertEqual(result.evidence['unavailablePages'], 1)
        decode_collection(asdict(result), 'breachsense')
        client.close.assert_called_once()

    def test_article_lookup_stops_after_access_failure_and_retains_undated_headlines(self):
        client = Mock(requests=2, bytes=100)
        feed = rss([item(date=None, guid=str(i)) for i in range(3)])
        client.request.side_effect = [Mock(content=feed), SourceError('HTTP 429; rate limited')]
        with patch.object(syndicated_sources, 'PublicClient', return_value=client):
            result = syndicated_sources.collect('news_bleepingcomputer', now=NOW)
        self.assertEqual(len(result.reports), 3)
        self.assertTrue(all(report.source_observed_at is None for report in result.reports))
        self.assertFalse(result.complete)
        self.assertEqual(client.request.call_count, 2)

    def test_every_original_state_feed_and_company_has_a_distinct_catalog_identity(self):
        states = {'california', 'delaware', 'hawaii', 'indiana', 'iowa', 'maine', 'maryland', 'massachusetts', 'montana', 'new_hampshire', 'new_jersey', 'north_dakota', 'oklahoma', 'south_carolina', 'texas', 'vermont', 'washington', 'wisconsin'}
        self.assertTrue(states <= SOURCES.keys())
        self.assertEqual(len(FEEDS), 20)
        self.assertEqual(len(COMPANY_PAGES), 5)
        self.assertTrue({'hibp', 'hibp_feed', 'breachsense', 'ransomlook', 'privacy_rights', 'nvd', 'cisa_kev'} <= SOURCES.keys())
        self.assertNotEqual(SOURCES['news_threatpost']['id'], SOURCES['news_darkreading']['id'])
        self.assertEqual(set(plan_sources('all')), set(ACTIVE_SOURCE_IDS))
        self.assertFalse({'privacy_rights', 'nvd', 'cisa_kev'} & set(ACTIVE_SOURCE_IDS))

    def test_recent_schedule_and_external_input_cannot_launch_unknown_or_reference_sources(self):
        recent = plan_sources('all', event='schedule', schedule=RECENT_CRON)
        self.assertEqual(recent, plan_sources('recent'))
        self.assertIn('vermont', recent)
        self.assertNotIn('maine', recent)
        self.assertEqual(plan_sources('hawaii'), ['hawaii'])
        for source in ['privacy_rights', '; echo unsafe', '', '../sec']:
            with self.assertRaises(ValueError): plan_sources(source)

    def test_vermont_current_table_retains_dates_counts_and_normalizes_only_duplicate_separators(self):
        html = table(VT_HEADER, [['9-11-2026', 'Example Firm', 'Other Commercial', '1,234', 'Social Security Numbers'],
                                  ['8-13--2026', 'Second Firm', 'Health Care', '2', 'Health Records']])
        result = parse_state('vermont', html)
        self.assertTrue(result.complete)
        self.assertEqual(result.reports[0].reported_date, '2026-09-11')
        self.assertEqual(result.reports[0].affected_count, 1234)
        self.assertEqual(result.reports[0].affected_jurisdiction, 'VT')
        self.assertEqual(result.reports[1].reported_date, '2026-08-13')
        self.assertEqual(result.reports[1].quality_flags[0]['code'], 'source_date_typo')
        self.assertIsNone(result.reports[0].notice_url)
        self.assertEqual(decode_collection(asdict(result), 'vermont'), result)

    def test_hawaii_case_can_cover_multiple_entities_but_conflicting_counts_are_withheld(self):
        rows = [['2024/03.18', '2024-0001', 'One Entity', 'Hacking', '1000', ''],
                ['2024/03.18', '2024-0001', 'Second Entity', 'Hacking', '2000', ''],
                ['2024/03.18', '2024-0002', 'Conflicting Entity', 'Hacking', '3000', ''],
                ['2024/03.18', '2024-0002', 'Conflicting Entity', 'Hacking', '4000', '']]
        result = parse_state('hawaii', table(HI_HEADER, rows))
        self.assertEqual((result.parsed, len(result.reports), result.rejected), (4, 2, 2))
        self.assertEqual({r.organization for r in result.reports}, {'One Entity', 'Second Entity'})
        self.assertIn('2024-03-18', result.message)
        self.assertFalse(result.complete)

    def test_state_pages_without_expected_table_fail_instead_of_becoming_empty_success(self):
        for html in ['<h1>Access denied</h1>', table(VT_HEADER, [])]:
            with self.assertRaises(SourceError): parse_state('vermont', html)

    def test_hibp_uses_catalog_publication_time_and_does_not_call_account_counts_people(self):
        entry = {'Name': 'Example', 'Title': 'Example Firm', 'AddedDate': '2026-09-11T14:00:00Z',
                 'BreachDate': '2018-01-01', 'DataClasses': ['Email addresses'], 'PwnCount': 1234, 'IsVerified': True}
        result = parse_hibp([entry], now=NOW)
        report = result.reports[0]
        self.assertEqual(report.signal_type, 'secondary_report')
        self.assertEqual(report.published_date, '2026-09-11')
        self.assertEqual(report.breach_start, '2018-01-01')
        self.assertIsNone(report.affected_count)
        self.assertIn('1,234 compromised accounts', report.summary)
        normalized = normalize_report(report, source_id='hibp', now=NOW)
        self.assertEqual(normalized['sourceObservedAt'], '2026-09-11T14:00:00Z')
        for bad in [dict(entry, AddedDate='2027-01-01T00:00:00Z'), dict(entry, AddedDate='invalid')]:
            result = parse_hibp([bad], now=NOW)
            self.assertEqual(result.rejected, 1)
            self.assertFalse(result.empty_is_valid)

    def test_breachsense_preserves_allegation_and_never_downloads_leaked_data(self):
        html = '<article class="blog-card"><h3><a href="/breaches/example-data-breach/">Example</a></h3><p>Victim example.com Threat Actor ExampleGroup Date Discovered Sep 11, 2026 Description Sample</p></article>'
        result = parse_breachsense(html, 'https://www.breachsense.com/breaches/2026/september/', now=NOW)
        self.assertEqual(result.reports[0].signal_type, 'ransomware_claim')
        self.assertIsNone(result.reports[0].affected_count)
        self.assertIsNone(result.reports[0].breach_start)
        self.assertTrue(result.evidence['metadataOnly'])
        normalize_report(result.reports[0], source_id='breachsense', now=NOW)

    def test_feed_ignores_unrelated_articles_and_preserves_exact_publication_time(self):
        result = parse_feed('news_bleepingcomputer', rss([item(), item('New software update', guid='other')]), now=NOW)
        self.assertEqual(len(result.reports), 1)
        self.assertEqual(result.reports[0].source_observed_at, '2026-09-11T15:00:00Z')
        self.assertEqual(result.evidence['unmatched'], 1)
        self.assertEqual(result.reports[0].signal_type, 'secondary_report')
        self.assertNotIn('<', result.reports[0].summary)

    def test_feed_build_date_never_makes_undated_or_old_articles_recent(self):
        result = parse_feed('news_bleepingcomputer', rss([item(date=''), item(date='Tue, 01 Jan 2019 15:00:00 GMT', guid='old')]), now=NOW)
        self.assertEqual(len(result.reports), 1)
        self.assertIsNone(result.reports[0].published_date)
        self.assertIsNone(result.reports[0].source_observed_at)
        self.assertFalse(result.complete)
        self.assertEqual(result.evidence['outsideWindow'], 1)

    def test_atom_metadata_is_supported_without_using_feed_updated_time(self):
        atom = b'<feed xmlns="http://www.w3.org/2005/Atom"><entry><title>Example data breach</title><id>one</id><link href="https://www.reddit.com/r/databreaches/comments/one"/><published>2026-09-11T12:00:00Z</published></entry></feed>'
        result = parse_feed('reddit_databreaches', atom, now=NOW)
        self.assertEqual(len(result.reports), 1)
        self.assertIn('reddit.com', result.reports[0].source_url)

    def test_feed_rejects_unsafe_urls_future_dates_html_and_xml_entities(self):
        for bad in [b'<html>challenge</html>', b'<!DOCTYPE rss [<!ENTITY x SYSTEM "file:///etc/passwd">]><rss/>']:
            with self.assertRaises(SourceError): parse_feed('news_krebs', bad, now=NOW)
        result = parse_feed('news_krebs', rss([item(link='javascript:alert(1)'), item(date='Fri, 11 Sep 2027 15:00:00 GMT', guid='future')]), now=NOW)
        self.assertEqual((result.parsed, result.rejected), (2, 2))
        self.assertFalse(result.empty_is_valid)

    def test_article_enrichment_uses_publication_metadata_and_not_generic_updated_time(self):
        self.assertEqual(article_date('<meta property="article:published_time" content="2026-09-11T12:00:00Z">').day, 11)
        self.assertIsNone(article_date('<time datetime="2026-09-12T12:00:00Z">Updated</time>'))
        self.assertIsNone(article_date('<script type="application/ld+json">{"datePublished": {"bad":"value"}}</script>'))

    def test_secondary_and_reference_records_cannot_pass_as_official(self):
        report = Report('hibp', 'one', 'Example', 'https://haveibeenpwned.com/PwnedWebsites')
        with self.assertRaises(InvalidReport): normalize_report(report, source_id='hibp', now=NOW)
        report = Report('nvd', 'one', 'Example CVE', 'https://nvd.nist.gov/')
        with self.assertRaises(InvalidReport): normalize_report(report, source_id='nvd', now=NOW)

    def test_partial_collection_has_usable_timestamp_without_claiming_complete_coverage(self):
        with tempfile.TemporaryDirectory() as directory, Store(Path(directory) / 'state.sqlite', 'live') as store:
            report = Report('vermont', 'one', 'Example', SOURCES['vermont']['homepage'], reported_date='2026-09-11')
            store.apply_collection(Collection('vermont', [report], 1, complete=False), NOW)
            data = store.dashboard(NOW)
            source = next(s for s in data['sources'] if s['id'] == 'vermont')
            self.assertIsNone(source['lastSuccess'])
            self.assertEqual(source['lastCollected'], '2026-09-12T16:00:00Z')
            self.assertEqual(source['latestReportDate'], '2026-09-11')
            reference = next(s for s in data['sources'] if s['id'] == 'privacy_rights')
            self.assertEqual(reference['status'], 'disabled')
            self.assertIn('purchased', reference['message'])


if __name__ == '__main__':
    unittest.main()
