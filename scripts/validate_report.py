"""Executable fact, evidence, presentation and state boundaries."""
from __future__ import annotations

import argparse
import copy
from calendar import monthrange
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from string import Formatter

from common import (SCHEMA, VERSION, check_contract, digest, money, number, period_dir,
                    period_key, period_of, read_json, relative_file, resolve, sha)


FACT_FILES={'standardized': '处理结果/原始标准化.json', 'events_file': '处理结果/经济事件.json',
            'links_file': '处理结果/关联记录.json', 'confirmations_file': '执行记录/确认记录.json',
            'analysis_context': '处理结果/analysis_context.json'}


def require(condition, message):
    if not condition:
        raise ValueError(message)


def version(value):
    require(value.get('schema_version')==VERSION, '契约版本必须是 2.0；不自动迁移历史')


def unique(rows, key):
    ids=[r[key] for r in rows]
    require(len(ids)==len(set(ids)), key+' 重复')
    return {r[key]:r for r in rows}


def evidence(root, refs, required=False, durable=False):
    require(not required or bool(refs),'缺少必需证据')
    for r in refs:
        check_contract(r,'evidence_ref')
        path=relative_file(root,r['file'])
        require(path.is_file(), '证据文件不存在: '+r['file'])
        require(sha(path)==r['sha256'],'证据哈希变化: '+r['file'])
        if durable and any(part in ('处理结果','执行记录') for part in Path(r['file']).parts):
            require('审计快照' in Path(r['file']).parts,'长期可追溯证据须使用 common.ref 生成不可变审计快照引用')
        keys={'record_ids':'record_id','event_ids':'event_id','confirmation_ids':'confirmation_id'}
        if any(k in r for k in keys):
            require(path.suffix.lower()=='.json','带 ID 的证据必须引用结构化 JSON')
            document=read_json(path)
            found=defaultdict(set)
            require(isinstance(document,dict),'ID 证据须引用实体文件')
            for collection,key in [('raw_records','record_id'),('normalized_records','record_id'),
                                   ('economic_events','event_id'),('confirmations','confirmation_id')]:
                for entity in document.get(collection,[]):
                    if isinstance(entity,dict) and isinstance(entity.get(key),str):
                        found[key].add(entity[key])
            for plural,key in keys.items():
                if plural in r:
                    require(bool(r[plural]) and len(r[plural])==len(set(r[plural])),'证据 ID 列表为空或重复')
                    require(set(r[plural])<=found[key],'证据引用 ID 不存在: '+r['file'])
        if r.get('row') is not None:
            require(r['row']>0,'证据行号必须为正')
            parts=Path(r['file']).parts
            require(parts and len(parts)>2 and parts[1]=='原始数据','行坐标只用于已登记的原始证据')
            raw=read_json(Path(root)/parts[0]/'处理结果/原始标准化.json',{})
            m=next((m for m in raw.get('source_manifest',[]) if m['file']==r['file']),None)
            require(m is not None and m['mapping'] is not None,'行坐标缺已登记的读取映射')
            from preprocess import source_rows
            locations={(sheet,row) for sheet,row,_ in source_rows(path,m['mapping'])}
            require((r.get('sheet'),r['row']) in locations,'证据行/工作表坐标无法解析')


def nested_evidence(root, value):
    if isinstance(value,dict):
        for key,child in value.items():
            if key in ('evidence_refs','acceptance_evidence_refs','confirmation_refs'):
                evidence(root,child,durable=True)
            else:
                nested_evidence(root,child)
    elif isinstance(value,list):
        for child in value:
            nested_evidence(root,child)


def check_scope(period, scope):
    start,end=date.fromisoformat(scope['coverage_start']),date.fromisoformat(scope['coverage_end'])
    year,month=period_key(period)
    require(start<=end and (start.year,start.month)==(year,month) and (end.year,end.month)==(year,month),'当期范围越出所选月份')
    require(scope['observed_days']>0 and scope['observed_days']<=(end-start).days+1,'有效观测日数越界')
    if scope['is_full_period']:
        require(start.day==1 and end.day==monthrange(year,month)[1] and scope['observed_days']==end.day,'完整月份范围不成立')


def revisions(root, values):
    for r in values:
        check_contract(r,'revision')
        evidence(root,r['evidence_refs'],True)
        require(r['before']!=r['after'],'修订前后相同')


def validate_goals(root, rows):
    unique(rows,'goal_id')
    for g in rows:
        check_contract(g,'goal')
        evidence(root,g['evidence_refs'],True)
        revisions(root,g['revisions'])
        require(period_key(g['target_period'])>=period_key(g['origin_period']),'目标期限先于起源期')
        target=g['target_value']
        if isinstance(target,dict):
            check_contract(target,'goal_target')
            if g['operator']=='range':
                require(set(target)=={'low','high'} and target['low']<=target['high'],'目标区间非法')
            elif g['operator']=='condition':
                require(set(target)=={'condition'},'条件目标非法')
            else:
                raise ValueError('数值目标不能采用对象目标')
        else:
            require(number(target) and g['operator'] in ('<=','>='),'目标数值或操作符非法')
        if g['goal_status'] in ('accepted','achieved','missed','insufficient_data'):
            evidence(root,g['acceptance_evidence_refs'],True)
            require(any(r.get('confirmation_ids') for r in g['acceptance_evidence_refs']),'目标接受必须引用确认 ID')
        if g['goal_status'] in ('achieved','missed'):
            require(number(g['actual_value']),'目标完成判定缺少实际值')


def validate_obligations(root, rows, precision=2):
    unique(rows,'obligation_id')
    for o in rows:
        check_contract(o,'obligation')
        evidence(root,o['evidence_refs'],True)
        revisions(root,o['revisions'])
        if o['service_start'] and o['service_end']:
            require(o['service_start']<=o['service_end'],'义务服务日期倒置')
        if o['remaining_principal'] is not None:
            money(o['remaining_principal'],precision)
        if o['data_status']=='unknown':
            require(o['remaining_principal'] is None and o['payment_schedule'] is None,'未知义务不能伪造本金/计划')
        if o['obligation_status']=='settled':
            require(o['remaining_principal'] in (0,None),'结清义务仍有本金')
        if o['payment_schedule'] is None:
            continue
        unique(o['payment_schedule'],'payment_id')
        for item in o['payment_schedule']:
            require(item['currency']==o['currency'],'付款计划币种不一致')
            evidence(root,item['evidence_refs'],item['status']=='confirmed')
            for key in ('amount','principal','interest_and_fees'):
                if item[key] is not None:
                    money(item[key],precision)
            if item['status']=='unknown':
                require(all(item[k] is None for k in ('amount','principal','interest_and_fees')),'未知计划金额须为 null')
            if item['status']=='confirmed':
                require(item['due_date'] is not None and item['amount'] is not None,'已确认付款缺日期或金额')
            if all(item[k] is not None for k in ('amount','principal','interest_and_fees')):
                require(Decimal(str(item['amount']))==Decimal(str(item['principal']))+Decimal(str(item['interest_and_fees'])),'本金费用与付款总额不符')
            if o['obligation_status']=='settled':
                require(item['payment_status'] in ('paid','cancelled'),'结清义务仍有未付计划')


def read_facts(root, period):
    base=period_dir(root,period)
    result={}
    for kind,relative in FACT_FILES.items():
        path=relative_file(root,(base/relative).relative_to(Path(root).resolve()).as_posix())
        require(path.is_file(),'缺少本期输入: '+relative)
        value=read_json(path)
        check_contract(value,kind)
        version(value)
        require(value['period_id']==period,'本期输入账期不一致')
        result[kind]=value
    return result


def audit_facts(root, period, facts=None):
    facts=read_facts(root,period) if facts is None else facts
    for kind,value in facts.items():
        check_contract(value,kind)
        version(value)
        require(value['period_id']==period,'本期输入账期不一致')
    raw=facts['standardized']
    ctx=facts['analysis_context']
    precision=ctx['amount_precision']
    require(0<=precision<=8,'金额精度越界')
    require(raw['currency']==ctx['currency'] and raw['amount_precision']==precision,'标准化与上下文币种/精度不一致')
    check_scope(period,ctx['period'])
    require(not any(v=='complete' for k,v in ctx['completeness'].items() if k!='missing_sources') or bool(ctx['confirmation_refs']), '完整性声明必须有确认依据')
    evidence(root,ctx['confirmation_refs'],durable=True)
    require(all(r.get('confirmation_ids') for r in ctx['confirmation_refs']),'当期上下文须引用确认 ID')
    if raw['rejected_rows'] or any(m['read_status']=='needs_reading' for m in raw['source_manifest']):
        require(ctx['completeness']['expense']!='complete' and ctx['completeness']['income']!='complete','拒绝行/未读取证据存在时不能宣称收支完整')
    manifests=unique(raw['source_manifest'],'file')
    raw_by_id=unique(raw['raw_records'],'record_id')
    normalized=unique(raw['normalized_records'],'record_id')
    from preprocess import mapped_record, source_rows
    source_cache={}
    for m in raw['source_manifest']:
        path=relative_file(root,m['file'])
        require(path.is_file() and sha(path)==m['sha256'],'源文件缺失或哈希变化')
        if m['read_status']=='read':
            require(m['mapping'] is not None,'已读取文件缺映射')
            source_cache[m['file']]={(sheet,row):fields for sheet,row,fields in source_rows(path,m['mapping'])}
            for (sheet,row),fields in source_cache[m['file']].items():
                loc=dict(file=m['file'],sha256=m['sha256'],sheet=sheet,row=row)
                try:
                    expected=mapped_record(fields,m['mapping'],loc,ctx['currency'],precision)
                except ValueError as exc:
                    require(any(r['file']==m['file'] and r['sheet']==sheet and r['row']==row and r['raw_fields']==fields and r['reason']==str(exc) for r in raw['rejected_rows']),'源文件拒绝行被遗漏/篡改')
                else:
                    require(expected['record_id'] in raw_by_id,'源文件有效行被遗漏')
        require(m['record_count']==sum(r['source_location']['file']==m['file'] for r in raw_by_id.values()),'源文件记录数不一致')
    for r in raw_by_id.values():
        money(r['raw_amount'],precision)
        require(r['currency']==ctx['currency'],'异币种原始记录')
        loc=r['source_location']
        require(loc['file'] in manifests and loc['sha256']==manifests[loc['file']]['sha256'],'原始坐标未登记')
        fields=source_cache.get(loc['file'],{}).get((loc['sheet'],loc['row']))
        require(fields==r['raw_fields'],'原始行内容或坐标与证据不符')
        expected=mapped_record(fields,manifests[loc['file']]['mapping'],loc,ctx['currency'],precision)
        require(expected==r,'原始金额/字段被覆盖或伪造')
    assigned_raw=set()
    for n in normalized.values():
        require(n['raw_record_ids'] and len(n['raw_record_ids'])==len(set(n['raw_record_ids'])),'标准化原始引用为空/重复')
        require(set(n['raw_record_ids'])<=raw_by_id.keys(),'标准化引用原始 ID 不存在')
        require(not assigned_raw.intersection(n['raw_record_ids']),'原始记录重复标准化')
        assigned_raw.update(n['raw_record_ids'])
        originals=[raw_by_id[rid] for rid in n['raw_record_ids']]
        require(n['source_locations']==[r['source_location'] for r in originals],'标准化坐标与原始不一致')
        keys=set(n)-{'record_id','raw_record_ids','source_locations'}
        require(all(all(n[k]==r[k] for k in keys) for r in originals),'标准化覆盖原始事实')
        if len(originals)>1:
            require(n['account_key'] and n['original_trade_no'] and all(manifests[r['source_location']['file']]['mapping']['transaction_id_is_stable'] for r in originals),'无账户或无稳定交易号不能自动归并')
    require(assigned_raw==raw_by_id.keys(),'原始记录未进入标准化')
    events=unique(facts['events_file']['economic_events'],'event_id')
    links=unique(facts['links_file']['match_links'],'match_link_id')
    confirmations=unique(facts['confirmations_file']['confirmations'],'confirmation_id')
    for item in confirmations.values():
        require(set(item['record_ids'])<=normalized.keys() and set(item['event_ids'])<=events.keys(),'确认记录引用 ID 不存在')
        evidence(root,item['evidence_refs'],True,durable=True)
    allocations=defaultdict(Decimal)
    refund=defaultdict(Decimal)
    aa=defaultdict(Decimal)
    source_applied=defaultdict(Decimal)
    pairs=set()
    for link in links.values():
        require(link['currency']==ctx['currency'],'关联币种不一致')
        amount=money(link['applied_amount'],precision)
        evidence(root,link['evidence_refs'],True,durable=True)
        require(set(link['record_ids'])<=normalized.keys(),'关联记录 ID 不存在')
        require(len(link['record_ids'])==len(set(link['record_ids'])),'关联记录 ID 重复')
        for key in ('source_event_id','target_event_id'):
            require(link[key] is None or link[key] in events,'关联事件 ID 不存在')
        if link['match_type'] in ('退款匹配','AA匹配'):
            require(link['data_status']=='confirmed','正式调整必须已确认')
            sid,tid=link['source_event_id'],link['target_event_id']
            require(sid and tid and sid!=tid,'调整源/目标缺失或相同')
            key=(sid,tid,link['match_type'])
            require(key not in pairs,'同一调整重复应用')
            pairs.add(key)
            s,t=events[sid],events[tid]
            require(s['economic_type']==('退款' if link['match_type']=='退款匹配' else 'AA回款') and s['cashflow_direction']=='收入','调整来源性质错误')
            require(t['economic_type'] in ('消费','代付垫资') and t['data_status']=='confirmed','调整目标不是已确认支出事件')
            require(s['trade_time']>=t['trade_time'],'回款先于目标支出')
            source_applied[sid]+=amount
            (refund if link['match_type']=='退款匹配' else aa)[tid]+=amount
        else:
            require(amount==0,'去重/资金链不能产生冲减金额')
            require(len(link['record_ids'])>=2 and link['data_status']=='confirmed','去重/资金链须有已确认的记录关系')
            if link['match_type']=='跨平台重复':
                records=[normalized[r] for r in link['record_ids']]
                require(all(r['raw_amount']==records[0]['raw_amount'] and r['flow_direction']==records[0]['flow_direction'] for r in records),'重复关系金额/方向不符')
    for eid,e in events.items():
        require(e['currency']==ctx['currency'],'事件币种不一致')
        period_key(e['period_id']);period_key(e['cashflow_period'])
        require(e['cashflow_period']==period_of(e['trade_time']),'事件现金流归期与实际日期不符')
        for key in ('cashflow_amount','gross_expense','refund_amount','reimbursement_amount','net_expense','income_amount','principal_amount','unsettled_amount'):
            money(e[key],precision)
        gross,rr,ar,net=(Decimal(str(e[k])) for k in ('gross_expense','refund_amount','reimbursement_amount','net_expense'))
        require(net==gross-rr-ar,'事件净额与调整不勾稽')
        require(rr==refund[eid] and ar==aa[eid],'事件调整与关联记录不一致')
        require(source_applied[eid]<=Decimal(str(e['cashflow_amount'])),'同一回款累计分配超额')
        require(e['unsettled_amount']<=e['net_expense'],'未结算金额超过剩余承担额')
        evidence(root,e['evidence_refs'],True,durable=True)
        require(e['record_allocations'],'事件必须有原始分配')
        unique(e['record_allocations'],'record_id')
        primary=[]
        for allocation in e['record_allocations']:
            rid=allocation['record_id']
            require(rid in normalized,'事件分配记录 ID 不存在')
            amount=money(allocation['amount'],precision)
            allocations[rid]+=amount
            r=normalized[rid]
            if allocation['role']=='primary':
                require(r['flow_direction']==e['cashflow_direction'],'主流水方向与事件不符')
                primary.append(amount)
                require(period_of(r['trade_time'])==e['cashflow_period'],'主流水归期不符')
            else:
                kind='跨平台重复' if allocation['role']=='duplicate' else '资金链'
                require(any(l['match_type']==kind and rid in l['record_ids'] and
                            any(a['record_id'] in l['record_ids'] and a['role']=='primary' for a in e['record_allocations'])
                            for l in links.values()),'次流水缺少同事件主流水关联依据')
        require(primary and sum(primary,Decimal(0))==Decimal(str(e['cashflow_amount'])),'事件现金流与主流水分配不符')
        kind=e['economic_type']
        if kind in ('消费','代付垫资'):
            require(e['cashflow_direction']=='支出' and gross==Decimal(str(e['cashflow_amount'])) and e['income_amount']==0 and e['principal_amount']==0,'消费/垫资资金性质不符')
            require(e['category_l1'] is not None,'消费缺少经济用途分类')
        else:
            require(gross==0 and net==0 and rr==0 and ar==0,'非消费不能计入支出')
        if kind=='真实收入':
            require(e['cashflow_direction']=='收入' and e['income_amount']==e['cashflow_amount'],'真实收入金额不符')
        else:
            require(e['income_amount']==0,'退款/回款/流转等不能计真实收入')
        if kind=='偿还本金':
            require(e['cashflow_direction']=='支出' and e['principal_amount']==e['cashflow_amount'],'本金拆分不符')
        else:
            require(e['principal_amount']==0,'非本金事件不能计本金偿付')
        if e['period_id']==period and e['cashflow_period']==period:
            require(ctx['period']['coverage_start']<=e['trade_time'][:10]<=ctx['period']['coverage_end'],'当期事件超出已确认范围')
    for rid,n in normalized.items():
        require(allocations[rid]<=Decimal(str(n['raw_amount'])),'流水分配超额或重复计入')
        if period_of(n['trade_time'])==period:
            require(allocations[rid]==Decimal(str(n['raw_amount'])),'当期流水未被完整审计分配')
    # Carry already audited allocations across periods; a receipt cannot be spent again
    # merely by omitting its older links from this month's input.
    past=read_json(Path(root)/'state/period_summary.json',dict(periods={}))['periods']
    cumulative_links={};cumulative_events={}
    for p in past.values():
        for e in p['event_snapshots']:cumulative_events[e['event_id']]=e
        for l in p['link_snapshots']:cumulative_links[l['match_link_id']]=l
    cumulative_events.update(events);cumulative_links.update(links)
    cumulative=defaultdict(Decimal);seen_pairs=set()
    for l in cumulative_links.values():
        if l['match_type'] in ('退款匹配','AA匹配') and l['currency']==ctx['currency']:
            pair=(l['source_event_id'],l['target_event_id'],l['match_type'])
            require(pair not in seen_pairs,'跨期同一调整重复应用')
            seen_pairs.add(pair)
            cumulative[l['source_event_id']]+=Decimal(str(l['applied_amount']))
    for eid,amount in cumulative.items():
        require(eid in cumulative_events and amount<=Decimal(str(cumulative_events[eid]['cashflow_amount'])),'跨期回款累计分配超额')
    nested_evidence(root,facts)
    validate_goals(root,ctx['goal_changes'])
    validate_obligations(root,ctx['obligation_changes'],precision)
    require(all(g['currency']==ctx['currency'] for g in ctx['goal_changes']) and all(o['currency']==ctx['currency'] for o in ctx['obligation_changes']),'当期目标/义务混入异币种')
    return facts


def validate_state(root, candidates=None):
    root=Path(root).resolve()
    errors=[]
    candidates=candidates or {}
    for name,kind in [('period_summary.json','period_state'),('goals.json','goal_state'),('obligations.json','obligation_state')]:
        path=Path(root)/'state'/name
        if name not in candidates and not path.exists():
            continue
        try:
            path=relative_file(root,path.relative_to(Path(root).resolve()).as_posix())
            value=candidates.get(name) if name in candidates else read_json(path)
            check_contract(value,kind);version(value)
            nested_evidence(root,value)
            if kind=='period_state':
                for pid,p in value['periods'].items():
                    require(pid==p['period_id'],'摘要主键/账期不一致')
                    check_scope(pid,p['period'])
                    revisions(root,p['revisions'])
                    for metric in p['metrics'].values():
                        check_metric(metric,p['currency'])
                    for e in p['event_snapshots']:
                        check_contract(e,'economic_event')
                        require(e['period_id']==pid and e['currency']==p['currency'],'摘要事件账期/币种不符')
                    unique(p['event_snapshots'],'event_id')
                    unique(p['link_snapshots'],'match_link_id')
                    for m in p['source_manifest']:
                        source=relative_file(root,m['file'])
                        require(source.is_file() and sha(source)==m['sha256'],'历史源文件缺失或变化')
                    supporting=list(p['evidence_refs'])
                    for revision in p['revisions']:
                        supporting.extend(revision['evidence_refs'])
                    supported=[];supported_links=[]
                    for r in supporting:
                        f=relative_file(root,r['file'])
                        if f.suffix.lower()=='.json':
                            document=read_json(f)
                            if isinstance(document,dict):
                                supported.extend(document.get('economic_events',[]))
                                supported_links.extend(document.get('match_links',[]))
                    require(all(e in supported for e in p['event_snapshots']),'摘要事件快照偏离审计证据')
                    require(all(l in supported_links for l in p['link_snapshots']),'摘要关联快照偏离审计证据')
                    from prepare_report import aggregate
                    expected,_=aggregate(p['event_snapshots'],pid,p['period'],p['completeness'],p['currency'],p['evidence_refs'])
                    for key,m in expected.items():
                        require(key in p['metrics'] and all(p['metrics'][key][field]==m[field] for field in ('value','status','unit','currency','definition')),'摘要指标偏离事件快照: '+key)
            elif kind=='goal_state':
                validate_goals(root,value['goals'])
            else:
                summaries=candidates.get('period_summary.json',read_json(Path(root)/'state/period_summary.json',{'periods':{}}))
                precisions=[p['amount_precision'] for p in summaries['periods'].values() if p['currency']==value['currency']]
                validate_obligations(root,value['obligations'],max(precisions,default=8))
                revisions(root,value['revisions'])
                if value['data_status']=='confirmed':
                    require(value['currency'] is not None,'确认义务覆盖缺币种')
                    evidence(root,value['evidence_refs'],True)
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors.append(name+': '+str(exc))
    return errors


def check_metric(m,currency):
    if m['status'] in ('unknown','not_applicable','insufficient_data','insufficient_history'):
        require(m['value'] is None,'未知/不适用指标须为 null')
    if m['status']=='confirmed':
        require(m['value'] is not None,'已确认指标缺值')
    require(m['currency']==(None if m['unit'] in ('ratio','count') else currency),'指标币种/单位不符')


def validate_inputs(data, copy_text, schema=None, period=None):
    errors=[]
    try:
        check_contract(data,'report_data');check_contract(copy_text,'report_copy')
        version(data);version(copy_text)
        require(data['period_id']==copy_text['period_id'] and (period is None or data['period_id']==period),'展示输入账期不一致')
        require(copy_text['data_sha256']==digest(data),'文案绑定陈旧 report_data')
        check_scope(data['period_id'],data['period'])
        for m in data['metrics'].values():
            check_metric(m,data['currency'])
        for name,table in data['audit_tables'].items():
            allowed=SCHEMA['audit_display_fields'].get(table['entity'])
            require(allowed is not None and name==table['entity'],'审计表实体非法')
            cols=table['columns']
            require(cols and len(cols)==len(set(cols)) and set(cols)<=set(allowed),'审计展示含内部备注/非法字段')
            for row in table['rows']:
                require(isinstance(row,dict) and set(row)==set(cols),'审计行字段不符')
                fields=SCHEMA['contracts'][table['entity']]['fields']
                # Validate a projection by supplying omitted fields from a typed complete row is avoided;
                # validate each projected field with a small schema wrapper.
                for key,value in row.items():
                    spec=fields[key]
                    if spec=='number':
                        require(number(value),'审计投影金额非法')
                    require(key in allowed,'审计字段未获实体授权')
        needed=set(SCHEMA['copy_strings'])
        needed.update('metric.'+k for k in data['metrics'])
        for table in data['audit_tables'].values():
            needed.update('field.'+k for k in table['columns'])
        needed.update('status.'+v for v in SCHEMA['enums']['data_status'])
        needed.update('status.'+v for v in SCHEMA['enums']['completeness_status'])
        require(needed<=copy_text['strings'].keys(),'缺少可见标题、表头或状态文案')
        unique(copy_text['sections'],'copy_id')
        for section in copy_text['sections']:
            require(section['data_refs'] and len(section['data_refs'])==len(set(section['data_refs'])),'动态文案须绑定真实字段')
            for reference in section['data_refs']:
                bound=resolve(data,reference)
                require(bound is None or isinstance(bound,(str,int,float,bool)),'动态文案仅绑定标量字段')
            placeholders=[]
            for _,field,fmt,conv in Formatter().parse(section['text']):
                if field is not None:
                    require(field in section['data_refs'] and conv is None and '{' not in fmt and '[' not in field,'非法动态占位绑定')
                    placeholders.append(field)
            require(placeholders,'动态文字须通过占位符绑定数据，静态文字放 strings')
            condition=section['visible_when']
            if condition:
                value=resolve(data,condition['data_ref'])
                statuses=set(sum((SCHEMA['enums'][k] for k in ('data_status','completeness_status','goal_status','obligation_status','payment_status')),[]))
                require(isinstance(value,str) and value in statuses and condition['status_in'] and set(condition['status_in'])<=statuses,'动态可见性须引用状态字段')
        comparison=data['comparison']
        require(comparison['sample_count']==len(comparison['reference_period_ids']) and len(set(comparison['reference_period_ids']))==comparison['sample_count'],'历史样本数不符')
        require(all(period_key(p)<period_key(data['period_id']) for p in comparison['reference_period_ids']),'历史参考含当前/未来期')
        if comparison['sample_count']<2:
            require(comparison['reference_value'] is None and comparison['normal_range'] is None,'历史不足仍生成趋势')
        if comparison['sample_count']<6:
            require(comparison['normal_range'] is None,'六期不足仍生成正常区间')
        amount=data['metrics']['net_expense']['value']
        if amount is not None:
            require(sum((Decimal(str(c['amount'])) for c in data['categories']),Decimal(0))==Decimal(str(amount)),'分类不勾稽')
        unique(data['categories'],'category_l1')
    except (ValueError,KeyError,IndexError,TypeError) as exc:
        errors.append(str(exc))
    return errors


def load_report_inputs(root, period):
    facts=audit_facts(root,period)
    state_errors=validate_state(root)
    require(not state_errors,'\n'.join(state_errors))
    base=period_dir(root,period)
    data=read_json(base/'处理结果/report_data.json')
    copy_text=read_json(base/'处理结果/report_copy.json')
    errors=validate_inputs(data,copy_text,period=period)
    require(not errors,'\n'.join(errors))
    for r in data['input_manifest']:
        evidence(root,[r])
    nested_evidence(root,data);nested_evidence(root,copy_text)
    # Regenerate every deterministic fact. A new digest alone cannot legitimise forged metrics.
    from prepare_report import build_data
    expected=build_data(root,period,facts)
    require(data==expected,'report_data 已陈旧或偏离已审计事实，请重新 prepare 并审核文案')
    return data,copy_text


def validate(root,period):
    try:
        load_report_inputs(root,period)
        return []
    except (ValueError,KeyError,TypeError,OSError) as exc:
        return [str(exc)]


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--period');p.add_argument('--state',action='store_true');p.add_argument('--facts',action='store_true')
    a=p.parse_args()
    if a.state:
        errors=validate_state(a.root)
    elif a.facts:
        try:
            audit_facts(a.root,a.period);errors=[]
        except (ValueError,KeyError,TypeError,OSError) as exc:
            errors=[str(exc)]
    else:
        errors=validate(a.root,a.period)
    if errors:
        p.exit(1,'\n'.join(errors)+'\n')
    print('校验通过')


if __name__=='__main__':
    main()
