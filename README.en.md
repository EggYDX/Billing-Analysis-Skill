[简体中文](README.md) | [English](README.en.md)

# billing-analysis

billing-analysis is an Agent Skill for personal bills. It organizes transactions from different sources, checks spending, income, refunds, and transfers, and produces an Excel report you can check line by line.

The Agent classifies transactions using your bills and explanations. Python calculates the amounts, validates the results, and keeps the history. Each amount retains its original records and evidence locations, so you can review spending and trace where the money went.

## What it does

- Merge evidence-backed duplicates and link refunds, reimbursements, and shared-expense repayments.
- Separate spending, income, internal transfers, principal, and fees.
- Keep period summaries, personal baselines, accepted goals, and payment obligations.
- Produce Excel and structured results with original records and evidence locations.

Inputs include CSV, TSV, XLSX, and JSON prepared by a reader, with explicit field mappings. Each analysis uses one currency: CNY defaults to two decimal places; other currencies use an explicit precision. Reports use Chinese.

## Getting started

### Installation

Use Python 3.10+ and an Agent with local file access and Python execution.

Send this sentence to your Agent, filling in the repository URL or local path:

```text
Install billing-analysis as a personal Skill and set up its dependencies: <repository URL or local path>
```

For manual installation, name the complete folder `billing-analysis`, place it in your Agent's personal Skill directory, and install the dependency:

```bash
python -m pip install -r requirements.txt
```

The direct dependency is `openpyxl`. Codex users can use `~/.agents/skills/billing-analysis/` or import through `$skill-installer`. [Codex installation guide](https://learn.chatgpt.com/docs/build-skills)

### Usage

Keep your bills in a separate workspace and tell the Agent the period and scope:

```text
Use billing-analysis to analyze my April 2031 bills in ../my-bills and generate an Excel report.
```

In Codex, invoke the Skill with `$billing-analysis`.

## Repository structure

```text
billing-analysis/
├── SKILL.md                 # Agent entry point
├── agents/openai.yaml       # Display name, description, and default prompt
├── scripts/                 # Preprocessing, validation, Excel, and state updates
├── references/              # Financial rules, workflow, extensions, and contracts
├── assets/templates/        # Report copy, empty merchant rules, and initial state
├── examples/                # Synthetic bill and field mapping
├── tests/                   # Synthetic acceptance tests
├── requirements.txt         # Python dependency
├── .gitignore
├── README.md
├── README.en.md
└── LICENSE
```

See [SKILL.md](SKILL.md) for Agent instructions and the [workflow](references/workflow.md) for the steps. Real bills, processing results, and history stay in a separate workspace.

## Tests

```bash
python -m unittest discover -s tests -v
```

## License

Copyright (c) 2026 EggYDX.

For personal, non-commercial use by natural persons only. Permitted uses include analyzing your own bills, personal learning, local modifications, and sharing copies free of charge for non-commercial purposes with the license and attribution retained.

Prohibited uses include:

- **Sales and paid outputs**: sales, resale, paid downloads, paid licensing, bundling into paid products, and generating or delivering reports, workbooks, or analyses for a fee.
- **Subscriptions and paid services**: subscriptions, memberships, per-task charges, and usage-based charges.
- **Work for others and professional services**: organizing bills, analyzing transactions, or preparing reports for others; consulting, training, courses, and commercial demonstrations.
- **Online services**: SaaS, hosted applications, online analysis platforms, and API services.
- **Company and client projects**: company, employer, organizational, client, or commissioned projects, including internal use, delivery, integration, and evaluation.
- **Other commercial use**: advertising, lead generation, sponsorships, commissions, commercial promotion, customer acquisition, commercial product development, and any other direct or indirect profit-making or business use.

See the English [LICENSE](LICENSE) for the full terms. The restrictions also apply to modified versions, related services, and outputs used for the activities above. Third-party dependencies retain their own licenses.
