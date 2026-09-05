from copy import deepcopy
from dataclasses import asdict
from datetime import date
from io import BytesIO
import json
from pathlib import Path
import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET
from zipfile import ZipFile, ZIP_DEFLATED

from ingestion import rediscovered_states as p
from ingestion.models import SourceError
from ingestion.runner import decode_collection
from ingestion.network import Response

FIXTURES = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


def fixture(name):
    return (FIXTURES / ('rediscovered_states_' + name)).read_text()


def workbook(rows, *, formula=False, date1904=False):
    namespace = 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'
    sheet = ET.Element('worksheet', xmlns=namespace)
    ET.SubElement(sheet, 'dimension', ref='A1:XFD1048576')
    data = ET.SubElement(sheet, 'sheetData')
    strings = []
    for i, row in enumerate(rows, 1):
        entry = ET.SubElement(data, 'row', r=str(i))
        for column, (value, numeric) in row.items():
            cell = ET.SubElement(entry, 'c', r=f'{column}{i}', **({} if numeric else {'t': 's'}))
            if formula:
                ET.SubElement(cell, 'f').text = '1+1'
            if not numeric:
                strings.append(value); value = str(len(strings) - 1)
            ET.SubElement(cell, 'v').text = value
    shared = ET.Element('sst', xmlns=namespace)
    for value in strings:
        ET.SubElement(ET.SubElement(shared, 'si'), 't').text = value
    book = ET.Element('workbook', xmlns=namespace)
    ET.SubElement(book, 'workbookPr', date1904='1' if date1904 else '0')
    output = BytesIO()
    with ZipFile(output, 'w', ZIP_DEFLATED) as z:
        z.writestr('xl/workbook.xml', ET.tostring(book))
        z.writestr('xl/sharedStrings.xml', ET.tostring(shared))
        z.writestr('xl/worksheets/sheet1.xml', ET.tostring(sheet))
    return output.getvalue()


class Client:
    def __init__(self, routes): self.routes, self.calls, self.closed = routes, [], False
    def request(self, url, **kwargs):
        self.calls.append(url)
        value = self.routes[url]
        if isinstance(value, Exception): raise value
        return Response(url, value if isinstance(value, bytes) else value.encode(), 'text/html')
    def close(self): self.closed = True


class RediscoveredStateTests(unittest.TestCase):
    def test_iowa_published_javascript_years_and_rollover(self):
        links = p.iowa_year_links(fixture('iowa_navigation.html'), p.SOURCES['iowa']['homepage'], today=TODAY)
        self.assertEqual((links[0][0], links[-1][0], len(links)), (2026, 2011, 16))
        self.assertNotIn(2026, [year for year, _ in p.iowa_year_links(fixture('iowa_navigation.html'), p.SOURCES['iowa']['homepage'], today=date(2025, 12, 31))])
        with self.assertRaises(SourceError): p.iowa_year_links('<script>var breachYears=[{url:"https://example.com/security-breach-notifications/2026-security-breach-notification"}];</script>', p.SOURCES['iowa']['homepage'])

    def test_iowa_sitemap_recovers_plural_and_bare_year_urls(self):
        years = dict(p.iowa_year_links(fixture('iowa_sitemap.html'), p.SOURCES['iowa']['homepage']))
        self.assertEqual(len(years), 16)
        self.assertTrue(years[2022].endswith('/2022-security-breach-notifications'))
        self.assertTrue(years[2019].endswith('/2019'))
        self.assertTrue(years[2017].endswith('/2017'))

    def test_iowa_linked_sitemap_overrides_stale_script_url(self):
        home = p.SOURCES['iowa']['homepage'] + '/'
        old = home + '2022-security-breach-notification'
        actual = old + 's'
        home_html = '<script>var breachYears=[{url:"' + old + '"}];</script><a href="/sitemap">Sitemap</a>'
        sitemap = 'https://www.iowaattorneygeneral.gov/sitemap'
        client = Client({home:home_html, sitemap:f'<a href="{actual}">2022</a>', actual:fixture('iowa2026.html').replace('2026','2022')})
        with patch.object(p,'PublicClient',return_value=client): result = p.collect('iowa')
        self.assertEqual(client.calls, [home, sitemap, actual])
        self.assertEqual(result.evidence['years'], [2022])

    def test_iowa_broken_initial_link_rejects_one_row_external_info_not_fetched(self):
        records, parsed, bad = p.parse_iowa_cards(fixture('iowa2024_links.html'), p.SOURCES['iowa']['homepage'], 2024)
        self.assertEqual((len(records), parsed, bad), (1, 2, 1))
        self.assertEqual(records[0].organization, 'National Public Data')
        self.assertIn('informational_link_not_collected', {f['code'] for f in records[0].quality_flags})

    def test_iowa_nested_unclosed_cards_have_one_report_each(self):
        records, parsed, bad = p.parse_iowa_cards(fixture('iowa2026.html'), p.SOURCES['iowa']['homepage'], 2026, today=TODAY)
        self.assertEqual((len(records), parsed, bad), (4, 4, 0))
        self.assertEqual(len({r.native_id for r in records}), 4)
        self.assertEqual(records[0].reported_date, '2026-01-06')
        self.assertIsNone(records[0].published_date)
        self.assertTrue(records[0].notice_url.endswith('.pdf'))
        self.assertIsNone(records[0].affected_count)

    def test_iowa_real_related_entity_and_supplement_only_not_template(self):
        records, parsed, bad = p.parse_iowa_cards(fixture('iowa2025.html'), p.SOURCES['iowa']['homepage'], 2025, today=TODAY)
        self.assertEqual((len(records), parsed, bad), (6, 6, 0))
        self.assertTrue(any(r.organization == 'Lewis Central Community School District' for r in records))
        self.assertFalse(any('Related Entity Name Here' in r.organization for r in records))
        supplemental = next(r for r in records if 'supplemental letter only' in r.organization)
        self.assertIn('supplemental_notice_only', {f['code'] for f in supplemental.quality_flags})

    def test_iowa_schema_offsite_and_empty_counter_guard(self):
        html = fixture('iowa2026.html')
        with self.assertRaises(SourceError): p.parse_iowa_cards(html.replace('sby-date-value','changed-field'), p.SOURCES['iowa']['homepage'], 2026)
        with self.assertRaises(SourceError): p.parse_iowa_cards(html.replace('/media/cms/','https://example.com/'), p.SOURCES['iowa']['homepage'], 2026)
        with self.assertRaises(SourceError): p.parse_iowa_cards('<h1>2026 Security Breach Notifications</h1>0 notices listed', p.SOURCES['iowa']['homepage'], 2026)

    def test_iowa_document_identity_survives_count_and_card_order(self):
        first = p.parse_iowa_cards(fixture('iowa2026.html'), p.SOURCES['iowa']['homepage'], 2026)[0][0]
        second = p.parse_iowa_cards(fixture('iowa2026.html').replace('Professional Services','Another industry'), p.SOURCES['iowa']['homepage'], 2026)[0][0]
        self.assertEqual(first.native_id, second.native_id)
        self.assertNotEqual(first.summary, second.summary)

    def test_iowa_budget_is_partial_and_later_archive_failure_retains(self):
        home = p.SOURCES['iowa']['homepage'] + '/'
        links = p.iowa_year_links(fixture('iowa_navigation.html'), home)
        client = Client({home:fixture('iowa_navigation.html'), links[0][1]:fixture('iowa2026.html'), links[1][1]:SourceError('HTTP 403')})
        with patch.object(p,'PublicClient',return_value=client): result=p.collect('iowa',max_pages=2)
        self.assertEqual(len(result.reports),4); self.assertFalse(result.complete)
        self.assertIn('403',result.message); self.assertTrue(client.closed)
        decode_collection(asdict(result),'iowa')

    def test_maine_links_are_published_and_same_host(self):
        links=p.maine_archive_links(fixture('maine_archives.html'))
        self.assertEqual(len(links),2)
        self.assertTrue(all(url.startswith('https://www.maine.gov/') for _,url in links))
        with self.assertRaises(SourceError):p.maine_archive_links(fixture('maine_archives.html').replace('/ag/sites/','https://example.com/'))

    def test_maine_xlsx_named_values_without_formatted_rectangle(self):
        rows=json.loads(fixture('maine_submission_cells.json'))
        content=workbook(rows)
        extracted=p.xlsx_rows(content)
        self.assertEqual(len(extracted[0]),3)
        reports,parsed,bad=p.parse_maine_archive(content,'https://www.maine.gov/archive.xlsx','2018–2020',today=TODAY)
        self.assertEqual((len(reports),parsed,bad),(2,2,0))
        first=reports[0]
        self.assertEqual(first.reported_date,'2020-09-11')
        self.assertEqual(first.breach_start,'2020-03-16')
        self.assertEqual((first.affected_count,first.affected_scope,first.affected_jurisdiction),(1,'state','ME'))
        self.assertEqual(first.data_types,['Social Security number'])
        self.assertIsNone(first.published_date)
        serialized=json.dumps(asdict(first))
        self.assertNotIn('908 W.',serialized); self.assertNotIn('Bozeman',serialized)

    def test_maine_legacy_date_semantics_and_address_withholding(self):
        rows=json.loads(fixture('maine_legacy_cells.json'))
        reports,parsed,bad=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/older.xlsx','2010–2018',today=TODAY)
        self.assertEqual((len(reports),parsed,bad),(2,2,0))
        self.assertEqual(reports[0].organization,'Example Corporation')
        self.assertIsNone(reports[0].reported_date)
        self.assertIsNone(reports[0].published_date)
        self.assertNotIn('Example Road',json.dumps(asdict(reports[0])))
        rows[2]['A']=['An ambiguous company 123 address Maine 00000',False]
        reports,parsed,bad=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/older.xlsx','2010–2018',today=TODAY)
        self.assertEqual((len(reports),parsed,bad),(1,2,1))

    def test_maine_identity_excludes_affected_count(self):
        rows=json.loads(fixture('maine_submission_cells.json'))
        one=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/archive.xlsx','fixture')[0][0]
        rows[1]['P']=['5',False]
        two=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/renamed.xlsx','fixture')[0][0]
        self.assertEqual(one.native_id,two.native_id)
        self.assertNotEqual(one.affected_count,two.affected_count)

    def test_maine_both_schemas_withhold_contact_contaminated_entity_fields(self):
        examples = (
            'Example Corporation, (202) 555-0100',
            'Example Corporation, privacy@example.invalid',
            'Example Corporation, Jordan Example, Chief Privacy Officer',
            'Example Corporation P.O. Box 123',
            'Example Corporation 123 Example Road',
        )
        for schema, index, column in [('submission', 1, 'B'), ('legacy', 2, 'A')]:
            for text in examples:
                with self.subTest(schema=schema, text=text):
                    rows=json.loads(fixture(f'maine_{schema}_cells.json'))
                    rows[index][column]=[text,False]
                    reports,parsed,bad=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/archive.xlsx','fixture',today=TODAY)
                    self.assertEqual((len(reports),parsed,bad),(1,2,1))
                    self.assertNotIn(text,json.dumps([asdict(r) for r in reports]))

    def test_maine_information_contact_block_is_not_a_data_category(self):
        rows=json.loads(fixture('maine_legacy_cells.json'))
        rows[2]['D']=['Additional retailer - Example Shop, 123 Example Road, Jordan Example, (202) 555-0100; privacy@example.invalid',False]
        reports,parsed,bad=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/archive.xlsx','fixture',today=TODAY)
        self.assertEqual((len(reports),parsed,bad),(2,2,0))
        self.assertEqual(reports[0].data_types,[])
        self.assertIn('contact_text_withheld',{f['code'] for f in reports[0].quality_flags})
        serialized=json.dumps(asdict(reports[0]))
        for value in ('Example Shop','Jordan Example','555-0100','example.invalid'):
            self.assertNotIn(value,serialized)

    def test_maine_information_uses_fixed_categories_without_copying_prose(self):
        flags=[]
        text='Names and Social Security numbers, with additional source commentary not suitable for an information-type field.'
        self.assertEqual(p.maine_legacy_data_types(text,flags),['Social Security number','Names'])
        self.assertEqual(flags,[])
        flags=[]
        self.assertEqual(p.maine_legacy_data_types('Additional retailer Example Shop',flags),[])
        self.assertEqual(flags[0]['code'],'unclassified_data_types')

    def test_conflicting_identity_withheld_reconciles_all_rows(self):
        rows=json.loads(fixture('maine_submission_cells.json'))
        reports=p.parse_maine_archive(workbook(rows),'https://www.maine.gov/archive.xlsx','fixture')[0]
        conflict=deepcopy(reports[0]);conflict.affected_count=100
        result=p.finish('maine',[reports[0],conflict,reports[1]],3,0,message='fixture',complete=True)
        self.assertEqual((len(result.reports),result.parsed,result.rejected),(1,3,2))
        self.assertFalse(result.complete);decode_collection(asdict(result),'maine')

    def test_spreadsheet_dtd_formula_and_date_system_fail(self):
        rows=json.loads(fixture('maine_submission_cells.json'))
        with self.assertRaises(SourceError):p.xlsx_rows(workbook(rows,formula=True))
        with self.assertRaises(SourceError):p.xlsx_rows(workbook(rows,date1904=True))
        with self.assertRaises(SourceError):p.xlsx_rows(b'<html>access denied</html>')
        with self.assertRaises(SourceError):p._xml(b'<!DOCTYPE x [<!ENTITY y "z">]><x/>')
        with self.assertRaises(SourceError):p._xml('<!DOCTYPE x [<!ENTITY y "z">]><x/>'.encode('utf-16'))
        rows[0]['B']=['Changed organization column',False]
        with self.assertRaises(SourceError):p.parse_maine_archive(workbook(rows),'https://www.maine.gov/archive.xlsx','fixture')

    def test_spreadsheet_limits_cover_raw_expanded_empty_rows_and_cells(self):
        content = workbook(json.loads(fixture('maine_submission_cells.json')))
        for limit in ('MAX_XLSX_BYTES', 'MAX_XLSX_EXPANDED_BYTES', 'MAX_XLSX_ROWS', 'MAX_XLSX_CELLS'):
            with self.subTest(limit=limit), patch.object(p,limit,1), self.assertRaises(SourceError):
                p.xlsx_rows(content)
        with patch.object(p, 'MAX_XLSX_ROWS', 2), self.assertRaises(SourceError):
            p.xlsx_rows(workbook([{}, {}, {}]))

    def test_native_excel_booleans_are_not_dates_or_affected_counts(self):
        content = workbook(json.loads(fixture('maine_submission_cells.json')))
        with ZipFile(BytesIO(content)) as source:
            files = {name:source.read(name) for name in source.namelist()}
        sheet = ET.fromstring(files['xl/worksheets/sheet1.xml'])
        for ref in ('A2', 'P2', 'T2'):
            cell = next(c for c in sheet.findall('.//{*}c') if c.get('r') == ref)
            cell.set('t', 'b'); cell.find('{*}v').text = '1'
        files['xl/worksheets/sheet1.xml'] = ET.tostring(sheet)
        output = BytesIO()
        with ZipFile(output, 'w', ZIP_DEFLATED) as destination:
            for name, value in files.items(): destination.writestr(name,value)
        report = p.parse_maine_archive(output.getvalue(),'https://www.maine.gov/archive.xlsx','fixture')[0][0]
        self.assertIsNone(report.reported_date)
        self.assertIsNone(report.affected_count)
        self.assertEqual(report.data_types, ['Social Security number'])

    def test_maine_live_restoration_does_not_claim_archives_are_current(self):
        home=p.SOURCES['maine']['homepage'];client=Client({home:'<h1>Current database restored</h1>'})
        with patch.object(p,'PublicClient',return_value=client),self.assertRaisesRegex(SourceError,'status changed'):p.collect('maine')
        self.assertTrue(client.closed)

    def test_bounds_precede_network(self):
        for value in (0,41,-1,True,'2'):
            with self.assertRaises(SourceError):p.collect('iowa',max_pages=value)


if __name__=='__main__':unittest.main()
