"""Deterministic report facts from audited events; no automatic semantics."""
from __future__ import annotations

import argparse
import copy
from decimal import Decimal
from pathlib import Path

from common import (PACKAGE, SCHEMA, VERSION, digest, envelope, period_dir, read_json,
                    ref, total, write_json)
from history_metrics import committed_cashflow, compare_history
from validate_report import FACT_FILES, audit_facts, require, validate_state


def metric(key,value,currency,refs,status='confirmed',unit='currency'):
    return dict(value=value,status=status,unit=unit,currency=None if unit in ('ratio','count') else currency,
                confidence='高' if status=='confirmed' else None,
                definition=SCHEMA['metric_definitions'][key],evidence_refs=refs)


def aggregate(events, period, scope, completeness, currency, refs):
    relevant=[e for e in events if e['period_id']==period]
    spending=[e for e in relevant if e['economic_type'] in ('消费','代付垫资')]
    uncertainty=any(e['data_status']!='confirmed' for e in relevant)
    expense_status='unknown' if uncertainty else 'confirmed' if completeness['expense']=='complete' else 'partial'
    income_status='unknown' if uncertainty else 'confirmed' if completeness['income']=='complete' else 'partial'
    expense=None if uncertainty else total(e['net_expense'] for e in spending)
    income=None if uncertainty else total(e['income_amount'] for e in relevant)
    result=dict(net_expense=metric('net_expense',expense,currency,refs,expense_status),
                real_income=metric('real_income',income,currency,refs,income_status))
    both=expense is not None and income is not None
    surplus=float(Decimal(str(income))-Decimal(str(expense))) if both else None
    result['net_surplus']=metric('net_surplus',surplus,currency,refs,'confirmed' if both and expense_status==income_status=='confirmed' else 'partial' if both else 'unknown')
    ratio=surplus/income if both and income>0 and expense_status==income_status=='confirmed' else None
    result['retention_ratio']=metric('retention_ratio',ratio,currency,refs,'confirmed' if ratio is not None else 'not_applicable' if both and income==0 and income_status=='confirmed' else 'unknown',unit='ratio')
    for key,flag in [('daily_living_baseline','baseline_included'),('daily_personal_baseline','personal_baseline_included')]:
        reliable=expense_status=='confirmed' and not any(e[flag] is None for e in spending)
        value=total(e['net_expense'] for e in spending if e[flag] is True)/scope['observed_days'] if reliable else None
        result[key]=metric(key,value,currency,refs,'confirmed' if reliable else 'unknown',unit='currency_per_day')
    cash=[e for e in events if e['cashflow_period']==period]
    for key,direction in [('cash_outflow','支出'),('cash_inflow','收入')]:
        value=total(e['cashflow_amount'] for e in cash if e['cashflow_direction']==direction)
        status='confirmed' if completeness['expense' if direction=='支出' else 'income']=='complete' and not uncertainty else 'partial'
        result[key]=metric(key,value,currency,refs,status)
    categories=[]
    if expense is not None:
        for category in sorted({e['category_l1'] for e in spending}):
            rows=[e for e in spending if e['category_l1']==category]
            categories.append(dict(category_l1=category,amount=total(e['net_expense'] for e in rows),
                                   count=len(rows),currency=currency,evidence_refs=refs))
    return result,categories


def merged_entities(existing, changes):
    # Lifecycle and automatic revisions are generated in the audited fact layer.
    rows={r[next(k for k in ('goal_id','obligation_id') if k in r)]:copy.deepcopy(r) for r in existing}
    for r in changes:
        key=next(k for k in ('goal_id','obligation_id') if k in r)
        previous=rows.get(r[key])
        if previous and previous!=r and 'goal_id' in r and previous['revisions']:
            incoming={k:v for k,v in r.items() if k!='revisions'}
            if any(revision['reason']=='按已接受目标的原口径反馈' and revision['before']==incoming for revision in previous['revisions']):
                continue
        if previous and previous!=r:
            require(r['revisions'][:len(previous['revisions'])]==previous['revisions'],'实体更新必须保留已有修订')
            before={k:v for k,v in previous.items() if k!='revisions'}
            after={k:v for k,v in r.items() if k!='revisions'}
            if before!=after:
                require(any(rev['before']==before and rev['after']==after for rev in r['revisions'][len(previous['revisions']):]),'实体变更缺少准确的前后快照修订')
        rows[r[key]]=copy.deepcopy(r)
    return [rows[key] for key in sorted(rows)]


def corrected_history(root,events,links=()):
    history=copy.deepcopy(read_json(Path(root)/'state/period_summary.json',dict(periods={}))['periods'])
    affected={e['period_id'] for e in events}
    for pid in affected & history.keys():
        previous=history[pid]
        if events and previous['currency']!=events[0]['currency']:
            continue
        snapshots={e['event_id']:e for e in previous['event_snapshots']}
        for event in events:
            if event['period_id']==pid and event['event_id'] in snapshots:
                snapshots[event['event_id']]=copy.deepcopy(event)
        previous['event_snapshots']=[snapshots[key] for key in sorted(snapshots)]
        relevant_ids=set(snapshots)
        link_rows={l['match_link_id']:l for l in previous['link_snapshots']}
        for link in links:
            if link['source_event_id'] in relevant_ids or link['target_event_id'] in relevant_ids:
                link_rows[link['match_link_id']]=copy.deepcopy(link)
        previous['link_snapshots']=[link_rows[key] for key in sorted(link_rows)]
        if previous['event_snapshots']:
            refs=[]
            for e in previous['event_snapshots']:
                refs.extend(e['evidence_refs'])
            previous['metrics'],previous['categories']=aggregate(previous['event_snapshots'],pid,previous['period'],previous['completeness'],previous['currency'],refs)
    return history


def build_data(root,period,facts):
    ctx=facts['analysis_context'];raw=facts['standardized']
    events=facts['events_file']['economic_events']
    event_refs=[ref(root,period_dir(root,period)/FACT_FILES['events_file'],event_ids=[e['event_id'] for e in events])] if events else [ref(root,period_dir(root,period)/FACT_FILES['events_file'])]
    metrics,categories=aggregate(events,period,ctx['period'],ctx['completeness'],ctx['currency'],event_refs)
    prior_goals=read_json(Path(root)/'state/goals.json',dict(goals=[]))['goals']
    prior_obligations=read_json(Path(root)/'state/obligations.json',dict(currency=None,data_status='unknown',obligations=[],evidence_refs=[],revisions=[]))
    goals=merged_entities(prior_goals,ctx['goal_changes'])
    obligations=merged_entities(prior_obligations['obligations'],ctx['obligation_changes'])
    goals=[g for g in goals if g['currency']==ctx['currency']]
    obligations=[o for o in obligations if o['currency']==ctx['currency']]
    for g in goals:
        if g['goal_status'] in ('accepted','achieved','missed','insufficient_data') and g['target_period']==period:
            before={k:copy.deepcopy(v) for k,v in g.items() if k!='revisions'}
            m=metrics.get(g['metric_key'])
            require(g['definition_version']==ctx['period']['definition_version'],'目标口径已变化，应先确认修订')
            if not m or m['status']!='confirmed' or g['operator']=='condition':
                g.update(actual_value=None,goal_status='insufficient_data')
            else:
                actual=m['value'];target=g['target_value']
                passed=actual<=target if g['operator']=='<=' else actual>=target if g['operator']=='>=' else target['low']<=actual<=target['high']
                g.update(actual_value=actual,goal_status='achieved' if passed else 'missed')
            after={k:v for k,v in g.items() if k!='revisions'}
            if before!=after:
                g['revisions'].append(dict(changed_at=ctx['period']['coverage_end']+'T23:59:59',reason='按已接受目标的原口径反馈',before=before,after=copy.deepcopy(after),evidence_refs=event_refs))
    obligation_state=dict(currency=ctx['currency'],data_status='confirmed' if ctx['completeness']['obligations']=='complete' else 'partial' if ctx['completeness']['obligations']=='partial' else 'unknown',
                          obligations=obligations,evidence_refs=ctx['confirmation_refs'])
    metrics.update(committed_cashflow(obligation_state,ctx['period']['coverage_end'],ctx['currency']))
    history=corrected_history(root,events,facts['links_file']['match_links'])
    current=dict(period_id=period,currency=ctx['currency'],amount_precision=ctx['amount_precision'],period=ctx['period'],metrics=metrics,
                 completeness=ctx['completeness'],data_status='confirmed')
    comparison=compare_history(current,history,'daily_living_baseline')
    tables={}
    table_sources=dict(raw_record=raw['raw_records'],normalized_record=raw['normalized_records'],economic_event=events,match_link=facts['links_file']['match_links'])
    for name,rows in table_sources.items():
        cols=SCHEMA['audit_display_fields'][name]
        filename=FACT_FILES['standardized'] if name in ('raw_record','normalized_record') else FACT_FILES['events_file'] if name=='economic_event' else FACT_FILES['links_file']
        tables[name]=dict(entity=name,columns=cols,rows=[{k:r[k] for k in cols} for r in rows],evidence_refs=[ref(root,period_dir(root,period)/filename)])
    inputs=[ref(root,period_dir(root,period)/filename,freeze=False) for filename in FACT_FILES.values()]
    return envelope(period,publication_status='final',currency=ctx['currency'],amount_precision=ctx['amount_precision'],period=ctx['period'],
                    metrics=metrics,categories=categories,completeness=ctx['completeness'],comparison=comparison,
                    goals=goals,obligations=obligations,audit_tables=tables,source_manifest=raw['source_manifest'],input_manifest=inputs)


def prepare(root,period):
    facts=audit_facts(root,period)
    errors=validate_state(root)
    require(not errors,'\n'.join(errors))
    data=build_data(root,period,facts)
    dest=period_dir(root,period)/'处理结果'
    write_json(dest/'report_data.json',data)
    # Only seed a review draft. An Agent explicitly reviews and binds the final copy.
    template=read_json(PACKAGE/'assets/templates/report_copy.zh-CN.json')
    template.update(schema_version=VERSION,period_id=period,data_sha256=digest(data))
    write_json(dest/'report_copy.draft.json',template)
    return data,template


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--period',required=True)
    a=p.parse_args();prepare(a.root,a.period)
    print('report_data 已构造；请审核 report_copy.draft.json 后保存为 report_copy.json')


if __name__=='__main__':
    main()
