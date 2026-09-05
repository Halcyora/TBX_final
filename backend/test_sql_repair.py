"""
Self-check for the execution-feedback repair loop (langgraph_flow.py): a SQL execution
failure should trigger exactly one regeneration attempt, never an unbounded retry loop.
Run directly: python test_sql_repair.py
"""
import asyncio
import langgraph_flow as lf
from langgraph_flow import (
    FinanceAssistantState, route_repair, route_after_repair, sql_repair_node, _result_signature,
)


def test_result_signature_ignores_row_and_key_order():
    a = [{"x": 1, "y": "a"}, {"x": 2, "y": "b"}]
    b = [{"y": "b", "x": 2}, {"y": "a", "x": 1}]  # same rows, reversed order, keys reordered
    assert _result_signature(a) == _result_signature(b)

    c = [{"x": 1, "y": "a"}, {"x": 3, "y": "b"}]  # genuinely different data
    assert _result_signature(a) != _result_signature(c)


def test_route_repair_fires_once():
    state = FinanceAssistantState(user_query="q", sql_query="SELECT 1", execution_error="boom")
    assert route_repair(state) == "sql_repair"

    state.repair_attempted = True
    assert route_repair(state) == "anomaly_detection", "must not retry a second time"

    state2 = FinanceAssistantState(user_query="q", sql_query="SELECT 1", execution_error=None)
    assert route_repair(state2) == "anomaly_detection", "no error, nothing to repair"


def test_route_after_repair():
    fixed = FinanceAssistantState(user_query="q", sql_valid=True, execution_error=None)
    assert route_after_repair(fixed) == "query_execution"

    still_broken = FinanceAssistantState(user_query="q", sql_valid=True, execution_error="still broken")
    assert route_after_repair(still_broken) == "anomaly_detection"


def test_sql_repair_node_calls_llm_once_and_sets_flag(monkeypatch):
    calls = []

    async def fake_to_thread(fn, *args, **kwargs):
        calls.append(args)
        return "SELECT account_id FROM account"

    monkeypatch.setattr(asyncio, "to_thread", fake_to_thread)

    state = FinanceAssistantState(
        user_query="which accounts are negative?",
        sql_query="SELECT bogus_col FROM account",
        execution_error="Catalog Error: bogus_col does not exist",
    )
    result = asyncio.run(sql_repair_node(state))

    assert result.repair_attempted is True
    assert len(calls) == 1, "repair must call the LLM exactly once"
    assert result.sql_query == "SELECT account_id FROM account"
    assert result.execution_error is None, "cleared so the retry gets a clean shot"
    assert result.sql_valid is True


if __name__ == "__main__":
    class _FakeMonkeypatch:
        def setattr(self, obj, name, value):
            setattr(obj, name, value)

    test_route_repair_fires_once()
    test_route_after_repair()
    test_sql_repair_node_calls_llm_once_and_sets_flag(_FakeMonkeypatch())
    test_result_signature_ignores_row_and_key_order()
    print("All sql_repair self-checks passed.")
