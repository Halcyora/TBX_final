# TBX Finance Assistant — Complete Documentation Index

Welcome! This is your central hub for all TBX Finance Assistant documentation. Start here to find what you need.

## 📋 Quick Navigation

### Getting Started
- [README.md](README.md) — **Start here** for overview, quick setup, and architecture
- [PRODUCTION.md](PRODUCTION.md) — MVP features and production deployment guide
- [SAMPLE_QUESTIONS.md](SAMPLE_QUESTIONS.md) — Example queries to test the system

### Technical Reference
- [TBX - Database Schema.md](TBX%20-%20Database%20Schema.md) — Complete database schema, tables, and sample data
- [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) — System design, query pipeline, and design decisions
- [docs/ACCOUNT_ENCRYPTION.md](docs/ACCOUNT_ENCRYPTION.md) — Encryption setup and security details
- [docs/JUDGE_DECRYPTION_GUIDE.md](docs/JUDGE_DECRYPTION_GUIDE.md) — How to decrypt masked account numbers

### Frontend
- [frontend/README.md](frontend/README.md) — React/Next.js setup and component overview

---

## 📖 By Task

### I want to...

**...set up and run the project**  
→ [README.md](README.md#quick-start) (Backend & Frontend setup)  
→ [PRODUCTION.md](PRODUCTION.md#running-mvp-locally) (MVP local run)

**...understand the system architecture**  
→ [docs/ARCHITECTURE.md](docs/ARCHITECTURE.md) (Full system design)  
→ [README.md](README.md#architecture) (High-level overview)

**...test the API**  
→ [SAMPLE_QUESTIONS.md](SAMPLE_QUESTIONS.md) (Example queries)  
→ [README.md](README.md#api-endpoints) (Endpoint reference)

**...set up encryption**  
→ [docs/ACCOUNT_ENCRYPTION.md](docs/ACCOUNT_ENCRYPTION.md) (Complete setup)  
→ [PRODUCTION.md](PRODUCTION.md#mvc-database) (Database configuration)

**...decrypt account numbers (judge evaluation)**  
→ [docs/JUDGE_DECRYPTION_GUIDE.md](docs/JUDGE_DECRYPTION_GUIDE.md)

**...understand the database**  
→ [TBX - Database Schema.md](TBX%20-%20Database%20Schema.md) (Full schema + DDL)

**...deploy to production**  
→ [PRODUCTION.md](PRODUCTION.md#production-deployment) (Production setup)

**...work on the frontend**  
→ [frontend/README.md](frontend/README.md) (Frontend guide)

---

## 🏗️ System Stack

| Component | Technology | Purpose |
|-----------|-----------|---------|
| **Frontend** | Next.js + React + TypeScript | Chat interface, results visualization |
| **Backend** | FastAPI + LangGraph | Query orchestration, 8-node pipeline |
| **Database** | DuckDB | 3 tables (bank, account, transaction) |
| **LLM** | AWS Bedrock (Qwen 1.5B) | SQL generation, intent classification |
| **Sessions** | In-memory (MVP) / Redis (Prod) | Conversation history |
| **Security** | Fernet encryption | Account number protection |

---

## 🚀 Quick Start (30 seconds)

```bash
# 1. Clone and setup
cd TBX_final
cp .env.example .env  # Add AWS credentials

# 2. Backend
cd backend && pip install -r requirements.txt
python main.py  # Runs on http://localhost:8000

# 3. Frontend (new terminal)
cd ../frontend && npm install
npm run dev  # Runs on http://localhost:3000

# 4. Visit http://localhost:3000 and start chatting!
```

---

## 📊 Project Structure

```
TBX_final/
├── README.md                      ← Start here
├── PRODUCTION.md                  ← MVP & Production guide
├── SAMPLE_QUESTIONS.md            ← Test queries
├── TBX - Database Schema.md       ← Database reference
├── DOCS.md                        ← You are here
├── .env, .env.example             ← Configuration
│
├── backend/                       ← FastAPI + LangGraph
│   ├── main.py                    ├─ Chat endpoints
│   ├── langgraph_flow.py          ├─ 8-node query pipeline
│   ├── database.py                ├─ DuckDB wrapper
│   ├── encryption.py              ├─ Account encryption
│   ├── sql_validator.py           ├─ SQL validation
│   ├── prompts.py                 ├─ LLM prompts
│   ├── tools.py                   ├─ Query execution & anomalies
│   └── requirements.txt
│
├── frontend/                      ← Next.js + React
│   ├── README.md                  ├─ Frontend setup
│   ├── pages/index.tsx            ├─ Main chat page
│   ├── components/                ├─ React components
│   │   ├── ChatInterface.tsx
│   │   ├── ResultsPanel.tsx
│   │   ├── SessionManager.tsx
│   │   ├── Sidebar.tsx
│   │   └── StepsList.tsx
│   ├── lib/types.ts               ├─ TypeScript types
│   ├── styles/                    ├─ CSS modules
│   └── package.json
│
├── data/                          ← Database files
│   ├── small/                     ├─ Test data
│   │   ├── account.csv
│   │   ├── bank.csv
│   │   └── transaction.csv
│   ├── large/                     ├─ Production data
│   └── sessions_store.json        ├─ Session storage
│
├── docs/                          ← Technical docs
│   ├── ARCHITECTURE.md            ├─ System design
│   ├── ACCOUNT_ENCRYPTION.md      ├─ Encryption guide
│   └── JUDGE_DECRYPTION_GUIDE.md  ├─ Judge decryption
│
└── exports/                       ← CSV exports

```

---

## 🔗 Key Links

| Feature | Doc | File |
|---------|-----|------|
| **API Reference** | [README.md](README.md#api-endpoints) | `backend/main.py` |
| **LangGraph Pipeline** | [ARCHITECTURE.md](docs/ARCHITECTURE.md#query-pipeline-8-nodes) | `backend/langgraph_flow.py` |
| **Database Schema** | [TBX - Database Schema.md](TBX%20-%20Database%20Schema.md) | `data/small/*.csv` |
| **Encryption** | [ACCOUNT_ENCRYPTION.md](docs/ACCOUNT_ENCRYPTION.md) | `backend/encryption.py` |
| **Frontend Setup** | [frontend/README.md](frontend/README.md) | `frontend/` |

---

## ✅ Status

- ✅ MVP Complete (in-memory sessions, small dataset)
- ✅ Core pipeline (8-node LangGraph)
- ✅ Encryption & security
- ✅ API fully documented
- ✅ Frontend responsive & type-safe
- 🟡 Production deployment (use PRODUCTION.md)

---

## 💡 Common Questions

**Q: How do I test the system?**  
A: See [SAMPLE_QUESTIONS.md](SAMPLE_QUESTIONS.md) for example queries.

**Q: How do I decrypt account numbers?**  
A: See [docs/JUDGE_DECRYPTION_GUIDE.md](docs/JUDGE_DECRYPTION_GUIDE.md) for the judge flow.

**Q: How does encryption work?**  
A: See [docs/ACCOUNT_ENCRYPTION.md](docs/ACCOUNT_ENCRYPTION.md) for full details.

**Q: What's in production vs MVP?**  
A: See [PRODUCTION.md](PRODUCTION.md) for differences.

**Q: How do I add new data?**  
A: Load CSV files into `data/small/` or `data/large/` — schema in [TBX - Database Schema.md](TBX%20-%20Database%20Schema.md).

---

Last updated: 2026-09-05
