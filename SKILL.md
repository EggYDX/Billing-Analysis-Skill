---
name: billing-analysis
license: 个人非商业用途；完整条款见 LICENSE
description: 将账单证据整理为可审计经济事件，集中确认关键事实，交付结构化分析和基础 Excel，并维护同口径历史、目标与义务。
---

# 账单分析

将财务事实、个人基线、决策和长期反馈连接成可追溯闭环。Agent 判断真实经济性质；脚本负责确定性运算、证据核验和展示隔离。用户当前说明优先于默认规则。

先读 [financial-rules.md](references/financial-rules.md) 的财务口径和判断约束、[workflow.md](references/workflow.md) 的执行边界，以及唯一结构来源 [billing_schema.json](references/billing_schema.json)。来源映射、规则、币种或渲染扩展时再读 [extensions.md](references/extensions.md)。

Skill 目录与账单工作区分开。使用 Python 3.10+，依赖见 `requirements.txt`。包内资源按脚本位置解析，所有用户数据通过 `--root` 指定。以下命令中的 `<包>` 与 `<工作区>` 由当前环境解析，不要求特定宿主、安装位置或当前目录。

1. 盘点上传文件与工作区原始证据，根据内容和用户说明确定账期、来源、账户、单一币种及金额精度。Agent 检查实际列结构，提供字段映射。不能读取的证据登记为待处理；不得忽略后宣布完整。
2. 执行 `python <包>/scripts/preprocess.py --root <工作区> --period YYYY.M --files <账单...> --mapping <映射.json>`。人民币默认两位；其他币种同时传 `--currency XXX --amount-precision N`。无历史、无商户规则也可启动。预处理仅给保守候选。
3. 核查重叠、退款、共同费用、本金与费用、跨期回款及关键覆盖缺口。先解决能由证据解决的事项，再集中确认影响金额、统计范围或结论的未知项；允许可靠降级，不重复询问已明确事实。
4. 将确认写入 `执行记录/确认记录.json`，构建 `处理结果/经济事件.json`、`关联记录.json` 与 `analysis_context.json`。使用稳定 ID；原始金额、记录和坐标持续保留。当期上下文仅承接本期结构化事实，不作为长期配置或覆盖规则。
5. 先执行 `validate_report.py --root <工作区> --period YYYY.M --facts`，再执行 `prepare_report.py` 的同名参数。审核生成的 `report_copy.draft.json`，将正式文案另存为 `report_copy.json`。所有标题、表头、注释、状态解释来自文案；动态文字绑定真实标量字段和输入摘要。数字与审计投影来自 `report_data`。
6. 执行 `validate_report.py` 后，通过 `render_workbook.py` 交付基础 Excel。正式渲染入口只能使用 `load_report_inputs(root, period)`；渲染函数只接收通过核验的两个对象。检查核心金额、读回一致性和视觉可读性，`null` 保持空值并显示状态，不能显示为 0。
7. 交付审计通过后执行 `update_state.py`，按稳定 ID 更新摘要、目标和义务；再执行 `validate_report.py --root <工作区> --state`。保留修订与结束生命周期，不自动接受建议目标。报告边界与成品位置，仅提出有证据、确有行动价值的调整。

PDF、Word、OCR、旧格式读取器与宿主 UI 是可选扩展，不是核心依赖。测试仅使用从零合成证据：`python -m unittest discover -s <包>/tests -v`。
