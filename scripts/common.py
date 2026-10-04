"""Package resources and deterministic, portable primitives (Python 3.10+)."""
from __future__ import annotations

import hashlib
import json
import math
import re
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path, PureWindowsPath

PACKAGE = Path(__file__).resolve().parent.parent
SCHEMA = json.loads((PACKAGE / 'references/billing_schema.json').read_text(encoding='utf-8'))
VERSION = SCHEMA['schema_version']


def read_json(path, default=None):
    path = Path(path)
    return json.loads(path.read_text(encoding='utf-8-sig')) if path.exists() else default


def write_json(path, value):
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    content = json.dumps(value, ensure_ascii=False, indent=2, allow_nan=False) + '\n'
    if path.exists() and path.read_text(encoding='utf-8') == content:
        return
    temp = path.with_name(path.name + '.tmp')
    temp.write_text(content, encoding='utf-8')
    temp.replace(path)


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=False, sort_keys=True,
                                    separators=(',', ':'), allow_nan=False).encode()).hexdigest()


def sha(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def stable_id(prefix, *parts):
    return prefix + '-' + digest(parts)[:24]


def number(value):
    return isinstance(value, (int, float)) and not isinstance(value, bool) and math.isfinite(value)


def money(value, precision=2):
    if isinstance(value, bool):
        raise ValueError('金额不能是布尔值')
    try:
        amount = Decimal(str(value))
    except (InvalidOperation, ValueError):
        raise ValueError('金额无法解析') from None
    if not amount.is_finite() or amount < 0 or amount != amount.quantize(Decimal(1).scaleb(-precision)):
        raise ValueError('金额必须非负、有限且符合显式精度，不能静默截断')
    return amount


def total(values):
    return float(sum((Decimal(str(v)) for v in values), Decimal(0)))


def period_key(value):
    if not isinstance(value, str) or not re.fullmatch(r'\d{4}\.(?:[1-9]|1[0-2])', value):
        raise ValueError('账期须为 YYYY.M')
    year, month = map(int, value.split('.'))
    date(year, month, 1)
    return year, month


def period_of(value):
    dt = datetime.fromisoformat(value)
    return f'{dt.year}.{dt.month}'


def period_dir(root, period):
    period_key(period)
    return Path(root).resolve() / period


def relative_file(root, name):
    """Reject absolute, traversal and directory-link escapes on every host."""
    if not isinstance(name, str) or not name or '\\' in name or ':' in name:
        raise ValueError('证据路径必须使用工作区内的相对 POSIX 路径')
    path = Path(name)
    if path.is_absolute() or PureWindowsPath(name).is_absolute() or '..' in path.parts:
        raise ValueError('证据路径不能是绝对路径或包含上级目录')
    root = Path(root).resolve()
    resolved = (root / path).resolve()
    if not resolved.is_relative_to(root):
        raise ValueError('证据路径越出工作区')
    return resolved


def ref(root, path, freeze=True, **ids):
    path = Path(path).resolve()
    root=Path(root).resolve()
    # Results and confirmations can be revised. Preserve their exact proven bytes
    # before returning a durable evidence reference; raw files stay registered originals.
    relative=path.relative_to(root)
    if freeze and path.suffix.lower()=='.json' and any(part in ('处理结果','执行记录') for part in relative.parts) and '审计快照' not in relative.parts:
        period=relative.parts[0]
        period_key(period)
        target=root/period/'执行记录'/'审计快照'/(sha(path)+'-'+path.name)
        target.parent.mkdir(parents=True,exist_ok=True)
        if not target.exists():
            target.write_bytes(path.read_bytes())
        elif sha(target)!=sha(path):
            raise ValueError('不可变审计快照被修改，须恢复原证据')
        path=target
    return dict(file=path.relative_to(Path(root).resolve()).as_posix(), sha256=sha(path), **ids)


def resolve(value, path):
    if not isinstance(path, str) or not path:
        raise ValueError('空绑定')
    for key in path.split('.'):
        value = value[int(key)] if isinstance(value, list) else value[key]
    return value


def check_contract(value, name):
    """The package's custom schema is the only field/type/enum source."""
    errors = []

    def check(item, spec, label):
        if spec.endswith('|null'):
            if item is None:
                return
            spec = spec[:-5]
        if spec.endswith('[]'):
            if not isinstance(item, list):
                errors.append(label + ': 应为数组')
            else:
                for i, child in enumerate(item):
                    check(child, spec[:-2], f'{label}[{i}]')
        elif spec.startswith('map:'):
            if not isinstance(item, dict) or not all(isinstance(k, str) and k for k in item):
                errors.append(label + ': 应为对象映射')
            else:
                for key, child in item.items():
                    check(child, spec[4:], label + '.' + key)
        elif spec in SCHEMA['contracts']:
            contract = SCHEMA['contracts'][spec]
            if not isinstance(item, dict):
                errors.append(label + ': 应为对象')
                return
            fields = contract['fields']
            required = set(fields) - set(contract.get('optional', []))
            if required - item.keys():
                errors.append(label + ': 缺字段 ' + ','.join(sorted(required - item.keys())))
            if item.keys() - fields.keys():
                errors.append(label + ': 未定义字段 ' + ','.join(sorted(item.keys() - fields.keys())))
            for key in item.keys() & fields.keys():
                check(item[key], fields[key], label + '.' + key)
        elif spec in SCHEMA['enums']:
            if item not in SCHEMA['enums'][spec]:
                errors.append(label + ': 非法枚举')
        else:
            valid = True
            if spec == 'string':
                valid = isinstance(item, str) and bool(item.strip())
            elif spec == 'text':
                valid = isinstance(item, str)
            elif spec == 'number':
                valid = number(item)
            elif spec == 'integer':
                valid = isinstance(item, int) and not isinstance(item, bool) and item >= 0
            elif spec == 'boolean':
                valid = isinstance(item, bool)
            elif spec == 'scalar':
                valid = item is None or isinstance(item, (str, bool)) or number(item)
            elif spec in ('date', 'datetime', 'period', 'sha256', 'currency'):
                try:
                    if spec == 'date':
                        valid = isinstance(item, str) and len(item) == 10
                        date.fromisoformat(item)
                    elif spec == 'datetime':
                        valid = isinstance(item, str)
                        datetime.fromisoformat(item)
                    elif spec == 'period':
                        period_key(item)
                    elif spec == 'sha256':
                        valid = isinstance(item, str) and re.fullmatch('[0-9a-f]{64}', item) is not None
                    else:
                        valid = isinstance(item, str) and re.fullmatch('[A-Z]{3}', item) is not None
                except (ValueError, TypeError):
                    valid = False
            elif spec == 'json':
                try:
                    json.dumps(item, allow_nan=False)
                except (ValueError, TypeError):
                    valid = False
            else:
                raise ValueError('包内 schema 含未知类型: ' + spec)
            if not valid:
                errors.append(label + ': 非法 ' + spec)

    check(value, name, name)
    if errors:
        raise ValueError('\n'.join(errors))


def envelope(period_id, **fields):
    return dict(schema_version=VERSION, period_id=period_id, **fields)
