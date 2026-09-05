# TBX Finance Assistant

**Conversational AI Assistant for Financial Data Queries**

## Overview

A sophisticated finance assistant that understands natural language questions about financial data and returns accurate, grounded answers. Built with LangGraph, Qwen2.5-Coder-1.5B-Instruct, FastAPI, and DuckDB.

### Key Features
- 🤖 **Natural Language Understanding**: Parse complex financial questions
- 🔍 **Grounded Retrieval**: SQL generation from NLP (not hallucination)
- 📊 **Multi-turn Conversations**: Context retention across sessions
- 🚨 **Anomaly Detection**: Hybrid approach (statistical + ML + business rules)
- 📈 **Confidence Signaling**: Transparent about answer certainty
- 💾 **Data Export**: CSV breakdown tables
- ⚡ **Lightweight Models**: Qwen2.5-Coder-1.5B-Instruct, served locally (Ollama) or via vLLM;
  AWS Bedrock (Nova Micro etc.) kept as a switchable fallback. See [INTERNAL_NOTES.md](INTERNAL_NOTES.md) for the full rationale and measured accuracy.

## Architecture

```
┌─────────────────────────────────────────────────────────────┐
│                    React + Next.js Frontend                  │
│                  (Chat Interface + Sessions)                 │
└────────────────────────┬────────────────────────────────────┘
                         │ HTTP/WebSocket
                         ▼
┌─────────────────────────────────────────────────────────────┐
│                      FastAPI Backend                         │
│  ├─ Session Management (Redis)                              │
│  ├─ Chat Endpoints                                           │
│  └─ Export/Download                                          │
└────────────────────────┬────────────────────────────────────┘
                         │
        ┌────────────────┼────────────────┐
        ▼                ▼                ▼
   ┌─────────┐   ┌──────────────┐   ┌────────────┐
   │LangGraph│   │  DuckDB      │   │   Redis    │
   │ Agentic │──▶│ Financial    │   │  Verified- │
   │  Loop   │   │ Database     │   │ query cache│
   └────┬────┘   └──────────────┘   └────────────┘
        │
        │ Nodes:
        ├─ Classify (intent, entities, confidence)
        ├─ Clarify (if needed)
        ├─ Verified-query cache lookup (Redis, optional)
        ├─ SQL Generation (few-shot, single call)
        ├─ SQL Validation (static safety checks)
        ├─ Query Execution
        ├─ SQL Repair (execution-feedback, bounded to 1 retry)
        ├─ Anomaly Detection (hybrid)
        ├─ Response Formatting
        └─ Export
        │
        ▼
   ┌──────────────────────────────────────────┐
   │   Qwen2.5-Coder-1.5B-Instruct             │
   │   - Local (Ollama) now, vLLM on GCP next │
   │   - PS Section 7 compliant (<=20B params)│
   │   - AWS Bedrock kept as fallback         │
   └──────────────────────────────────────────┘
```

See [INTERNAL_NOTES.md](INTERNAL_NOTES.md) for the detailed architecture diagram and rationale.

## Project Structure

```
tbx_finance_assistant/
├── backend/
│   ├── main.py                  # FastAPI app
│   ├── langgraph_flow.py        # LangGraph orchestration
│   ├── database.py              # DuckDB wrapper
│   ├── prompts.py               # LLM prompts + few-shot examples
│   ├── sql_validator.py         # SQL validation
│   ├── tools.py                 # Query execution, anomaly detection, export
│   ├── requirements.txt
│   └── logs/
├── frontend/
│   ├── package.json
│   ├── pages/
│   │   ├── index.tsx            # Main chat interface
│   │   └── sessions.tsx
│   ├── components/
│   │   ├── ChatWindow.tsx
│   │   ├── SessionManager.tsx
│   │   └── ResponseDisplay.tsx
│   └── public/
├── benchmarks/
│   ├── run_benchmark.py         # Benchmark suite
│   ├── results/                 # Benchmark results
│   └── test_questions.json
├── data/
│   ├── transactions.csv         (100K rows, 11.2 MB)
│   ├── vendor_payouts.csv       (100K+ rows, 0.4 MB)
│   ├── reconciliation_status.csv (5.1 MB)
│   ├── chart_of_accounts.csv
│   └── vendor_list.csv
├── .env.example
├── .env                         # Your credentials (not in git)
├── README.md
└── docker-compose.yml           # Local Redis + services

```

## Setup Instructions

### Prerequisites
- Python 3.10+
- Node.js 18+ (for frontend)
- An OpenAI-compatible Qwen2.5-Coder-1.5B-Instruct endpoint (e.g. `ollama pull qwen2.5-coder:1.5b-instruct`, or the deployed vLLM endpoint) — set `LLM_BASE_URL`/`LLM_MODEL_NAME` in `.env`
- Optional: Redis (verified-query cache — the app runs fine without it)
- Optional: AWS Account with Bedrock access (only needed if using the Bedrock fallback model)

### 1. Environment Setup

```bash
# Clone repo
cd TBX_final

# Create Python venv
python -m venv venv
source venv/bin/activate  # On Windows: venv\Scripts\activate

# Copy env template
cp .env.example .env

# Edit .env with your credentials
nano .env
```

### 2. Backend Setup

```bash
# Install dependencies
cd backend
pip install -r requirements.txt

# Start Redis (using Docker)
docker run -d -p 6379:6379 redis:latest

# Run FastAPI
python main.py
# Server available at http://localhost:8000
```

### 3. Frontend Setup

```bash
# Install dependencies
cd ../frontend
npm install

# Start Next.js dev server
npm run dev
# UI available at http://localhost:3000
```

### 4. Database Initialization

DuckDB will auto-load CSV files from `./data/` directory on first run.

```bash
# Verify database
python -c "from database import get_db; db = get_db(); print(db.conn.execute('SELECT COUNT(*) FROM transactions').fetchone())"
```

## Usage

### Chat API

```bash
# Create session
curl -X POST http://localhost:8000/sessions/create

# Send query
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "session-uuid",
    "message": {"content": "What is the total spending across all accounts?"},
    "model": "qwen2.5-coder-1.5b"
  }'
```

### Example Queries

```
Easy:
- "What is the total spending across all accounts?"
- "How many transactions occurred in the last month?"
- "What is the average balance per account?"

Moderate:
- "Show total spending by bank for each month"
- "Which accounts have negative balances?"
- "Compare spending patterns between different banks"

Complex:
- "Identify accounts with unusual transaction patterns"
- "Show accounts with extreme balance swings and their transaction history"
- "Provide a breakdown of credit vs debit transactions by account type"
```

## Model Selection & Benchmarking

### Primary Model: Qwen2.5-Coder-1.5B-Instruct

**Qwen2.5-Coder-1.5B-Instruct** (1.5B parameters, coder-tuned) is the default model.
- **Parameters**: 1.5B — well under the Problem Statement Section 7 cap (<=20B params)
- **Serving**: OpenAI-compatible `/v1/chat/completions` endpoint — local (Ollama) for
  development, the same client points at a vLLM deployment on GCP for production
- **Use Case**: Coder-tuned models are competitive with much larger general models on the
  narrow task this assistant needs (SQL generation over a 3-table schema)
- **Fallback**: AWS Bedrock (Nova Micro, etc.) stays available via the existing model-alias switch

### Running Benchmark Suite

```bash
cd benchmarks
python run_benchmark.py --dataset small   # hand-verified 10-row reference set
python run_benchmark.py --dataset large   # 10K accounts / 500K transactions, scale spot-check

# Generates:
# - benchmark_results_YYYYMMDD_HHMMSS.json
# - report_YYYYMMDD_HHMMSS.txt
```

The suite runs Qwen2.5-Coder-1.5B twice per question — once single-shot ("baseline"), once with
the execution-feedback repair loop enabled ("with-repair") — using execution-verified scoring:
extracts the generated SQL, runs it against real DuckDB data, and compares results to reference
queries. See [INTERNAL_NOTES.md](INTERNAL_NOTES.md) §4 for the measured numbers.

### Model: Qwen2.5-Coder-1.5B-Instruct
- ✅ **Lightweight**: 1.5B params, PS Section 7 compliant (<=20B)
- ✅ **Accurate**: coder-tuned, and paired with a real-error-feedback repair loop (see
  [INTERNAL_NOTES.md](INTERNAL_NOTES.md) §3)
- ✅ **Portable**: same OpenAI-compatible client works local now and against vLLM on GCP later

## Key Design Decisions

### 1. **Prompt-to-SQL vs. Record Chunking**
✅ **Selected**: Prompt-to-SQL (few-shot + chain-of-thought)
- More accurate for financial data
- Prevents hallucination
- Enables grounding verification

### 2. **Lightweight Models**
✅ **Rationale**:
- Qwen2.5-Coder-1.5B-Instruct: 1.5B params, PS Section 7 compliant, coder-tuned for this task's SQL-generation-heavy workload
- Portable serving: same OpenAI-compatible client works against a local Ollama instance or the vLLM deployment on GCP
- AWS Bedrock (Nova Micro, etc.) kept available as a fallback via the model-alias switch

### 3. **Hybrid Anomaly Detection**
✅ **Approach**:
- Statistical: Z-score for outlier detection
- Business Rules: Vendor-specific thresholds
- ML-based: Isolation Forest for pattern detection
- Context: Explain why each anomaly matters

### 4. **Redis Verified-Query Cache**
✅ **Benefits**:
- Replays SQL that has already executed successfully for an equivalent prior question, skipping LLM generation entirely
- Strictly more deterministic than regenerating SQL from scratch each time
- Always re-executed against live data, never trusted blindly
- Optional: fails open (cache silently skipped) if Redis isn't reachable

(Session/conversation history itself is stored in-process, persisted to a local JSON file — see `backend/main.py`'s `SessionManager` — not Redis.)

### 5. **DuckDB for Analytics**
✅ **Advantages**:
- Embedded (no server needed)
- Optimized for OLAP queries
- Fast aggregations (Group By, window functions)
- <100ms queries on 100K rows

## Grounding & Accuracy

### Grounding Checks
✅ Verify all numbers from query results  
✅ Check SQL against database schema  
✅ Flag if data missing/null  
✅ Validate date range constraints  
✅ Prevent fabricated figures  

### Confidence Scoring (Composite)
```python
confidence = (
    query_clarity * 0.4 +       # How unambiguous was the question?
    data_completeness * 0.3 +   # How much data was available?
    result_reliability * 0.3    # How confident in results?
)
```

Levels:
- 🟢 High (>80%): Answer with confidence
- 🟡 Medium (60-80%): Answer with caveats
- 🔴 Low (<60%): Ask clarifying questions

## Bonus Features

### ✅ CSV Export
- Download query breakdown as CSV
- All columns from result set
- Max 50K rows per export

### ✅ Confidence Signaling
- Composite score from: clarity, completeness, reliability
- Temperature-based adjustment
- Uncertainty quantification

### ✅ Anomaly Callouts
- Hybrid detection (statistical + business rules + ML)
- Flagged in response with explanation
- Severity levels (high/medium)

## Performance Metrics

Measured via `benchmarks/run_benchmark.py` against the live Qwen2.5-Coder-1.5B-Instruct endpoint
(execution-verified: SQL actually run against DuckDB, compared to reference results). Full
numbers and an honest read of what's a real effect vs run-to-run variance: see
[INTERNAL_NOTES.md](INTERNAL_NOTES.md) §4.

### Accuracy (small dataset, 10 hand-verified rows/table)
- Easy questions: 100%
- Moderate questions: 80%
- Complex questions: 46.7%
- Overall execution correctness: 75.6%
- SQL execution rate: 100%

### Grounding
- Every answer comes from executing SQL against the real database, never from the model stating a number directly
- Hallucination rate (grounding heuristic): ~20%
- SQL execution rate (ran without error): 93-100% depending on dataset size

## Deployment

### Local Development
```bash
# Already set up above
python main.py  # Backend
npm run dev     # Frontend
```

### Docker (Future)
```bash
docker-compose up
```

## Troubleshooting

### Redis Connection Error
```bash
# Start Redis
docker run -d -p 6379:6379 redis:latest
```

### DuckDB File Locked
```bash
# Close other connections and restart
rm ./data/finance.db
```

### Model Not Found
```bash
# Verify AWS credentials and model availability
aws bedrock list-foundation-models --region us-east-1
```

## Testing

### Unit Tests
```bash
pytest backend/tests/ -v
```

### Integration Tests
```bash
pytest benchmarks/run_benchmark.py
```

## API Documentation

Full API docs available at:
- Swagger UI: `http://localhost:8000/docs`
- ReDoc: `http://localhost:8000/redoc`

## Model Efficiency Justification

**Why Qwen2.5-Coder-1.5B-Instruct?**
- **Lightweight**: 1.5B parameters (PS Section 7 constraint: <=20B params) — a small fraction of the allowed budget
- **Coder-tuned**: this task is narrow (SQL generation + explaining a computed result), exactly where a small coder-tuned model is competitive with much larger general models
- **Portable serving**: an OpenAI-compatible client talks to either a local Ollama instance or the production vLLM deployment on GCP — no code change to switch
- **Paired with a repair loop, not raw scale**: accuracy comes from execution-feedback self-repair, real column types, and a verified-query cache (see [INTERNAL_NOTES.md](INTERNAL_NOTES.md) §3), not from a bigger model

**Why keep AWS Bedrock as a fallback?**
- Same `model_alias` switch already in the code, no reason to delete it
- Useful if the vLLM deployment is ever unavailable during the demo

## License & Attribution

Dataset: Synthetically generated for TBX Hackathon
Models: Qwen2.5-Coder-1.5B-Instruct (primary; local/vLLM), AWS Bedrock (fallback)
Framework: LangGraph (LangChain)

## Support

For issues or questions:
1. Check `.env.example` for missing config
2. Review logs in `./logs/`
3. Run benchmark to validate setup

---

**Built for TBX—BVP Tech Catalyst Hackathon**  
**Challenge**: Build a Finance Assistant That Actually Understands You
