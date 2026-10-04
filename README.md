[简体中文](README.md) | [English](README.en.md)

# billing-analysis

billing-analysis 是一个分析个人账单的 Agent Skill。它整理来自不同来源的流水，核对消费、收入、退款和资金往来，生成逐笔可查的 Excel 报告。

Agent 根据账单和用户说明判断交易性质，Python 负责计算、审计和保存历史。每笔金额保留原始记录与证据位置，方便核对实际支出和资金去向。

## 能做什么

- 按证据合并重复流水，关联退款、报销和共同费用回款。
- 区分消费、收入、内部转账、本金与费用。
- 保存历史摘要、个人基线、已接受的目标和付款义务。
- 输出 Excel 和结构化结果，保留原始记录与证据位置。

支持 CSV、TSV、XLSX 和读取工具整理的 JSON，字段通过映射指定。每次分析一种币种；人民币默认两位精度，其他币种显式设置精度。报告使用中文。

## 开始使用

### 安装

需要 Python 3.10+，以及支持本地文件和 Python 的 Agent。

将下面这句话发给 Agent，填入仓库链接或本地路径：

```text
请将 billing-analysis 安装为个人 Skill，并配置依赖：<仓库链接或本地路径>
```

手动安装时，将完整目录命名为 `billing-analysis`，放入 Agent 的个人 Skill 目录，再安装依赖：

```bash
python -m pip install -r requirements.txt
```

直接依赖为 `openpyxl`。Codex 个人 Skill 目录可使用 `~/.agents/skills/billing-analysis/`，也可通过 `$skill-installer` 导入。[Codex 安装说明](https://learn.chatgpt.com/docs/build-skills)

### 使用

将自己的账单放在独立工作区，告诉 Agent 账期和范围：

```text
使用 billing-analysis 分析 ../my-bills 中的 2031 年 4 月账单，生成 Excel 报告。
```

在 Codex 中可通过 `$billing-analysis` 调用。

## 仓库结构

```text
billing-analysis/
├── SKILL.md                 # Agent 执行入口
├── agents/openai.yaml       # 名称、简介与默认指令
├── scripts/                 # 预处理、审计、Excel 和状态更新
├── references/              # 财务口径、流程、扩展和字段契约
├── assets/templates/        # 文案、空商户规则和初始状态
├── examples/                # 合成账单与字段映射
├── tests/                   # 合成验收测试
├── requirements.txt         # Python 依赖
├── .gitignore
├── README.md
├── README.en.md
└── LICENSE
```

执行说明见 [SKILL.md](SKILL.md)，详细步骤见 [执行流程](references/workflow.md)。真实账单、处理结果和历史状态保存在独立工作区。

## 测试

```bash
python -m unittest discover -s tests -v
```

## 许可证

Copyright (c) 2026 EggYDX.

仅限自然人的个人非商业用途。允许分析自己的账单、个人学习、本地修改，以及保留许可和署名的无偿非商业分享。

禁止的用途包括：

- **销售与收费产出**：销售、转售、付费下载、收费授权、捆绑收费产品，收费生成或交付报告、工作簿和分析结果。
- **订阅与计费服务**：订阅、会员、按次或按量收费服务。
- **代做与专业服务**：为他人代做账单整理、分析或报告，咨询、培训、课程和商业演示。
- **在线服务**：SaaS、托管应用、在线分析平台和 API 服务。
- **公司与客户项目**：公司、雇主、组织、客户或受委托项目，包括内部使用、交付、集成和评估。
- **其他商业化**：广告、引流、赞助、佣金、商业推广、获客、商业产品研发，以及其他直接或间接营利、业务用途。

完整条款见英文 [LICENSE](LICENSE)，限制同样适用于修改版、相关服务及用于上述活动的产出。第三方依赖遵循各自许可证。
