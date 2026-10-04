import copy
import csv
import json
import os
from pathlib import Path
import shutil
import subprocess
import sys
import tempfile
import unittest

from synthetic_fixtures import PACKAGE, fixture, finalize_copy
from common import VERSION, digest, envelope, period_dir, read_json, ref, sha, write_json
from preprocess import intake
from history_metrics import committed_cashflow, compare_history
from validate_report import audit_facts, load_report_inputs, validate, validate_inputs, validate_state
from render_workbook import deliver, render_workbook, verify_workbook
from update_state import update


class Acceptance(unittest.TestCase):
    def setUp(self):
        self.temp=tempfile.TemporaryDirectory(prefix='billing-synthetic-')
        self.root=Path(self.temp.name)
        self.period='2031.4'
        self.raw,self.events,self.links,self.ctx=fixture(self.root)
        self.base=period_dir(self.root,self.period)
    def tearDown(self):
        self.temp.cleanup()
    def save(self,name,value):
        write_json(self.base/name,value)
    def facts(self):
        self.save('处理结果/经济事件.json',envelope(self.period,economic_events=self.events))
        self.save('处理结果/关联记录.json',envelope(self.period,match_links=self.links))
        self.save('处理结果/analysis_context.json',self.ctx)
    def assertBlocked(self,call):
        with self.assertRaises((ValueError,KeyError,TypeError,OSError)):
            call()
    def final(self):
        return finalize_copy(self.root,self.period)

    def test_new_workspace_empty_rules_no_history_end_to_end(self):
        write_json(self.root/'merchant_rules.json',read_json(PACKAGE/'assets/templates/merchant_rules.json'))
        data,_=self.final()
        self.assertEqual(data['metrics']['net_expense']['value'],136.5)
        self.assertEqual(data['metrics']['real_income']['value'],2600)
        self.assertEqual(data['metrics']['net_surplus']['value'],2463.5)
        self.assertEqual(data['metrics']['cash_outflow']['value'],768.25)
        self.assertEqual(data['metrics']['cash_inflow']['value'],3031.75)
        self.assertEqual(data['comparison']['status'],'insufficient_history')
        self.assertFalse(validate(self.root,self.period))
        path=deliver(self.root,self.period);self.assertTrue(path.exists())
        update(self.root,self.period);self.assertFalse(validate_state(self.root))

    def test_repeat_and_overlapping_exports(self):
        mapping=read_json(PACKAGE/'examples/source_mapping.json')
        first=self.root/'input.csv';overlap=self.root/'overlap.csv'
        lines=first.read_text(encoding='utf-8').splitlines()
        overlap.write_text('\n'.join(lines[:5])+'\n',encoding='utf-8')
        raw,pre=intake(self.root,self.period,[first,overlap],mapping=mapping)
        self.assertEqual(len(raw['normalized_records']),9)
        self.assertEqual(len(raw['raw_records']),13)
        self.assertEqual(sorted(len(n['source_locations']) for n in raw['normalized_records'])[-1],2)
        again,_=intake(self.root,self.period,[first,overlap],mapping=mapping)
        self.assertEqual(again,raw)

    def test_export_sequence_and_missing_account_preserve_ambiguity(self):
        mapping=read_json(PACKAGE/'examples/source_mapping.json')
        first=self.root/'input.csv';other=self.root/'other.csv';shutil.copyfile(first,other)
        for stable,account in [(False,'account'),(True,None)]:
            mapping.update(transaction_id_is_stable=stable,account_key=account)
            raw,pre=intake(self.root,self.period,[first,other],mapping=mapping)
            self.assertEqual(len(raw['normalized_records']),18)
            self.assertTrue(pre['candidates'])

    def test_same_amount_multiple_candidates(self):
        mapping=read_json(PACKAGE/'examples/source_mapping.json')
        source=self.root/'ambiguous.csv'
        source.write_text('日期,金额,方向,交易号,对方,摘要\n2031-04-01T12:00:00,44,OUT,X1,虚构A,候选\n2031-04-01T12:01:00,44,OUT,X2,虚构B,候选\n2031-04-01T12:02:00,44,OUT,X3,虚构C,候选\n',encoding='utf-8')
        raw,pre=intake(self.root,self.period,[source],mapping=mapping)
        self.assertEqual(len(raw['normalized_records']),3)
        self.assertTrue(all(c['ambiguous'] and c['status']=='candidate' for c in pre['candidates']))

    def test_arbitrary_sources_columns_multiaccount_json_xlsx(self):
        m=dict(format='standardized_json',original_source='ArbitraryProvider42',fields=dict(trade_time='when',raw_amount='value',flow_direction='side',account_key='acct',original_trade_no='id'),transaction_id_is_stable=True,direction_values={'-':'支出'},date_formats=['%d/%m/%Y'])
        source=self.root/'adapted.json'
        write_json(source,dict(records=[dict(when='01/04/2031',value=25,side='-',acct=a,id='ORDER-SHARED') for a in ('A','B')]))
        raw,_=intake(self.root,self.period,[source],mapping=m)
        self.assertEqual(len(raw['normalized_records']),2)
        from openpyxl import Workbook
        w=Workbook();w.active.append(['when','value','side','acct','id']);w.active.append(['01/04/2031',25,'-','C','OTHER'])
        xlsx=self.root/'adapter.xlsx';w.save(xlsx);w.close()
        m['format']='xlsx'
        raw,_=intake(self.root,self.period,[xlsx],mapping=m)
        self.assertEqual(raw['normalized_records'][0]['original_source'],'ArbitraryProvider42')

    def test_name_conflict_evidence_registration(self):
        m=read_json(PACKAGE/'examples/source_mapping.json')
        directory=self.root/'external';directory.mkdir();source=directory/'input.csv'
        source.write_text((self.root/'input.csv').read_text(encoding='utf-8').replace('37.25','38.25'),encoding='utf-8')
        raw,_=intake(self.root,self.period,[source],mapping=m)
        self.assertIn('-',Path(raw['source_manifest'][0]['file']).stem)
        self.assertEqual(sha(self.base/'原始数据/input.csv'),sha(self.root/'input.csv'))
        self.assertFalse(Path(raw['source_manifest'][0]['file']).is_absolute())

    def test_currency_precision_and_no_silent_rounding(self):
        m=read_json(PACKAGE/'examples/source_mapping.json');m['currency']='JPY'
        source=self.root/'yen.csv'
        source.write_text('日期,金额,方向,交易号,对方,摘要\n2031-04-01,109,OUT,J1,虚构,整额\n2031-04-02,1.5,OUT,J2,虚构,精度拒绝\n',encoding='utf-8')
        self.assertBlocked(lambda:intake(self.root,self.period,[source],mapping=m,currency='JPY'))
        raw,_=intake(self.root,self.period,[source],mapping=m,currency='JPY',amount_precision=0)
        self.assertEqual(raw['normalized_records'][0]['raw_amount'],109)
        self.assertEqual(len(raw['rejected_rows']),1)
        m['currency']='USD'
        raw,_=intake(self.root,self.period,[source],mapping=m,currency='CNY')
        self.assertEqual(len(raw['rejected_rows']),2)

    def test_unknown_partial_zero_income_null_display(self):
        self.events[5].update(economic_type='内部转账',income_amount=0)
        self.facts();data,cp=self.final()
        self.assertEqual(data['metrics']['real_income']['value'],0)
        self.assertIsNone(data['metrics']['retention_ratio']['value'])
        self.assertEqual(data['metrics']['retention_ratio']['status'],'not_applicable')
        self.ctx['completeness']['income']='partial';self.ctx['completeness']['obligations']='unknown'
        self.facts();data,cp=self.final()
        self.assertEqual(data['metrics']['real_income']['status'],'partial')
        self.assertIsNone(data['metrics']['committed_cashflow_1_month']['value'])
        self.events[5]['data_status']='unknown';self.facts();data,cp=self.final()
        self.assertIsNone(data['metrics']['net_expense']['value'])
        w=render_workbook(data,cp)
        self.assertIsNone(w.worksheets[0]['B5'].value)
        self.assertEqual(w.worksheets[0]['C5'].value,'未知')
        w.close()

    def test_unreadable_files_preserved_and_completeness_blocked(self):
        source=self.root/'unreadable.pdf';source.write_bytes(b'SYNTHETIC UNREADABLE EVIDENCE')
        m=read_json(PACKAGE/'examples/source_mapping.json')
        raw,pre=intake(self.root,self.period,[self.root/'input.csv',source],mapping=dict(files={'input.csv':m}))
        self.assertEqual(len(pre['needs_reading']),1)
        self.assertBlocked(lambda:audit_facts(self.root,self.period))
        self.ctx['completeness'].update(expense='partial',income='partial');self.facts()
        rawref=ref(self.root,self.base/'处理结果/原始标准化.json')
        for e in self.events:
            e['evidence_refs']=[dict(rawref,record_ids=[a['record_id'] for a in e['record_allocations']])]
        for l in self.links:l['evidence_refs']=[rawref]
        confirmations=read_json(self.base/'执行记录/确认记录.json')
        confirmations['confirmations'][0]['evidence_refs']=[rawref]
        self.save('执行记录/确认记录.json',confirmations)
        self.ctx['confirmation_refs']=[ref(self.root,self.base/'执行记录/确认记录.json',confirmation_ids=['CONF-SYNTHETIC-SCOPE'])]
        self.facts()
        audit_facts(self.root,self.period)

    def test_net_amount_and_allocation_defects_blocked(self):
        for mutate in [lambda:self.events[0].update(net_expense=19),
                       lambda:self.events[6]['record_allocations'][0].update(amount=201),
                       lambda:self.events[5].update(income_amount=2500),
                       lambda:self.events[3].update(income_amount=18.75)]:
            saved=copy.deepcopy(self.events);mutate();self.facts()
            self.assertBlocked(lambda:audit_facts(self.root,self.period));self.events=saved
        self.facts()

    def test_refund_shared_return_overallocation_duplicate_links_blocked(self):
        self.links.append(copy.deepcopy(self.links[0]));self.links[-1]['match_link_id']='FAKE-DUPLICATE';self.facts()
        self.assertBlocked(lambda:audit_facts(self.root,self.period))
        self.links.pop();self.links[1]['applied_amount']=40;self.events[1]['reimbursement_amount']=40;self.events[1]['net_expense']=85;self.facts()
        self.assertBlocked(lambda:audit_facts(self.root,self.period))

    def test_missing_evidence_changed_hash_absolute_unresolved_ids_blocked(self):
        original=copy.deepcopy(self.events[0]['evidence_refs'][0])
        cases=[dict(original,file='missing.json'),dict(original,sha256='0'*64),dict(original,file=str(self.root/'input.csv')),dict(original,record_ids=['NO-SUCH-ID'])]
        for value in cases:
            self.events[0]['evidence_refs']=[value];self.facts()
            self.assertBlocked(lambda:audit_facts(self.root,self.period))
        self.events[0]['evidence_refs']=[original];self.facts()
        (self.base/'原始数据/input.csv').write_text('CHANGED',encoding='utf-8')
        self.assertBlocked(lambda:audit_facts(self.root,self.period))

    def test_raw_amount_and_projection_tampering_blocked(self):
        self.raw['raw_records'][0]['raw_amount']=123
        self.save('处理结果/原始标准化.json',self.raw)
        self.assertBlocked(lambda:audit_facts(self.root,self.period))

    def test_internal_notes_bindings_and_stale_render_blocked(self):
        data,cp=self.final()
        bad=copy.deepcopy(data);t=bad['audit_tables']['economic_event'];t['columns'].append('audit_notes')
        for row in t['rows']:row['audit_notes']='INTERNAL'
        badcp=copy.deepcopy(cp);badcp['data_sha256']=digest(bad)
        self.assertTrue(validate_inputs(bad,badcp))
        for mutate in [lambda c:c['sections'][0].update(data_refs=['metrics.nonexistent.value']),
                       lambda c:c['sections'][0].update(text='金额 {metrics.real_income.value:.2f}'),
                       lambda c:c['sections'][0].update(visible_when={'data_ref':'metrics.net_expense.value','status_in':['confirmed']}),
                       lambda c:c['sections'][0].update(text='无绑定自由文本')]:
            badcp=copy.deepcopy(cp);mutate(badcp);self.assertTrue(validate_inputs(data,badcp))
        self.ctx['completeness']['income']='partial';self.facts()
        self.assertBlocked(lambda:load_report_inputs(self.root,self.period))

    def test_forged_metrics_even_with_updated_copy_digest_blocked(self):
        data,cp=self.final();data['metrics']['real_income']['value']=9999;cp['data_sha256']=digest(data)
        self.save('处理结果/report_data.json',data);self.save('处理结果/report_copy.json',cp)
        self.assertBlocked(lambda:load_report_inputs(self.root,self.period))

    def test_workbook_readback_formula_text_and_delivery_gate(self):
        self.assertBlocked(lambda:update(self.root,self.period))
        data,cp=self.final();cp['strings']['title']='=FORMULA MUST STAY TEXT'
        self.save('处理结果/report_copy.json',cp)
        path=deliver(self.root,self.period);verify_workbook(path,data,cp)
        from openpyxl import load_workbook
        w=load_workbook(path);self.assertEqual(w.worksheets[0]['A1'].data_type,'s');w.worksheets[0]['B5']=1;w.save(path);w.close()
        self.assertBlocked(lambda:update(self.root,self.period))

    def test_state_idempotency_summary_revisions_and_no_overwrite(self):
        self.final();deliver(self.root,self.period);update(self.root,self.period)
        before={p.name:p.read_bytes() for p in (self.root/'state').glob('*.json')}
        update(self.root,self.period)
        self.assertEqual(before,{p.name:p.read_bytes() for p in (self.root/'state').glob('*.json')})
        self.ctx['completeness']['income']='partial';self.facts();self.final();deliver(self.root,self.period);update(self.root,self.period)
        state=read_json(self.root/'state/period_summary.json')
        self.assertEqual(len(state['periods'][self.period]['revisions']),1)
        self.assertEqual(state['periods'][self.period]['revisions'][0]['before']['completeness']['income'],'complete')
        self.assertFalse(validate_state(self.root))

    def test_goal_acceptance_feedback_and_idempotency(self):
        evidence=self.ctx['confirmation_refs']
        goal=dict(goal_id='GOAL-SYNTHETIC',origin_period=self.period,target_period=self.period,currency='CNY',definition_version='economic-v2',metric_key='net_expense',operator='<=',target_value=150,actual_value=None,goal_status='accepted',evidence_refs=evidence,acceptance_evidence_refs=[],revisions=[])
        self.ctx['goal_changes']=[goal];self.facts();self.assertBlocked(lambda:audit_facts(self.root,self.period))
        goal['acceptance_evidence_refs']=evidence;self.facts();data,_=self.final()
        self.assertEqual(data['goals'][0]['goal_status'],'achieved')
        deliver(self.root,self.period);update(self.root,self.period);update(self.root,self.period)
        saved=read_json(self.root/'state/goals.json')['goals'][0]
        self.assertEqual(len(saved['revisions']),1)

    def test_usd_full_chain_without_cny_units(self):
        fixture(self.root,self.period,currency='USD',precision=2)
        data,_=self.final();deliver(self.root,self.period);update(self.root,self.period)
        self.assertEqual(data['currency'],'USD')
        self.assertTrue(all(m['currency'] in ('USD',None) for m in data['metrics'].values()))
        self.assertFalse(validate_state(self.root))

    def test_obligation_lifecycle_revisions_and_unknown_plan(self):
        ev=self.ctx['confirmation_refs']
        schedule=[dict(payment_id='SYNTHETIC-PAY-1',due_date='2031-05-20',currency='CNY',amount=97,principal=90,interest_and_fees=7,status='confirmed',payment_status='scheduled',evidence_refs=ev)]
        obligation=dict(obligation_id='SYNTHETIC-OBLIGATION',currency='CNY',obligation_type='贷款',obligation_status='active',service_start=None,service_end=None,remaining_principal=90,payment_schedule=schedule,data_status='confirmed',evidence_refs=ev,revisions=[])
        self.ctx['obligation_changes']=[obligation];self.facts();data,_=self.final()
        self.assertEqual(data['metrics']['committed_cashflow_1_month']['value'],97)
        deliver(self.root,self.period);update(self.root,self.period)
        before={k:copy.deepcopy(v) for k,v in obligation.items() if k!='revisions'}
        obligation.update(obligation_status='settled',remaining_principal=0)
        obligation['payment_schedule'][0]['payment_status']='paid'
        after={k:copy.deepcopy(v) for k,v in obligation.items() if k!='revisions'}
        obligation['revisions']=[dict(changed_at='2031-04-30T20:00:00',reason='合成提前结清',before=before,after=after,evidence_refs=ev)]
        self.facts();data,_=self.final();deliver(self.root,self.period);update(self.root,self.period);update(self.root,self.period)
        state=read_json(self.root/'state/obligations.json')
        self.assertEqual(len(state['obligations']),1)
        self.assertEqual(state['obligations'][0]['obligation_status'],'settled')
        self.assertEqual(len(state['obligations'][0]['revisions']),1)
        self.assertTrue(all(m['value']==0 for k,m in data['metrics'].items() if k.startswith('committed_cashflow')))

    def test_cross_period_refund_cashflow_and_original_net_revision(self):
        self.final();deliver(self.root,self.period);update(self.root,self.period)
        prior=copy.deepcopy(self.events[1])
        other='2031.5';raw,events,links,ctx=fixture(self.root,other)
        base=period_dir(self.root,other)
        received=next(e for e in events if e['economic_type']=='退款')
        links=[l for l in links if l['source_event_id']!=received['event_id']]
        meal=events[0];meal.update(refund_amount=0,net_expense=37.25)
        # Bring the original evidence through the uniform JSON adapter with its own mapping.
        # Its existing record ID is reused by registering the earlier standardized source file.
        oldraw=read_json(self.base/'处理结果/原始标准化.json')
        raw['raw_records'].extend(copy.deepcopy(oldraw['raw_records']))
        raw['normalized_records'].extend(copy.deepcopy(oldraw['normalized_records']))
        raw['source_manifest'].extend(copy.deepcopy(oldraw['source_manifest']))
        write_json(base/'处理结果/原始标准化.json',raw)
        rawref=ref(self.root,base/'处理结果/原始标准化.json')
        for e in events:e['evidence_refs']=[dict(rawref,record_ids=[a['record_id'] for a in e['record_allocations']])]
        confirmations=read_json(base/'执行记录/确认记录.json');confirmations['confirmations'][0]['evidence_refs']=[rawref]
        write_json(base/'执行记录/确认记录.json',confirmations)
        ctx['confirmation_refs']=[ref(self.root,base/'执行记录/确认记录.json',confirmation_ids=['CONF-SYNTHETIC-SCOPE'])]
        for link in links:link['evidence_refs']=[rawref]
        prior['refund_amount']=18.75;prior['net_expense']-=18.75
        prior['evidence_refs']=[dict(rawref,record_ids=[a['record_id'] for a in prior['record_allocations']])]
        events.append(prior)
        links.append(dict(match_link_id='CROSS-PERIOD-REFUND',match_type='退款匹配',source_event_id=received['event_id'],target_event_id=prior['event_id'],record_ids=[],currency='CNY',applied_amount=18.75,data_status='confirmed',evidence_refs=[rawref],audit_notes='合成跨期追溯'))
        # The earlier AA adjustment is carried with the earlier source event and relation.
        aa=copy.deepcopy(self.events[4]);events.append(aa)
        aa['evidence_refs']=[dict(rawref,record_ids=[a['record_id'] for a in aa['record_allocations']])]
        carried=copy.deepcopy(self.links[1]);carried['evidence_refs']=[rawref];links.append(carried)
        write_json(base/'处理结果/经济事件.json',envelope(other,economic_events=events))
        write_json(base/'处理结果/关联记录.json',envelope(other,match_links=links))
        write_json(base/'处理结果/analysis_context.json',ctx)
        data,_=finalize_copy(self.root,other)
        self.assertEqual(data['metrics']['net_expense']['value'],155.25)
        self.assertEqual(data['metrics']['real_income']['value'],2600)
        self.assertEqual(data['metrics']['cash_inflow']['value'],3031.75)
        deliver(self.root,other);update(self.root,other);update(self.root,other)
        old=read_json(self.root/'state/period_summary.json')['periods'][self.period]
        self.assertEqual(old['metrics']['net_expense']['value'],117.75)
        self.assertEqual(len(old['revisions']),1)

    def test_state_source_hash_and_metrics_tampering_blocked(self):
        self.final();deliver(self.root,self.period);update(self.root,self.period)
        state=read_json(self.root/'state/period_summary.json')
        state['periods'][self.period]['metrics']['net_expense']['value']=1
        write_json(self.root/'state/period_summary.json',state)
        self.assertTrue(validate_state(self.root))
        state['periods'][self.period]['metrics']['net_expense']['value']=136.5
        state['periods'][self.period]['link_snapshots'][0]['applied_amount']=1
        write_json(self.root/'state/period_summary.json',state)
        self.assertTrue(validate_state(self.root))

    def test_reanalysis_fact_change_preserves_immutable_evidence_and_revision(self):
        self.final();deliver(self.root,self.period);update(self.root,self.period)
        previous=read_json(self.root/'state/period_summary.json')['periods'][self.period]
        oldref=previous['evidence_refs'][0]
        self.events[1]['category_l1']='合成修订类别';self.facts()
        self.assertEqual(sha(self.root/oldref['file']),oldref['sha256'])
        self.final();deliver(self.root,self.period);update(self.root,self.period);update(self.root,self.period)
        new=read_json(self.root/'state/period_summary.json')['periods'][self.period]
        self.assertEqual(len(new['revisions']),1)
        self.assertNotEqual(new['categories'],previous['categories'])
        self.assertFalse(validate_state(self.root))

    def test_valid_source_rows_cannot_be_silently_omitted(self):
        removed=self.raw['normalized_records'].pop()
        self.raw['raw_records']=[r for r in self.raw['raw_records'] if r['record_id'] not in removed['raw_record_ids']]
        self.raw['source_manifest'][0]['record_count']-=1
        self.save('处理结果/原始标准化.json',self.raw)
        self.assertBlocked(lambda:audit_facts(self.root,self.period))

    def test_durable_fact_evidence_and_source_coordinates(self):
        from validate_report import evidence
        source=ref(self.root,self.base/'原始数据/input.csv',row=2,sheet=None)
        evidence(self.root,[source])
        self.assertBlocked(lambda:evidence(self.root,[dict(source,row=999)]))
        self.events[0]['evidence_refs']=[ref(self.root,self.base/'处理结果/原始标准化.json',freeze=False)]
        self.facts();self.assertBlocked(lambda:audit_facts(self.root,self.period))

    def test_opaque_raw_fields_cannot_supply_evidence_ids(self):
        from validate_report import evidence
        opaque=self.root/'opaque.json'
        write_json(opaque,dict(raw_fields=dict(record_id='OPAQUE-SMUGGLED-ID')))
        self.assertBlocked(lambda:evidence(self.root,[ref(self.root,opaque,record_ids=['OPAQUE-SMUGGLED-ID'])]))

    def test_package_relocation_clean_cli_and_reference_granularity(self):
        relocated=self.root/'portable-package';shutil.copytree(PACKAGE,relocated,ignore=shutil.ignore_patterns('__pycache__','*.pyc'))
        clean=dict(os.environ)
        for key in ('PYTHONPATH','NODE_PATH'):clean.pop(key,None)
        completed=subprocess.run([sys.executable,'-E','-s','-B',str(relocated/'scripts/validate_report.py'),'--root',str(self.root),'--period',self.period,'--facts'],cwd=self.root,env=clean,capture_output=True)
        self.assertEqual(completed.returncode,0,completed.stderr.decode(errors='replace'))
        self.assertEqual({p.name for p in (relocated/'references').iterdir()},{'financial-rules.md','workflow.md','extensions.md','billing_schema.json'})

    def test_undeclared_context_override_and_old_contract_blocked(self):
        for key,value in [('merchant_rules',{}),('metric_overrides',{'net_expense':0}),('matching_threshold',50)]:
            self.ctx[key]=value;self.facts();self.assertBlocked(lambda:audit_facts(self.root,self.period));del self.ctx[key]
        self.ctx['schema_version']='1.3';self.facts();self.assertBlocked(lambda:audit_facts(self.root,self.period))


class PureCalculations(unittest.TestCase):
    def summary(self,month,value=11,currency='CNY'):
        return dict(period_id=f'2031.{month}',currency=currency,amount_precision=2,period=dict(context_group='synthetic',definition_version='v2',observed_days=28,is_full_period=False),data_status='confirmed',completeness=dict(expense='complete'),metrics=dict(daily=dict(value=value,status='confirmed' if value is not None else 'unknown',unit='currency_per_day',currency=currency,definition='synthetic daily')))
    def test_history_two_six_thresholds_exclusions(self):
        current=self.summary(10,55)
        history={p['period_id']:p for p in [self.summary(m,m*11) for m in range(1,10)]}
        history[current['period_id']]=current;history['2031.11']=self.summary(11,9999)
        for month,key,value in [(1,'currency','USD'),(2,'data_status','partial')]:history[f'2031.{month}'][key]=value
        result=compare_history(current,history,'daily')
        self.assertEqual(result['reference_period_ids'],[f'2031.{m}' for m in range(4,10)])
        self.assertEqual(result['reference_value'],71.5)
        self.assertEqual(result['normal_range'],dict(low=57.75,high=85.25,method='linear_P25_P75'))
        history={'2031.8':self.summary(8,22),'2031.9':self.summary(9,44)}
        result=compare_history(current,history,'daily');self.assertEqual(result['reference_value'],33)
        self.assertIsNone(result['normal_range'])
        self.assertEqual(compare_history(current,{'2031.9':history['2031.9']},'daily')['status'],'insufficient_history')
        self.assertEqual(compare_history(self.summary(10,None),history,'daily')['status'],'insufficient_data')
        for mutate in [lambda p:p.update(currency='USD'),lambda p:p['period'].update(context_group='other'),lambda p:p['period'].update(definition_version='other'),lambda p:p['metrics']['daily'].update(unit='currency'),lambda p:p['metrics']['daily'].update(value=None,status='unknown'),lambda p:p['completeness'].update(expense='partial')]:
            changed=copy.deepcopy(history);mutate(changed['2031.8'])
            self.assertEqual(compare_history(current,changed,'daily')['sample_count'],1)
    def test_commitment_calendar_unknown_paid_closed_currency(self):
        schedule=[dict(payment_id=f'PAY-{m}',due_date=f'2031-{m:02d}-28',currency='CNY',amount=97,principal=90,interest_and_fees=7,status='confirmed',payment_status='scheduled',evidence_refs=[]) for m in range(2,8)]
        obligation=dict(currency='CNY',obligation_status='active',data_status='confirmed',payment_schedule=schedule,evidence_refs=[])
        state=dict(currency='CNY',data_status='confirmed',obligations=[obligation],evidence_refs=[])
        cash=committed_cashflow(state,'2031-01-31')
        self.assertEqual([m['value'] for m in cash.values()],[97,291,582])
        schedule[0]['payment_status']='paid';schedule[1]['payment_status']='cancelled'
        self.assertEqual(committed_cashflow(state,'2031-01-31')['committed_cashflow_3_months']['value'],97)
        obligation['obligation_status']='settled'
        self.assertTrue(all(m['value']==0 for m in committed_cashflow(state,'2031-01-31').values()))
        for mutation in [lambda s:s.update(data_status='unknown'),lambda s:s['obligations'][0].update(currency='USD'),lambda s:s['obligations'][0].update(obligation_status='active',payment_schedule=None)]:
            changed=copy.deepcopy(state);mutation(changed)
            self.assertTrue(all(m['value'] is None for m in committed_cashflow(changed,'2031-01-31').values()))


if __name__=='__main__':unittest.main()
