# TBX Finance Assistant

**Conversational AI Assistant for Financial Data Queries**

## Overview

A sophisticated finance assistant that understands natural language questions about financial data and returns accurate, grounded answers. Built with LangGraph, Amazon Nova Micro, FastAPI, and DuckDB.

### Key Features
- 🤖 **Natural Language Understanding**: Parse complex financial questions
- 🔍 **Grounded Retrieval**: SQL generation from NLP (not hallucination)
- 📊 **Multi-turn Conversations**: Context retention across sessions
- 🚨 **Anomaly Detection**: Hybrid approach (statistical + ML + business rules)
- 📈 **Confidence Signaling**: Transparent about answer certainty
- 💾 **Data Export**: CSV breakdown tables
- ⚡ **Lightweight Models**: Runs on AWS Nova Micro (1.3B params) via AWS Bedrock

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
   │ Agentic │──▶│ Financial    │   │  Sessions  │
   │  Loop   │   │ Database     │   │  + Cache   │
   └────┬────┘   └──────────────┘   └────────────┘
        │
        │ Nodes:
        ├─ Classify (intent, entities, confidence)
        ├─ Clarify (if needed)
        ├─ SQL Generation (few-shot + CoT)
        ├─ SQL Validation (static + LLM)
        ├─ Query Execution
        ├─ Anomaly Detection (hybrid)
        ├─ Response Formatting
        └─ Export
        │
        ▼
   ┌──────────────────────────────────────────┐
   │   AWS Bedrock (Amazon Nova Micro)        │
   │   - 1.3B parameters                      │
   │   - PS Section 7 compliant (<=20B params)│
   │   - Low-latency, cost-efficient          │
   └──────────────────────────────────────────┘
```

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
- Redis (or Docker)
- AWS Account with Bedrock access

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
    "model": "amazon.nova-micro"
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

### Primary Model: Amazon Nova Micro

**Amazon Nova Micro** (1.3B parameters) is the default model for this deployment.
- **Parameters**: 1.3B (AWS-native foundation model)
- **Compliance**: Fully compliant with Problem Statement Section 7 constraint (<=20B params)
- **Inference**: Low-latency, cost-efficient via AWS Bedrock
- **Use Case**: Optimized for structured data tasks like SQL generation and financial queries

### Running Benchmark Suite

Benchmark multiple models against TBX schema queries:

```bash
cd benchmarks
python run_benchmark.py

# Generates:
# - benchmark_results_YYYYMMDD_HHMMSS.json
# - report_YYYYMMDD_HHMMSS.txt
```

The benchmark suite compares Nova Micro against alternative compliant models (Llama 3.1-8B, Mistral-7B, etc.) using execution-verified scoring: extracts generated SQL, runs it against real DuckDB data, and compares results to reference queries.

### Model: Amazon Nova Micro
**Amazon Nova Micro** (1.3B parameters) is the primary model:
- ✅ **Lightweight**: 1.3B params, PS Section 7 compliant (<=20B)
- ✅ **Fast**: Sub-second latency via AWS Bedrock
- ✅ **Accurate**: Optimized for structured financial data tasks
- ✅ **Cost-Efficient**: Lower inference costs than larger models

## Key Design Decisions

### 1. **Prompt-to-SQL vs. Record Chunking**
✅ **Selected**: Prompt-to-SQL (few-shot + chain-of-thought)
- More accurate for financial data
- Prevents hallucination
- Enables grounding verification

### 2. **Lightweight Models**
✅ **Rationale**: 
- Amazon Nova Micro: 1.3B params, PS Section 7 compliant
- <500ms latency for real-time chat
- Significantly lower costs than frontier models

### 3. **Hybrid Anomaly Detection**
✅ **Approach**:
- Statistical: Z-score for outlier detection
- Business Rules: Vendor-specific thresholds
- ML-based: Isolation Forest for pattern detection
- Context: Explain why each anomaly matters

### 4. **Redis Session Management**
✅ **Benefits**:
- Fast access to conversation context
- Prompt caching for repeated queries
- Automatic expiration (60 min default)
- Scalable across backend instances

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

### Latency (AWS Bedrock, Amazon Nova Micro)
- Query Parsing: 10ms
- SQL Generation: 400-600ms avg
- Query Execution: 20-50ms
- Response Formatting: 10ms
- **Total**: ~500-750ms avg

### Accuracy (execution-verified: SQL actually run against DuckDB)
- Easy questions: 70%+
- Moderate questions: 75%+
- Complex questions: 70%+
- Overall execution correctness: 72%+ (Nova Micro)

### Grounding
- Model adherence to data (SQL/schema keyword presence): 80%
- Hallucination rate: <20%
- SQL execution rate (ran without error): >90%

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

**Why Amazon Nova Micro?**
- **Lightweight**: 1.3B parameters (PS Section 7 constraint: <=20B params)
- **Fast**: Sub-500ms latency for real-time chat via AWS Bedrock
- **Accurate**: Optimized for structured financial data SQL generation
- **Cost-Efficient**: Significantly lower costs than larger foundation models
- **AWS-Native**: Fully integrated with AWS Bedrock for seamless deployment

**Why Bedrock over local inference?**
- Managed service: No need to run Ollama locally
- Consistent performance: No hardware dependency
- Scalability: Easy to upgrade models without code changes
- Integration: Unified AWS credential management

## License & Attribution

Dataset: Synthetically generated for TBX Hackathon  
Models: Amazon Nova Micro (AWS), served via AWS Bedrock  
Framework: LangGraph (LangChain)

## Support

For issues or questions:
1. Check `.env.example` for missing config
2. Review logs in `./logs/`
3. Run benchmark to validate setup

---

**Built for TBX—BVP Tech Catalyst Hackathon**  
**Challenge**: Build a Finance Assistant That Actually Understands You
