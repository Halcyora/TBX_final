# Sample Questions — TBX Finance Assistant

> 📚 **Full Docs**: See [DOCS.md](DOCS.md) for complete guide index

Grounded in the actual `bank` / `account` / `transaction` dataset (`data/small/*.csv`). Use these to test the assistant or as UI example prompts.

## Question Categories

```mermaid
graph TD
    A["Financial<br/>Queries"]
    A --> B["Account Lookup"]
    A --> C["Transaction Search"]
    A --> D["Reconciliation"]
    A --> E["Aggregation"]
    A --> F["Bank Analysis"]
    
    B --> B1["Balance Queries"]
    B --> B2["Account Filtering"]
    
    C --> C1["By Date/Amount"]
    C --> C2["By Description"]
    
    D --> D1["Anomaly Detection"]
    D --> D2["Missing Data"]
    
    E --> E1["Totals & Averages"]
    E --> E2["Top N Queries"]
    
    F --> F1["Bank Comparison"]
    F --> F2["Volume Analysis"]
    
    style A fill:#e1f5ff
    style B fill:#f3e5f5
    style C fill:#fff9c4
    style D fill:#ffcdd2
    style E fill:#f1f8e9
    style F fill:#ffe0b2
```

## Account balance & lookup

- What's the available balance for account 50200013729069?
- Show me all accounts at HDFC BANK LIMITED.
- Which accounts have a negative available balance?
- List all accounts under program 21.
- What bank does account number 30123456789012 belong to?

## Transaction search

- Show me all debit transactions for account 50200013729069.
- List the last 10 transactions for account 60100112233445.
- Find transactions with description containing "SELECTION ELECTRONICS".
- Show all credit transactions above ₹100,000 in December 2025.
- What transactions happened on 2026-06-24 for account 50200013729069?

## Reconciliation & anomalies

- Show me unreconciled transactions in Q3 2026.
- Which transactions have a missing transaction_reference_id?
- Flag any transactions above ₹500,000 as high-value anomalies.
- Are there duplicate UTR numbers across transactions?
- Which accounts have unusually large debit transactions this month?

## Aggregation & totals

- What is the total debit amount for account acfbe204-7541-492c-a352-040aa984bedc?
- What's the total transaction volume per bank?
- List the top 10 accounts by total credit amount.
- Compare total debits vs credits for HDFC accounts.
- What is the average transaction amount by transaction_type?

## Bank-level questions

- List all banks in the system.
- How many accounts does UNION BANK OF INDIA have?
- Which bank has the highest total available balance across its accounts?
- Show total transaction count grouped by bank_code.

## Notes

### Query Complexity Levels

```mermaid
graph LR
    A["Simple"]
    B["Moderate"]
    C["Complex"]
    
    A -->|~50ms| D["Direct Lookup<br/>Single Table"]
    B -->|100-200ms| E["Multi-Table<br/>Aggregation"]
    C -->|300-500ms| F["Pattern Detection<br/>Anomalies"]
    
    style A fill:#c8e6c9
    style B fill:#fff9c4
    style C fill:#ffcdd2
    style D fill:#f1f8e9
    style E fill:#ffe0b2
    style F fill:#ffccbc
```

### Data Privacy Notes

- `account_number` and `utr_number` are treated as sensitive — the assistant should mask them in responses rather than echoing raw values.
- `transaction_reference_id` is plaintext and safe to search directly; don't confuse it with `utr_number` unless the user explicitly says "UTR".
- Dates in the dataset span late 2025–mid 2026; adjust "Q3"/"this month" style questions accordingly when testing.
