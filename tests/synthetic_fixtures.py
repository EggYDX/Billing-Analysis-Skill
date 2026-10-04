"""Freshly invented source evidence and explicitly constructed Agent fact outputs."""
import copy
from pathlib import Path
import sys

PACKAGE=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(PACKAGE/'scripts'))
from common import VERSION, envelope, period_dir, read_json, ref, stable_id, write_json
from preprocess import intake


def fixture(root,period='2031.4',currency='CNY',precision=2):
    mapping=read_json(PACKAGE/'examples/source_mapping.json')
    mapping['currency']=currency
    filename=Path(root)/'input.csv'
    source=(PACKAGE/'examples/synthetic_bill.csv').read_text(encoding='utf-8')
    y,m=period.split('.')
    source=source.replace('2031-04',f'{y}-{int(m):02d}')
    source=source.replace('FAKE-',f'FAKE-{y}{int(m):02d}-')
    filename.write_text(source,encoding='utf-8')
    raw,_=intake(root,period,[filename],mapping=mapping,currency=currency,amount_precision=precision)
    base=period_dir(root,period)
    records={'FAKE-'+n['original_trade_no'].rsplit('-',1)[-1]:n for n in raw['normalized_records']}
    rawref=ref(root,base/'处理结果/原始标准化.json')
    events=[]
    def event(tx,kind,gross=0,income=0,principal=0,amount=None,role='',baseline=False):
        n=records[tx];amount=n['raw_amount'] if amount is None else amount
        eid=stable_id('EVT',n['record_id'],role)
        e=dict(event_id=eid,period_id=period,cashflow_period=period,trade_time=n['trade_time'],currency=currency,economic_type=kind,
               cashflow_direction=n['flow_direction'],cashflow_amount=amount,record_allocations=[dict(record_id=n['record_id'],amount=amount,role='primary')],
               gross_expense=gross,refund_amount=0,reimbursement_amount=0,net_expense=gross,income_amount=income,principal_amount=principal,unsettled_amount=0,
               category_l1='餐饮' if baseline else '共同费用' if kind=='消费' else None,category_l2=None,expense_attribute='刚需' if baseline else '弹性' if kind=='消费' else '无',
               recurrence_type='经常性' if baseline else '一次性',baseline_included=baseline,personal_baseline_included=kind=='消费',is_adjustable=False,
               data_status='confirmed',confidence='高',evidence_refs=[dict(rawref,record_ids=[n['record_id']])],audit_notes='合成测试内部备注，不应出现在展示输入')
        events.append(e);return e
    meal=event('FAKE-001','消费',gross=37.25,baseline=True)
    shared1=event('FAKE-002','消费',gross=125)
    shared2=event('FAKE-003','消费',gross=70)
    refund=event('FAKE-004','退款')
    returned=event('FAKE-005','AA回款')
    event('FAKE-006','真实收入',income=2600)
    event('FAKE-007','偿还本金',principal=200,amount=200,role='principal')
    fee=event('FAKE-007','消费',gross=3,amount=3,role='fee');fee['category_l1']='金融费用'
    event('FAKE-008','内部转账');event('FAKE-009','内部转账')
    links=[]
    for s,t,kind,amount in [(refund,meal,'退款匹配',18.75),(returned,shared1,'AA匹配',30),(returned,shared2,'AA匹配',50)]:
        field='refund_amount' if kind=='退款匹配' else 'reimbursement_amount'
        t[field]=amount;t['net_expense']-=amount
        links.append(dict(match_link_id=stable_id('LNK',s['event_id'],t['event_id'],kind),match_type=kind,source_event_id=s['event_id'],target_event_id=t['event_id'],record_ids=[],currency=currency,applied_amount=amount,data_status='confirmed',evidence_refs=[rawref],audit_notes='合成关联依据，仅供审计'))
    confirmation=dict(confirmation_id='CONF-SYNTHETIC-SCOPE',question='合成来源是否覆盖完整账期收支与义务？',answer='完全合成情景：已确认完整覆盖，本期无额外义务。',record_ids=[],event_ids=[],evidence_refs=[rawref])
    write_json(base/'执行记录/确认记录.json',envelope(period,confirmations=[confirmation]))
    confirmref=ref(root,base/'执行记录/确认记录.json',confirmation_ids=[confirmation['confirmation_id']])
    import calendar
    days=calendar.monthrange(int(y),int(m))[1]
    ctx=envelope(period,currency=currency,amount_precision=precision,period=dict(coverage_start=f'{y}-{int(m):02d}-01',coverage_end=f'{y}-{int(m):02d}-{days}',observed_days=days,is_full_period=True,context_group='synthetic-normal',definition_version='economic-v2'),completeness=dict(expense='complete',income='complete',obligations='complete',missing_sources=[]),confirmation_refs=[confirmref],goal_changes=[],obligation_changes=[])
    write_json(base/'处理结果/经济事件.json',envelope(period,economic_events=events))
    write_json(base/'处理结果/关联记录.json',envelope(period,match_links=links))
    write_json(base/'处理结果/analysis_context.json',ctx)
    return raw,events,links,ctx


def finalize_copy(root,period):
    from prepare_report import prepare
    from common import digest
    data,draft=prepare(root,period)
    draft['sections']=[dict(copy_id='net-expense',text='净支出为 {metrics.net_expense.value:.2f}。',data_refs=['metrics.net_expense.value'],evidence_refs=data['metrics']['net_expense']['evidence_refs'],visible_when=None)]
    draft['data_sha256']=digest(data)
    write_json(period_dir(root,period)/'处理结果/report_copy.json',draft)
    return data,draft
