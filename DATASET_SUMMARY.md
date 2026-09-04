# TBX Finance Assistant - Generated Dataset Summary

## Dataset Overview
A complex, realistic financial dataset generated for the TBX Finance Assistant hackathon that mirrors real-world business scenarios with data quality issues.

### Scale
- **100,000 transactions** (11.24 MB)
- **550 vendors** (multi-industry)
- **45 chart of accounts** (complete GL structure)
- **~100,000 reconciliation records** (5.06 MB)
- **Vendor payouts** with multiple payment methods
- **Date range**: January 2023 - December 2025 (3 years)

---

## Dataset Files

### 1. transactions.csv (11.24 MB)
Core transaction records with:
- **Transaction ID**: Unique identifier (TXN0000001-TXN0100000)
- **Vendor ID**: Links to vendor_list (V00001-V00550)
- **Transaction Date**: Realistic date distribution across 3 years
- **Transaction Type**: Payment, Invoice, Expense, Refund, Credit Memo
- **Amount**: Log-normal distribution (most $100-$10K, some anomalies $1K-$200K+)
- **Account ID & Name**: Links to chart of accounts
- **Status**: Pending, Completed, Rejected, Hold
- **Invoice/Reference Numbers**: Partial data (realistic incomplete records)
- **Notes**: Data quality flags on ~10% of records

**Data Quality Issues Included:**
- ~2% duplicate transactions (same vendor, similar amount, within ±1 day)
- ~2% anomaly transactions (unusually large amounts - 5-20x normal)
- ~5% missing values in optional fields
- ~10% have data quality notes

### 2. vendor_payouts.csv (0.39 MB)
Vendor payment records:
- **Payout ID**: Unique identifier (PO0000001+)
- **Vendor ID**: Links to vendors
- **Payout Date**: Distributed across 3 years
- **Amount**: Log-normal distribution
- **Payment Method**: ACH, Wire Transfer, Check, Credit Card
- **Status**: Completed, Pending, Cancelled
- **Reference Number**: Check numbers or transaction refs

**Realistic Pattern:**
- ~70% of vendors have payouts
- Variable payment frequency (1-30 payouts per vendor)
- Amount mismatch with related transactions (realistic reconciliation challenge)

### 3. reconciliation_status.csv (5.06 MB)
Reconciliation tracking:
- **Transaction ID**: Links to transactions
- **Reconciliation Status**: 
  - Reconciled (~75%)
  - Unreconciled (~15%)
  - Partially Reconciled (~10%)
- **Matched Payout ID**: Optional link to vendor_payouts (when matched)
- **Reconciliation Date**: When transaction was reconciled
- **Last Reviewed**: Date of last review
- **Notes**: Reasons for non-reconciliation (amount mismatch, pending confirmation, etc.)

**Real-World Challenges:**
- ~25% unreconciled (matching the PS requirement)
- Explanatory notes for pending items
- Some matches exist, many don't (realistic reconciliation gaps)

### 4. chart_of_accounts.csv
General Ledger structure:
- **Account IDs**: 1000-1044 (45 accounts)
- **Account Types**: Assets, Liabilities, Equity, Revenue, Expenses
- **Account Names**: Standard GL accounts (Cash, AR, AP, Sales, COGS, etc.)

### 5. vendor_list.csv (0.03 MB)
Vendor master data:
- **Vendor ID**: V00001-V00550
- **Vendor Name**: Realistic business names
- **Industry**: Diverse (Technology, Logistics, Consulting, Manufacturing, etc.)
- **Country**: USA, Canada, UK, Germany, India (international vendors)
- **Status**: Active, Inactive, On Hold

### 6. data_dictionary.csv
Complete documentation of all fields, types, and descriptions.

---

## Key Features for Finance Assistant Testing

### ✅ Grounding Ready
- All answers must come from this data
- Clear vendor-transaction linkages
- Defined accounts and categories
- Reconciliation status tracking

### ✅ Data Quality Issues (Realistic)
- Duplicate transactions requiring deduplication
- Partial reconciliations (incomplete matches)
- Missing values in reference fields
- Anomalous transactions to flag
- Amount mismatches (transactions ≠ payouts)

### ✅ Complex Query Scenarios
The dataset supports testing:
- "How much did we spend on vendor X last month?" → Sum by vendor + date
- "Which transactions are unreconciled?" → Filter by status
- "What's the largest vendor payout?" → Identify anomalies
- "Show reconciliation breakdown by vendor" → Group + status
- "What's outstanding/pending?" → Filter by status fields
- "Which vendors have irregular transaction patterns?" → Recurring pattern detection
- Multi-period comparisons (month-over-month, year-over-year)

### ✅ Conversational AI Challenges
- **Ambiguous dates**: "last month" vs "this quarter" vs "year to date"
- **Implicit filters**: "expenses" could mean any transaction type
- **Follow-up questions**: "How does that compare to X?" requires context retention
- **Confidence signals**: Some questions have clear answers, some need "not enough data"

---

## Statistics

### Transaction Breakdown
- Recurring vendor pattern: ~20% of vendors generate ~80% of volume
- Average transaction: $~4,200 (log-normal distribution)
- Largest transaction: $200K+ (anomaly)
- Smallest transaction: <$10 (data quality test)

### Reconciliation Status
- Reconciled: 75,000 (75%)
- Unreconciled: 15,000 (15%)
- Partially Reconciled: 10,000 (10%)

### Data Quality Metrics
- Duplicate rate: ~2%
- Anomaly rate: ~2%
- Missing value rate: ~5% in optional fields
- Data quality notes: ~10%

---

## Usage for TBX Assistant

### Test Queries
```
1. "How much did we spend on vendor payments last month?"
   → Filter: reconciliation_status.status != 'Unreconciled', date range
   → Answer: Sum of matched payout amounts

2. "Which transactions are still unreconciled?"
   → Filter: reconciliation_status.status = 'Unreconciled'
   → Answer: List of TXN IDs with notes on why

3. "Show me spending by vendor for Q3 2024"
   → Filter: date range + group by vendor
   → Answer: Vendor breakdown table

4. "What are our highest-value payouts?"
   → Filter & sort: vendor_payouts by amount DESC
   → Answer: Top vendors with anomaly callouts

5. "How much is outstanding from ABC Vendor?"
   → Filter: vendor + unreconciled + grouped by status
   → Answer: Total pending + breakdown
```

### Multi-Turn Conversation Example
```
Q1: "How much did we spend last month?"
A1: "$127,450 total across 450 transactions"

Q2: "And how does that compare to the month before?"
A2: "Up 15% from $110,500 in the prior month"

Q3: "Which vendors drove that increase?"
A3: "Vendor X (+$8K), Vendor Y (+$5.5K), Vendor Z (+$4.2K)"
```

---

## Model Efficiency Considerations

This dataset is optimized for:
- ✅ Lightweight model testing (< 20B parameters)
- ✅ Efficient retrieval (indexed by transaction_id, vendor_id, date)
- ✅ Clear schema (no nested objects, flat CSV structure)
- ✅ Grounding validation (all answers verifiable)
- ❌ Not bloated with irrelevant dimensions
- ❌ No multi-currency complexity (USD only)
- ❌ No production-scale security (single company)

---

## Next Steps

1. **Schema Mapping**: Map CSV columns to your LLM-friendly schema
2. **Retrieval Setup**: Create efficient SQL/pandas queries for each question type
3. **Grounding**: Implement checks to ensure answers come from data only
4. **Testing**: Validate against sample question set
5. **Model Evaluation**: Test with lightweight models (7B-13B parameters)

---

Generated: TBX Finance Assistant Dataset v2  
Complexity: High (duplicates, anomalies, reconciliation gaps, data quality issues)  
Scale: 100K transactions, 3-year history, 550 vendors
