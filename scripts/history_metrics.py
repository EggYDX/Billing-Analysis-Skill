"""Pure comparable-history and unpaid-obligation calculations; no state writes."""
from calendar import monthrange
from datetime import date
from decimal import Decimal
from common import number, period_key


def percentile(values, proportion):
    values=sorted(Decimal(str(v)) for v in values)
    position=Decimal(len(values)-1)*Decimal(str(proportion))
    low=int(position)
    return values[low]+(values[min(low+1,len(values)-1)]-values[low])*(position-low)


def compare_history(current, periods, metric_key, coverage_key='expense'):
    metric=current.get('metrics',{}).get(metric_key,{})
    result=dict(status='insufficient_history',reference_period_ids=[],sample_count=0,
                definition_version=current['period']['definition_version'],metric_key=metric_key,currency=current['currency'],
                reference_value=None,reference_method=None,delta=None,delta_ratio=None,normal_range=None)
    def eligible(period):
        m=period.get('metrics',{}).get(metric_key,{})
        scope=period.get('period',{})
        return (period.get('data_status')=='confirmed' and period.get('currency')==current['currency']
                and period.get('amount_precision')==current['amount_precision']
                and scope.get('context_group')==current['period']['context_group']
                and scope.get('definition_version')==current['period']['definition_version']
                and period.get('completeness',{}).get(coverage_key)=='complete'
                and m.get('status')=='confirmed' and number(m.get('value'))
                and m.get('unit')==metric.get('unit') and m.get('currency')==metric.get('currency')
                and bool(m.get('definition')) and m.get('definition')==metric.get('definition')
                and isinstance(scope.get('observed_days'),int) and scope['observed_days']>0
                and (m['unit'] in ('currency_per_day','currency_per_30_days','ratio') or scope.get('is_full_period') is True))
    refs=[p for pid,p in periods.items() if period_key(pid)<period_key(current['period_id']) and eligible(p)]
    refs=sorted(refs,key=lambda p:period_key(p['period_id']))[-6:]
    result.update(reference_period_ids=[p['period_id'] for p in refs],sample_count=len(refs))
    if len(refs)<2:
        return result
    if not eligible(current):
        result['status']='insufficient_data'
        return result
    values=[p['metrics'][metric_key]['value'] for p in refs]
    precision=Decimal('0.000001') if metric['unit']=='ratio' else Decimal(1).scaleb(-current['amount_precision']-4)
    reference=percentile(values,.5).quantize(precision)
    delta=Decimal(str(metric['value']))-reference
    result.update(status='confirmed',reference_method='median',reference_value=float(reference),delta=float(delta),
                  delta_ratio=float((delta/reference).quantize(Decimal('0.000001'))) if reference else None)
    if len(refs)==6:
        result['normal_range']=dict(low=float(percentile(values,.25).quantize(precision)),
                                    high=float(percentile(values,.75).quantize(precision)),method='linear_P25_P75')
    return result


def committed_cashflow(state, as_of, currency='CNY'):
    start=date.fromisoformat(as_of)
    known=state.get('data_status')=='confirmed' and state.get('currency')==currency
    refs=list(state.get('evidence_refs',[]))
    pending=[]
    for o in state.get('obligations',[]):
        if o.get('currency')!=currency:
            known=False
            continue
        refs.extend(o['evidence_refs'])
        if o['obligation_status'] in ('settled','closed','cancelled'):
            continue
        if o['data_status']!='confirmed' or o['obligation_status']!='active' or o['payment_schedule'] is None:
            known=False
            continue
        for item in o['payment_schedule']:
            if item['payment_status'] in ('paid','cancelled'):
                continue
            if item['currency']!=currency or item['status']!='confirmed' or item['payment_status']!='scheduled' or not number(item['amount']) or not item['due_date']:
                known=False
                continue
            pending.append((date.fromisoformat(item['due_date']),Decimal(str(item['amount']))))
            refs.extend(item['evidence_refs'])
    result={}
    for months in (1,3,6):
        year, month=divmod(start.year*12+start.month-1+months,12)
        month+=1
        end=date(year,month,min(start.day,monthrange(year,month)[1]))
        key=f"committed_cashflow_{months}_month{'s' if months>1 else ''}"
        result[key]=dict(value=float(sum((v for due,v in pending if start<due<=end),Decimal(0))) if known else None,
                         status='confirmed' if known else 'unknown',confidence='高' if known else None,
                         unit='currency',currency=currency,evidence_refs=refs,
                         definition=f'已确认未付计划；{as_of}之后至{end.isoformat()}（含）')
    return result
