# Sample Questions — TBX Finance Assistant

Grounded in the actual `bank` / `account` / `transaction` dataset (`data/small/*.csv`). Use these to test the assistant or as UI example prompts.

## Account balance & lookup

- Show me all accounts at HDFC BANK LIMITED.
- Which accounts have a negative available balance?
- List all accounts under program 21.
- What bank does account `acfbe204-7541-492c-a352-040aa984bedc` belong to?
- Show me the account number and bank name for accounts with a negative balance.

## Transaction search

- Show me all debit transactions for account `acfbe204-7541-492c-a352-040aa984bedc`.
- List the last 10 transactions for account `6f306737-dfa8-4bf7-8003-be64034b8dea`.
- Find transactions with description containing "SELECTION ELECTRONICS".
- Show all credit transactions above 100,000 in December 2025.
- What transactions happened on 2026-06-24 for account `acfbe204-7541-492c-a352-040aa984bedc`?

## Anomalies & data quality

- Which transactions have a missing transaction_reference_id?
- Flag any transactions above 500,000 as high-value anomalies.
- Are there duplicate UTR numbers across transactions?
- Which accounts have unusually large debit transactions this month?

## Aggregation & totals

- What is the total debit amount for account `acfbe204-7541-492c-a352-040aa984bedc`?
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

- `account_number` and `utr_number` are encrypted at rest, but the assistant always shows the
  decrypted plaintext value in responses — there is no masking. What IS enforced: neither column
  can be used as a search/filter key (a WHERE or JOIN match against ciphertext can never succeed,
  since each row was encrypted independently) — only `IS NULL`/`IS NOT NULL` checks are allowed.
  Look up a specific account/transaction by `account_id`/`transaction_id` instead.
- `transaction_reference_id` is plaintext and safe to search directly; don't confuse it with
  `utr_number` unless the user explicitly says "UTR".
- Dates in the dataset span late 2025–mid 2026; adjust "this month"-style questions accordingly
  when testing.
- There is no reconciliation-status data in this schema (`bank`/`account`/`transaction` only) —
  don't ask about "unreconciled" transactions, there's nothing to answer that with.
