from copy import deepcopy
from dataclasses import asdict
from datetime import date
import json
from pathlib import Path
import unittest
from unittest.mock import patch

from ingestion import rediscovered_delaware as p
from ingestion.models import SourceError
from ingestion.network import Response
from ingestion.runner import decode_collection

F = Path(__file__).parent / 'fixtures'
TODAY = date(2026, 9, 5)


class Client:
    def __init__(self, values): self.values=iter(values); self.requests=self.bytes=0; self.closed=False
    def request(self, url, **kwargs):
        value=next(self.values); self.requests+=1
        if isinstance(value, Exception): raise value
        content=json.dumps(value).encode(); self.bytes+=len(content)
        return Response(url,content,'application/json')
    def close(self): self.closed=True


class DelawareTests(unittest.TestCase):
    def setUp(self):
        self.metadata=json.loads((F/'rediscovered_delaware_metadata.json').read_text())
        self.rows=json.loads((F/'rediscovered_delaware_rows.json').read_text())
        self.aliases=json.loads(Path(p.__file__).with_name('delaware_legacy_ids.json').read_text())

    def test_current_public_schema_and_notice_date_semantics(self):
        p.validate_metadata(self.metadata)
        reports,ids,bad=p.parse_rows(self.rows,today=TODAY)
        self.assertEqual((len(reports),len(ids),bad),(3,3,0))
        latest=reports[1]
        self.assertIn('2026-08-12',latest.summary)
        self.assertIsNone(latest.reported_date)
        self.assertIsNone(latest.published_date)
        self.assertEqual(latest.affected_scope,'state')
        self.assertEqual(latest.affected_jurisdiction,'DE')

    def test_legacy_id_and_verified_reported_date_survive_migration(self):
        reports,_,_=p.parse_rows(self.rows,aliases=self.aliases,today=TODAY)
        alias=self.aliases[self.rows[0][':id']]
        self.assertEqual(reports[0].native_id,alias['native_id'])
        self.assertEqual(reports[0].reported_date,alias['reported_date'])
        changed=deepcopy(self.rows); changed[0]['de_residents_affected']='999'
        again=p.parse_rows(changed,aliases=self.aliases,today=TODAY)[0][0]
        self.assertEqual(again.native_id,reports[0].native_id)
        self.assertEqual(again.affected_count,999)

    def test_supplement_count_is_not_added_or_substituted(self):
        reports,_,_=p.parse_rows(self.rows,today=TODAY)
        self.assertEqual(reports[2].affected_count,int(self.rows[2]['de_residents_affected']))
        self.assertIn('supplemental_count_not_combined',{f['code'] for f in reports[2].quality_flags})

    def test_verified_legacy_end_and_absent_count_are_preserved_with_provenance(self):
        row=deepcopy(self.rows[0]);aliases=deepcopy(self.aliases);alias=aliases[row[':id']]
        row['date_of_breach']='2023-01-01T00:00:00.000';row.pop('de_residents_affected',None)
        alias.update(breach_start='2023-01-01',breach_end='2023-01-10',affected_count=124,affected_qualifier='exact')
        report=p.parse_rows([row],aliases=aliases,today=TODAY)[0][0]
        self.assertEqual((report.breach_start,report.breach_end,report.affected_count),('2023-01-01','2023-01-10',124))
        codes={f['code'] for f in report.quality_flags}
        self.assertTrue({'legacy_breach_end_preserved','legacy_affected_count_preserved'} <= codes)
        row['de_residents_affected']='unparseable'
        self.assertIsNone(p.parse_rows([row],aliases=aliases,today=TODAY)[0][0].affected_count)
        row['de_residents_affected']='5'
        self.assertEqual(p.parse_rows([row],aliases=aliases,today=TODAY)[0][0].affected_count,5)

    def test_changed_start_keeps_old_range_as_context_without_hybrid_end(self):
        row=deepcopy(self.rows[0]);aliases=deepcopy(self.aliases);alias=aliases[row[':id']]
        row['date_of_breach']='2023-01-05T00:00:00.000'
        alias.update(breach_start='2023-01-01',breach_end='2023-01-10')
        report=p.parse_rows([row],aliases=aliases,today=TODAY)[0][0]
        self.assertEqual(report.breach_start,'2023-01-05');self.assertIsNone(report.breach_end)
        context=next(f['message'] for f in report.quality_flags if f['code']=='legacy_breach_range_context')
        self.assertIn('2023-01-01',context);self.assertIn('2023-01-10',context)

    def test_reused_published_id_cannot_inherit_another_entitys_legacy_fields(self):
        row=deepcopy(self.rows[0]);row['company_name']='Unrelated Example Corporation'
        reports,ids,bad=p.parse_rows([row],aliases=self.aliases,today=TODAY)
        self.assertEqual((len(reports),len(ids),bad),(0,1,1))

    def test_count_and_revision_reconcile_before_claiming_complete(self):
        count=[{'count':'3'}]
        client=Client([self.metadata,count,self.rows,count,self.metadata])
        with patch.object(p,'PublicClient',return_value=client): result=p.collect()
        self.assertEqual((len(result.reports),result.parsed,result.rejected),(3,3,0))
        self.assertTrue(result.complete); self.assertTrue(client.closed)
        decode_collection(asdict(result),'delaware')
        changed=deepcopy(self.metadata);changed['rowsUpdatedAt']+=1
        with patch.object(p,'PublicClient',return_value=Client([self.metadata,count,self.rows,count,changed])):
            self.assertFalse(p.collect().complete)

    def test_failed_final_check_preserves_valid_records_as_partial(self):
        client=Client([self.metadata,[{'count':'3'}],self.rows,SourceError('HTTP 503')])
        with patch.object(p,'PublicClient',return_value=client): result=p.collect()
        self.assertEqual(len(result.reports),3); self.assertFalse(result.complete)
        self.assertIn('consistency check failed',result.message)

    def test_pagination_budget_and_overlapping_pages_are_partial(self):
        count=[{'count':'3'}]
        with patch.object(p,'PAGE_SIZE',1):
            client=Client([self.metadata,count,[self.rows[0]],count,self.metadata])
            with patch.object(p,'PublicClient',return_value=client):result=p.collect(max_pages=1)
            self.assertEqual((len(result.reports),result.parsed),(1,1))
            self.assertFalse(result.complete)
            client=Client([self.metadata,count,*[[row] for row in self.rows],count,self.metadata])
            with patch.object(p,'PublicClient',return_value=client):result=p.collect(max_pages=3)
            self.assertTrue(result.complete);self.assertEqual(len(result.reports),3)
        with patch.object(p,'PAGE_SIZE',2):
            client=Client([self.metadata,count,self.rows[:2],[self.rows[0]],count,self.metadata])
            with patch.object(p,'PublicClient',return_value=client):result=p.collect()
            self.assertEqual((len(result.reports),result.parsed),(2,2))
            self.assertFalse(result.complete)
            self.assertIn('overlaps',result.message)

    def test_duplicate_id_missing_schema_and_bad_independent_count_fail(self):
        with self.assertRaises(SourceError):p.parse_rows([self.rows[0],self.rows[0]])
        row=deepcopy(self.rows[0]);del row[':id']
        with self.assertRaises(SourceError):p.parse_rows([row])
        metadata=deepcopy(self.metadata);metadata['columns'][0]['dataTypeName']='number'
        with self.assertRaises(SourceError):p.validate_metadata(metadata)
        for count in ([],[{'count':True}],[{'count':'3.5'}]):
            with self.assertRaises(SourceError):p.count_rows(count)

    def test_bad_dates_and_non_https_notice_never_become_valid_fields(self):
        row=deepcopy(self.rows[0]);row['date_of_notice']='yesterday'
        with self.assertRaises(SourceError):p.parse_rows([row])
        row=deepcopy(self.rows[0]);row['sample_of_notice']={'url':'http://example.invalid/notice.pdf'}
        report=p.parse_rows([row],today=TODAY)[0][0]
        self.assertIsNone(report.notice_url)

    def test_limits_precede_network_and_alias_map_is_one_to_one(self):
        self.assertEqual(len({a['native_id'] for a in self.aliases.values()}),len(self.aliases))
        with patch.object(p,'PublicClient') as client:
            for limit in (True,0,101,'2'):
                with self.assertRaises(SourceError):p.collect(max_pages=limit)
            client.assert_not_called()


if __name__=='__main__':unittest.main()
