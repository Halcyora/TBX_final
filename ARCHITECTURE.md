# TBX Finance Assistant - Complete Implementation Guide

## Overview
This document provides a comprehensive guide to the TBX Finance Assistant implementation, including architecture decisions, component descriptions, and deployment instructions.

## Problem Statement Alignment

### ✅ Requirements Met

**Must Have:**
- ✅ Natural language query handling (Classification → SQL Generation)
- ✅ Grounded retrieval (Prompt-to-SQL, not hallucination)
- ✅ Accurate computation (SQL execution before LLM formatting)
- ✅ Verifiable answers (Results table + Grounding Info)
- ✅ Hallucination guardrails (Confidence scoring, data validation)
- ✅ Lightweight model constraint (Qwen2.5-Coder-1.5B-Instruct: 1.5B params, PS Section 7 compliant; see [INTERNAL_NOTES.md](INTERNAL_NOTES.md))
- ✅ Multi-turn conversation (session context compression; see [INTERNAL_NOTES.md](INTERNAL_NOTES.md) for the current session-storage mechanism)
- ✅ Explainability (Show SQL, data pulled, grounding info)

**Good to Have:**
- ✅ CSV export (implemented in tools.py)

**Bonus:**
- ✅ Confidence signalling (Composite score: clarity + completeness + reliability)
- ✅ Model choice documentation (Benchmarking suite with detailed metrics)
- ✅ Anomaly callouts (Hybrid: Statistical + Business Rules + ML)

---

## Architecture Components

### 1. Data Layer

#### Files
- `data/bank.csv` (50 banks, TBX schema primary data)
- `data/account.csv` (10,000 accounts with balances)
- `data/transaction.csv` (500K+ transactions with edge cases)

#### Database: DuckDB (`backend/database.py`)
- **Why DuckDB?** Embedded, analytical optimizations, fast aggregations on TBX schema
- Auto-loads CSVs from `data/small/` or `data/large/` on initialization
- Indexes on bank_code, account_id, transaction_date, transaction_id
- Provides schema info for SQL validation (bank, account, transaction tables only)
- Supports complex queries (GROUP BY, window functions, CTEs, JOINS)

---

### 2. LLM Integration Layer

#### Qwen2.5-Coder-1.5B-Instruct (1.5B params, PS Section 7 compliant)
- **Qwen2.5-Coder-1.5B-Instruct**: 1.5B parameters, coder-tuned, served via an OpenAI-compatible
  `/v1/chat/completions` endpoint (local Ollama for dev, vLLM on GCP for production - same client)
- **Fallback**: AWS Bedrock (Nova Micro, Llama 3.1-8B, Mistral-7B, Llama Scout-17B - all <=20B params) via the same `model_alias` switch

#### Prompt Engineering (`backend/prompts.py`)
- **Few-shot Examples**: 6 diverse SQL examples in system prompt
- **Classification Prompt**: Parse intent, entities, filters, confidence
- **Repair Prompt**: execution-feedback self-repair - the real DB error is fed back for one bounded regeneration attempt (see [INTERNAL_NOTES.md](INTERNAL_NOTES.md) §3)
- **Response Template**: Format answer with confidence + grounding

---

### 3. Core Processing Pipeline (LangGraph)

#### `backend/langgraph_flow.py` - Agentic Loop

**Node: Classify**
- Input: User question
- Process: Use Claude (placeholder) to parse intent, entities, filters, confidence
- Output: Parsed query structure + confidence score (0-1)
- Routes: If confidence < 0.6 → Clarify, else → SQL Generation

**Node: Clarification (Conditional)**
- Input: Low-confidence query
- Process: Generate clarification questions
- Output: Error message with questions OR proceed if user confirms

**Node: SQL Generation**
- Input: Query + conversation context
- Process: 
  1. Chain-of-thought reasoning
  2. Few-shot SQL generation
  3. Clean markdown/SQL formatting
- Output: SQL query string

**Node: SQL Validation**
- Input: Generated SQL
- Process:
  1. Static checks (syntax, dangerous ops, schema)
  2. LLM semantic validation + correction
- Output: Validated SQL OR error messages

**Node: Query Execution**
- Input: Validated SQL
- Process: Execute on DuckDB, return results
- Output: List of result dictionaries OR error

**Node: Anomaly Detection**
- Input: Query results
- Process: Hybrid detection (Z-score + Business Rules + Isolation Forest)
- Output: List of anomalies with severity & explanation

**Node: Response Formatting**
- Input: Query results + anomalies + grounding info
- Process:
  1. Format results table
  2. Calculate composite confidence
  3. Generate answer text
  4. Store grounding info
- Output: Final answer + confidence + grounding

**Node: Export**
- Input: Query results
- Process: Generate CSV file
- Output: Filename for download

---

### 4. Validation & Safety (`backend/sql_validator.py`)

#### SQLValidator
- Syntax validation (using sqlparse)
- Dangerous operation detection (DROP, DELETE, UPDATE, etc.)
- Table reference verification (only allowed tables)
- Basic column checks

#### QueryResultValidator
- Result integrity checks
- Data quality issue detection (null rates, negative amounts)
- Anomaly flagging

---

### 5. Tools & Utilities (`backend/tools.py`)

#### QueryExecutor
- Executes validated SQL on DuckDB
- Error handling & logging

#### AnomalyDetector
- **Z-score**: Statistical outliers (>2σ)
- **Multiplier**: Vendor-specific (>3x average)
- **Isolation Forest**: ML-based detection (10% contamination)
- Deduplication: Removes duplicates across methods

#### DataExporter
- CSV export (pandas to_csv)
- Pretty table formatting (currency format, truncation)

#### ContextManager
- Summarizes conversation turns (for token efficiency)
- Compresses context (last N full + summaries of older)

---

### 6. FastAPI Backend (`backend/main.py`)

#### Endpoints

**POST `/sessions/create`**
- Creates Redis session
- Returns session_id (UUID)

**GET `/sessions/{session_id}`**
- Returns session info (created_at, message count, last_message_at)

**POST `/chat`**
- Main endpoint
- Input: `ChatRequest(session_id, message, model)`
- Process: Run through LangGraph
- Output: `ChatResponse(message, confidence, grounding_info, anomalies, export)`

**POST `/export`**
- Downloads CSV of results

**GET `/schema`**
- Returns database schema (for client validation)

**GET `/health`**
- Health check (Redis, DB status)

#### Middleware
- CORS enabled (for React frontend)
- Request/response logging

#### Session Management
- Redis-backed sessions
- Auto-expiration (60 min default)
- Message history storage

---

### 7. Benchmarking Suite (`benchmarks/run_benchmark.py`)

#### Test Questions
- **Easy (5)**: Simple filters, single tables
- **Moderate (5)**: GROUP BY, joins, aggregations
- **Complex (5)**: Window functions, CTEs, multi-table analysis

#### Metrics
- **Accuracy**: % keywords from expected response present
- **Grounding**: SQL presence + data reference check
- **Latency**: P50, P95, P99 (ms)
- **Hallucination Rate**: 1 - grounding score

#### Output
- JSON results with all metrics
- Comparison by complexity
- Model rankings by metric
- Human-readable report

---

### 8. Frontend Scaffold (`frontend/`)

#### Technology Stack
- **Next.js**: React framework
- **TypeScript**: Type safety
- **Tailwind CSS**: Styling
- **Fetch API**: HTTP requests

#### Key Pages
- **Chat Interface**: Session-based chat with context
- **Session Manager**: View/switch between sessions
- **Response Display**: Answer + grounding info + export button

#### Components (to implement)
- `ChatWindow`: Message display + input
- `ResponseDisplay`: Answer + confidence + anomalies
- `SessionSelector`: Create/switch sessions
- `ExportButton`: Download CSV

---

## Key Design Decisions

### 1. **Prompt-to-SQL vs. Record Chunking**
```
Selected: Prompt-to-SQL (Few-shot + Chain-of-Thought)

Rationale:
✓ More accurate for financial data
✓ Prevents hallucination (grounded in SQL execution)
✓ Schema validation before execution
✓ No information loss from chunking
✓ Explainable (can show SQL to user)

Downside: Requires good LLM SQL generation
Mitigation: Few-shot examples + validation
```

### 2. **Lightweight Models (Qwen2.5-Coder-1.5B-Instruct primary)**
```
Selected: Qwen2.5-Coder-1.5B-Instruct (1.5B params, OpenAI-compatible endpoint)

Design Rationale:
✓ Fully compliant with Problem Statement Section 7 (<=20B params constraint)
✓ Coder-tuned: this task is narrow (SQL generation + result explanation), where a small
  coder-tuned model is competitive with much larger general models
✓ Portable serving: local Ollama for dev, vLLM on GCP for production - same client code
✓ Paired with execution-feedback repair + real column types + a verified-query cache for
  accuracy, rather than relying on raw model scale (see INTERNAL_NOTES.md §3-4)
✓ AWS Bedrock kept as a fallback via the same model_alias switch
```

### 3. **Hybrid Anomaly Detection**
```
Selected: Combination of Statistical + Business Rules + ML

Approach:
┌─ Z-score (2σ threshold)
├─ Business Rules (3x vendor avg)
├─ Isolation Forest (0.1 contamination)
└─ Deduplicate + rank by severity

Why Hybrid?
✓ Statistical catches obvious outliers
✓ Business rules catch contextual anomalies
✓ ML catches complex patterns
✓ Deduplication prevents false alarms
```

### 4. **Redis for Session Management**
```
Selected: Redis (vs. in-memory or database)

Reasons:
✓ Sub-millisecond access
✓ Built-in TTL (auto-expiration)
✓ Scalable (can add more servers)
✓ Prompt caching potential
✓ Conversation history persistence
```

### 5. **DuckDB over PostgreSQL**
```
Selected: DuckDB (for prototype)

Rationale:
✓ Embedded (no server needed)
✓ Optimized for OLAP (GROUP BY, aggregations)
✓ Auto-indexes common columns
✓ <100ms queries on 100K rows
✓ Works locally + Docker

Note: Can migrate to PostgreSQL for production
```

---

## Confidence Scoring Mechanism

### Components (Ensemble Approach)
```python
confidence = (
    query_clarity * 0.4 +        # How unambiguous was the question?
    data_completeness * 0.3 +    # How much data matched filters?
    result_reliability * 0.3     # How confident in SQL accuracy?
)
```

### Score Bands
- 🟢 **High (>80%)**: "Based on X records, we found..."
- 🟡 **Medium (60-80%)**: "We found Y, but note that..."
- 🔴 **Low (<60%)**: "Please clarify: Is this what you meant?"

### Where Scores Come From
- **query_clarity**: Classification LLM confidence
- **data_completeness**: % of requested data available
- **result_reliability**: Based on # results + anomalies

---

## Grounding Validation

### Checks Implemented
1. ✅ **SQL Verification**: Query matches schema
2. ✅ **Data Completeness**: Check for nulls/missing values
3. ✅ **Hallucination Detection**: Numbers come from results only
4. ✅ **Date Range Validation**: Filters applied correctly
5. ✅ **Anomaly Flagging**: Unusual values highlighted

### False Positive Prevention
- Only flag anomalies with clear justification
- Show historical context ("avg was $X")
- Multiple detection methods must agree

---

## Testing & Validation

### Unit Tests (Backend)
```bash
pytest backend/tests/ -v
```

### Integration Tests (Full Pipeline)
```bash
cd benchmarks
python run_benchmark.py
```

### Manual Testing
```bash
# 1. Create session
curl -X POST http://localhost:8000/sessions/create

# 2. Ask question
curl -X POST http://localhost:8000/chat \
  -H "Content-Type: application/json" \
  -d '{
    "session_id": "...",
    "message": {"content": "What is the total transaction volume by account?"},
    "model": "qwen2.5-coder-1.5b"
  }'
```

---

## Performance (measured via the OpenAI-compatible `/v1/chat/completions` endpoint)

See [INTERNAL_NOTES.md](INTERNAL_NOTES.md) §4 for the full, current numbers (measured against a
live Qwen2.5-Coder-1.5B-Instruct deployment) and an honest read of what's a real effect vs
run-to-run variance. Summary, small dataset:

### Accuracy (execution-verified)
- Easy Questions: 100%
- Moderate Questions: 80%
- Complex Questions: 46.7%
- Overall: 75.6% (execution-verified: SQL extracted and run against real DuckDB data)

### Grounding Targets (measured)
- Data completeness (grounding score): 80%+
- Hallucination rate: <20%
- SQL execution rate (ran without error): >90%
- False positive anomalies: <5% (design target)

---

## Deployment Checklist

- [ ] Environment variables in `.env`
- [ ] AWS Bedrock access verified
- [ ] Data CSV files loaded
- [ ] DuckDB database initialized
- [ ] Redis running (Docker or local)
- [ ] Backend dependencies installed
- [ ] Frontend dependencies installed
- [ ] Run `init.py` to verify
- [ ] Start backend: `python backend/main.py`
- [ ] Start frontend: `npm run dev`
- [ ] Test chat endpoint
- [x] Run benchmark: `python benchmarks/run_benchmark.py` (execution-verified results in `benchmarks/benchmark_results_20260905_011009.json`)

---

## Future Enhancements

1. **PostgreSQL Migration**: For multi-tenant production
2. **WebSocket Streaming**: Real-time response streaming
3. **Advanced Caching**: Prompt caching for repeated queries
4. **Multi-language Support**: Non-English queries
5. **Custom Metrics**: Domain-specific anomaly rules
6. **Audit Logging**: Regulatory compliance
7. **API Rate Limiting**: Prevent abuse
8. **Advanced Auth**: User roles, access control

---

## Troubleshooting

### Common Issues

**Redis Connection Error**
```bash
# Check if Redis is running
redis-cli ping

# If not, start it
docker run -d -p 6379:6379 redis:latest
```

**DuckDB File Locked**
```bash
# Restart backend
rm ./data/finance.db
python backend/main.py
```

**Model Not Found**
```bash
# Verify AWS credentials
aws bedrock list-foundation-models --region us-east-1

# Check .env variables
grep QWEN .env
```

**Slow Queries**
```
• Add indexes (done in database.py)
• Check result set size (< 10K rows recommended)
• Verify SQL optimization (EXPLAIN query)
```

---

## Support & Documentation

- **README.md**: Getting started guide
- **API Docs**: `http://localhost:8000/docs`
- **Benchmark Report**: `benchmarks/report_*.txt`
- **Database Schema**: `GET /schema` endpoint

---

## Summary

This implementation provides a **production-quality prototype** of a conversational finance assistant that:

1. ✅ **Understands** natural language via LLM classification
2. ✅ **Generates** SQL without hallucinating
3. ✅ **Validates** before execution (prevents errors)
4. ✅ **Detects** anomalies (statistical + business context)
5. ✅ **Scores** confidence (knows when uncertain)
6. ✅ **Grounds** answers (shows data provenance)
7. ✅ **Exports** results (CSV breakdown)
8. ✅ **Scales** across sessions (Redis management)
9. ✅ **Benchmarks** live (Qwen2.5-Coder-1.5B-Instruct as default, AWS Bedrock models available as fallback)

**Primary Design Principle**: Accuracy through grounding, not raw model size.

---

**Built for TBX—BVP Tech Catalyst Hackathon**  
Last Updated: September 5, 2026
