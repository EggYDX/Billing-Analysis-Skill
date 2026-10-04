"""Only audited delivery updates keyed state; existing history is preserved."""
from __future__ import annotations

import argparse
import copy
from pathlib import Path

from common import PACKAGE, VERSION, check_contract, digest, period_dir, read_json, relative_file, sha, write_json
from prepare_report import corrected_history
from render_workbook import verify_workbook
from validate_report import audit_facts, load_report_inputs, require, validate_state


def update(root,period):
    root=Path(root).resolve()
    data,copy_text=load_report_inputs(root,period)
    audit=read_json(period_dir(root,period)/'执行记录/交付审计.json')
    check_contract(audit,'delivery_audit')
    require(audit['schema_version']==VERSION and audit['period_id']==period,'交付审计版本/账期不符')
    require(audit['report_data_sha256']==digest(data) and audit['report_copy_sha256']==digest(copy_text),'交付审计已陈旧')
    workbook=relative_file(root,audit['workbook'])
    require(workbook.is_file() and sha(workbook)==audit['workbook_sha256'],'交付工作簿缺失或变化')
    verify_workbook(workbook,data,copy_text)
    facts=audit_facts(root,period)
    events=facts['events_file']['economic_events']
    state_path=root/'state'
    prior=read_json(state_path/'period_summary.json',dict(schema_version=VERSION,periods={}))
    new=copy.deepcopy(prior)
    links=facts['links_file']['match_links']
    history=corrected_history(root,events,links)
    refs=data['audit_tables']['economic_event']['evidence_refs']+data['audit_tables']['match_link']['evidence_refs']
    def revise(before,after,reason):
        if before is None:
            return after
        old={k:v for k,v in before.items() if k!='revisions'}
        changed={k:v for k,v in after.items() if k!='revisions'}
        after['revisions']=copy.deepcopy(before['revisions'])
        if old!=changed:
            after['revisions'].append(dict(changed_at=data['period']['coverage_end']+'T23:59:59',reason=reason,before=old,after=changed,evidence_refs=refs))
        return after
    for pid,p in history.items():
        if pid!=period:
            new['periods'][pid]=revise(prior['periods'][pid],p,'跨期关联回款修订经济净额')
    summary=dict(period_id=period,currency=data['currency'],amount_precision=data['amount_precision'],period=data['period'],
                 data_status='confirmed',metrics=data['metrics'],categories=data['categories'],completeness=data['completeness'],comparison=data['comparison'],
                 source_manifest=data['source_manifest'],evidence_refs=refs,
                 event_snapshots=[e for e in events if e['period_id']==period],
                 link_snapshots=[l for l in links if any(e['period_id']==period and e['event_id'] in (l['source_event_id'],l['target_event_id']) for e in events)],revisions=[])
    new['periods'][period]=revise(prior['periods'].get(period),summary,'本期审计后摘要修订')
    goals=read_json(state_path/'goals.json',dict(schema_version=VERSION,goals=[]))
    goals_by_id={g['goal_id']:g for g in goals['goals']}
    for goal in data['goals']:
        previous=goals_by_id.get(goal['goal_id'])
        updated=copy.deepcopy(goal)
        # Deterministic status feedback retains accepted target and all earlier revisions.
        if previous and previous!=updated:
            old={k:v for k,v in previous.items() if k!='revisions'}
            after={k:v for k,v in updated.items() if k!='revisions'}
            if old!=after and len(updated['revisions'])==len(previous['revisions']):
                updated['revisions'].append(dict(changed_at=data['period']['coverage_end']+'T23:59:59',reason='按已接受目标的原口径反馈',before=old,after=after,evidence_refs=refs))
        goals_by_id[goal['goal_id']]=updated
    goals['goals']=[goals_by_id[k] for k in sorted(goals_by_id)]
    obligations=read_json(state_path/'obligations.json',read_json(PACKAGE/'assets/templates/state/obligations.json'))
    require(obligations['currency'] in (None,data['currency']), '现有义务状态属于另一币种，请使用独立工作区')
    before=copy.deepcopy(obligations)
    by_id={o['obligation_id']:o for o in obligations['obligations']}
    by_id.update({o['obligation_id']:o for o in data['obligations']})
    obligations.update(currency=data['currency'],obligations=[by_id[k] for k in sorted(by_id)],
                       data_status='confirmed' if data['completeness']['obligations']=='complete' else 'partial' if data['completeness']['obligations']=='partial' else 'unknown',
                       evidence_refs=facts['analysis_context']['confirmation_refs'])
    old={k:v for k,v in before.items() if k!='revisions'}
    after={k:v for k,v in obligations.items() if k!='revisions'}
    if old!=after and state_path.joinpath('obligations.json').exists():
        obligations['revisions'].append(dict(changed_at=data['period']['coverage_end']+'T23:59:59',reason='审计后义务覆盖与生命周期更新',before=old,after=after,evidence_refs=refs))
    staged=[('period_summary.json',new,'period_state'),('goals.json',goals,'goal_state'),('obligations.json',obligations,'obligation_state')]
    # Validate the complete candidate state before touching existing files.
    errors=validate_state(root,{name:value for name,value,_ in staged})
    require(not errors,'\n'.join(errors))
    for name,value,_ in staged:
        write_json(state_path/name,value)
    require(not validate_state(root),'\n'.join(validate_state(root)))
    return new


def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--root',required=True);p.add_argument('--period',required=True)
    a=p.parse_args();update(a.root,a.period);print('状态已按稳定 ID 更新')


if __name__=='__main__':
    main()
