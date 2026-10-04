# 来源、规则、币种与渲染扩展

先由 Agent 查看实际文件结构再提供字段映射。支持 CSV、TSV、XLSX 与读取工具整理出的 JSON `{ "records": [...] }`。映射的 format 选择读取器，original_source 是任意非空标识，不是平台枚举。fields 将标准字段映射到实际列名；direction_values 显式映射方向，date_formats 解析非 ISO 日期；account_key 可在列中或映射中明确给出。

`transaction_id_is_stable` 只用于真正交易 ID，不能把导出序号标为 true。无账户、无稳定 ID 的记录以文件哈希和行位置保留；不同导出之间仅提示候选，不强制归并。映射支持一个 source_mapping 对象，或 `{ "files": { "实际文件名": source_mapping } }`，缺少某文件映射时登记待读取。

人民币省略币种/精度参数时采用 CNY 与2位。其他三位币种标识必须显式传精度；不以当前环境推断汇率。amount_multiplier 只作金额单位换算，必须为正；如最小货币单位到主单位，应让外部工具保留原始单位事实，不能用于换汇。超出精度的金额拒绝并保存原因，不能四舍五入后伪装原始值。异币种拒绝行使覆盖降级；正式事件、关联、计划、指标与历史比较均保持币种一致。每种币种使用独立运行工作区，避免义务覆盖语义混淆。

商户规则模板为空；规则是可选用户知识，预处理不会据其自动决定经济事件。Agent 可按 merchant_rules 契约读取并应用有确认依据的 suggested 字段，不让其覆盖原始数据。新增规则留证据；用户本期说明优先。虚构规则示意：match 使用 raw_counterparty=`虚构餐店Alpha`，suggested 可为 category_l1=`餐饮`，不得把示例当真实规则。

PDF、图片、旧 XLS、加密文件或其他格式保留 needs_reading。可用的外部读取器/OCR 将原始结果转换为统一 JSON，再提供字段映射；保留原始文件、整理结果和提取证据。无法读取时披露缺口，禁止假装完整。外部读取器的依赖由适配器单独声明。

新增指标在 schema.metric_definitions 中定义，由 prepare 确定性构造，并在文案中补标签与状态解释。定义变化要更新 definition_version；历史不可强行比较。新增审计投影必须按实体增补 audit_display_fields，不能允许 schema 中任意字段直接显示。

新增 PDF/Word 或其他渲染器仍由 load_report_inputs 取核验输入，核心 render 只接受 report_data 与 report_copy。资源与字体由扩展自己的环境解析；不读取聊天、执行记录或未投影字段。状态写入要求 Excel 通过交付审计。宿主 UI 的发现元数据可在宿主端自行设置，核心包不需要它。
