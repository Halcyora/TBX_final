---
marp: true
theme: default
paginate: true
size: 16:9
backgroundColor: #fff
style: |
  section {
    font-size: 26px;
  }
  h1 {
    color: #1a3d7c;
  }
  h2 {
    color: #1a3d7c;
  }
  table {
    font-size: 20px;
  }
  code {
    font-size: 20px;
  }
---

<!-- _class: lead -->
<!-- _paginate: false -->

# TBX Finance Assistant
### Conversational AI for Grounded Financial Data Queries

Natural language → SQL → Verified answers, in under a second

---

## Agenda

1. Problem Statement
2. Solution Overview
3. Architecture & Query Pipeline
4. Key Features
5. Security: Account Number Encryption
6. Sample Questions & Demo
7. Performance & Accuracy
8. Business Impact & ROI (₹ INR)
9. MVP → Production Roadmap

---

## Problem Statement

- Finance & ops teams spend hours manually querying bank/account/transaction data (SQL, spreadsheets, BI tools)
- Reconciliation and anomaly checks are slow, reactive, and error-prone
- Sensitive data (account numbers, UTRs) often shown in plaintext across tools
- Non-technical stakeholders can't self-serve — every question becomes a ticket to a data/BI analyst
- **Need**: a safe, natural-language interface that gives grounded, explainable answers — not hallucinated ones

---

## Solution Overview

**TBX Finance Assistant** — ask questions in plain English, get SQL-grounded answers instantly.

- 🤖 Natural language understanding of financial questions
- 🔍 Grounded retrieval — SQL generated & executed, never guessed
- 📊 Multi-turn conversations with session context
- 🚨 Hybrid anomaly detection (statistical + ML + business rules)
- 📈 Transparent confidence scoring on every answer
- 🔐 Account numbers encrypted at rest & masked in every response
- 💾 One-click CSV export of any result set

---

## Architecture

```
   Next.js + React Frontend  (Chat, Results, Sessions)
                 │  HTTP/JSON
                 ▼
        FastAPI Backend (Session mgmt, /chat, /export, /decrypt)
                 │
     ┌───────────┼───────────────┐
     ▼           ▼               ▼
 LangGraph    DuckDB          Redis
 Agentic  ──▶ (bank/account/  (Sessions,
 Pipeline     transaction)     cache)
     │
     ▼
 AWS Bedrock — Amazon Nova Micro (1.3B params)
 PS Section 7 compliant · low-latency · cost-efficient
```

---

## Query Pipeline — 8 LangGraph Nodes

**Classify → Clarify (if needed) → SQL Generation → Validate → Execute → Anomaly Detection → Format → Export**

| Stage | Purpose |
|---|---|
| Classify | Intent, entities, confidence scoring |
| Clarify | Ask follow-up if confidence < 60% |
| SQL Generation | Few-shot + chain-of-thought prompting |
| Validation | Static (syntax/safety) + LLM semantic check |
| Execution | Run on DuckDB, capture real results |
| Anomaly Detection | Z-score + Isolation Forest + business rules |
| Formatting | Confidence-scored, grounded natural-language answer |
| Export | On-demand CSV download |

---

## Key Features

- 🔎 **Grounded answers** — every number traces back to an executed SQL query
- 🎯 **Composite confidence score** — Clarity 40% + Completeness 30% + Reliability 30%
- ⚠️ **Hybrid anomaly detection** — statistical, ML (Isolation Forest), and business-rule based
- 💬 **Multi-turn context** — follow-up questions understand prior turns
- 📤 **CSV export** for any query result
- 🔐 **Encryption by default** — no raw account numbers ever leave the database unmasked
- 🖥️ **Modern chat UI** — SQL, confidence, and anomalies shown alongside every answer

---

## Security: Account Number Encryption

- Account numbers encrypted with **Fernet symmetric encryption** on load
- API & UI always show masked values: `****3729069`
- Judges/evaluators can decrypt via a **code-gated** `/decrypt` endpoint
- Full audit trail on every decryption attempt

```
Account Number → Encrypt (Fernet) → Store Encrypted
     → Query & Mask in Response (****3729069)
     → Valid Code? → Reveal Full Number : Deny Access
```

Docs: [docs/ACCOUNT_ENCRYPTION.md](docs/ACCOUNT_ENCRYPTION.md) · [docs/JUDGE_DECRYPTION_GUIDE.md](docs/JUDGE_DECRYPTION_GUIDE.md)

---

## Data Model — 3 Tables

- **`bank`** — bank_code (PK), bank_name
- **`account`** — account_id (PK), entity_id, account_number (sensitive), program_id, available_balance, bank_code (FK)
- **`transaction`** — transaction_id (PK), account_id (FK), transaction_date, transaction_type (credit/debit), description, transaction_amount, transaction_reference_id (plaintext), utr_number (sensitive)

One bank → many accounts → many transactions

---

## Sample Questions It Handles

**Easy**
- "What's the available balance for account 50200013729069?"
- "Show me all accounts at HDFC BANK LIMITED."

**Moderate**
- "Show total spending by bank for each month."
- "Which accounts have negative available balances?"

**Complex**
- "Identify accounts with unusual transaction patterns."
- "Flag any transactions above ₹500,000 as high-value anomalies."

---

## Performance & Accuracy (Measured)

| Metric | Value |
|---|---|
| End-to-end latency | 500–750ms |
| Easy question accuracy | 70%+ |
| Moderate question accuracy | 75%+ |
| Complex question accuracy | 70%+ |
| Grounding score | 80%+ |
| Hallucination rate | <20% |
| SQL execution success rate | >90% |

Model: **Amazon Nova Micro / Qwen 1.5B** — 1.3B params, PS Section 7 compliant (≤20B), low-latency & cost-efficient via AWS Bedrock

---

## Business Impact — Why It Matters

Today, finance/ops teams rely on manual SQL pulls and spreadsheet reconciliation:

- ⏱️ ~10–15 minutes per ad-hoc data question, routed through a BI/data analyst
- 👥 Dedicated analyst bandwidth consumed by repetitive lookup requests
- 🕵️ Anomalies (duplicate UTRs, high-value outliers) often caught late, after settlement
- 🔓 Inconsistent masking of sensitive account data across internal tools

**TBX collapses this to a single natural-language question with a sub-second, grounded, masked-by-default answer.**

---

## ROI Estimate (Illustrative, ₹ INR)

*Assumptions modeled on a mid-size NBFC/fintech ops team — figures are illustrative, not audited.*

| Cost/Benefit Driver | Assumption | Annual Impact |
|---|---|---|
| Analyst time saved | 3 analysts × 40% time freed × ₹9,00,000 CTC | **₹10,80,000** |
| Faster reconciliation | 500K+ txns/month, anomaly caught 5 days earlier | **₹18,00,000** (reduced write-offs) |
| Fraud/error prevention | 0.05% of ₹500 Cr/month flagged early | **₹30,00,000** |
| **Gross Annual Benefit** | | **₹58,80,000** |

---

## ROI Estimate — Cost Side (₹ INR)

| Cost Item | Assumption | Annual Cost |
|---|---|---|
| Build/dev effort (one-time) | 2 engineers × 6 weeks | ₹9,00,000 (amortized Yr 1) |
| AWS Bedrock inference (Nova Micro) | ~2M queries/yr @ low per-token cost | ₹4,50,000 |
| Infra (DuckDB/Redis/hosting) | Small cloud footprint | ₹3,00,000 |
| **Total Annual Cost** | | **₹16,50,000** |

### Net Impact
- **Net Annual Benefit**: ₹58,80,000 − ₹16,50,000 = **₹42,30,000**
- **ROI**: ~256% in Year 1
- **Payback Period**: ~3.4 months

---

## MVP → Production Roadmap

| Aspect | MVP (Current) | Production |
|---|---|---|
| Sessions | In-memory | Redis, persistent |
| Dataset | Small (10 records) | Large (500K+ records) |
| Scale | Single instance | Multi-instance + load balancer |
| CORS | `["*"]` | Restricted allow-list |
| Server | `uvicorn --reload` | Gunicorn + workers |
| Setup time | <5 minutes | 1–2 hours (hardening) |

---

## Production Checklist

- [ ] Redis with persistence (`--appendonly yes`)
- [ ] Large dataset loaded (50 banks, 10K accounts, 500K+ txns)
- [ ] CORS restricted to allowed domains
- [ ] Gunicorn/ASGI production server
- [ ] Secrets in `.env.production`
- [ ] Logging, monitoring, rate limiting
- [ ] Database backups & load testing

---

<!-- _class: lead -->

# Thank You

**TBX Finance Assistant**
Grounded answers. Encrypted by default. Sub-second latency.

📚 Full docs: README.md · docs/ARCHITECTURE.md · PRODUCTION.md
