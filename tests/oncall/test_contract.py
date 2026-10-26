"""What the model is offered: exactly the six tools, and a prompt that states the policy and bounds."""

from app.oncall import llm, prompt
from app.services import agent_tools


def test_the_tool_set_is_exactly_the_six_functions():
    names = [tool["name"] for tool in llm.TOOL_DEFINITIONS]

    assert names == [
        "get_import_incident",
        "get_import_attempts",
        "get_import_diagnostics",
        "retry_failed_import",
        "mark_needs_attention",
        "resolve_alert",
    ]
    assert tuple(names) == agent_tools.TOOL_NAMES == tuple(agent_tools.TOOLS)


def test_each_tool_schema_takes_only_its_ids_and_reason():
    for tool in llm.TOOL_DEFINITIONS:
        schema = tool["input_schema"]
        assert schema["type"] == "object"
        assert schema["additionalProperties"] is False
        assert set(schema["required"]) == set(schema["properties"])
        assert set(schema["properties"]) <= {"alert_id", "import_id", "reason"}
    by_name = {tool["name"]: tool["input_schema"]["properties"] for tool in llm.TOOL_DEFINITIONS}
    assert set(by_name["mark_needs_attention"]) == {"alert_id", "reason"}
    assert by_name["retry_failed_import"]["import_id"]["type"] == "integer"


def test_the_prompt_states_the_four_policy_rows_and_the_two_bounds():
    text = prompt.system_prompt(max_tool_calls=8, timeout_seconds=120)

    # The four rows of `_docs/team/oncall-agent.md` -> *Policy*.
    assert "TRANSIENT_STORAGE_TIMEOUT with attempt_count 1: call retry_failed_import once" in text
    assert "If the import is then COMPLETED, call resolve_alert" in text
    assert "TRANSIENT_STORAGE_TIMEOUT with attempt_count 2 or more: do not retry" in text
    assert 'mark_needs_attention("retry budget exhausted")' in text
    assert "VALIDATION_ERROR: never retry and never modify the file" in text
    assert "validation error count" in text and '"needs corrected' in text
    assert "Anything else, or an unknown code: do not retry" in text
    assert "Call mark_needs_attention with the failure code" in text
    # The two bounds, with the configured values.
    assert "at most 8 tool calls" in text
    assert "at most 120 seconds" in text
    assert '"agent run exceeded limits"' in text
    assert "At most two attempts per import" in text


def test_the_prompt_follows_the_configured_bounds():
    text = prompt.system_prompt(max_tool_calls=3, timeout_seconds=7.5)

    assert "at most 3 tool calls" in text and "at most 7.5 seconds" in text


def test_the_first_message_names_only_the_two_ids():
    assert prompt.first_message(12, 34) == (
        "Alert 12 for import 34 is claimed for you. "
        "Start with get_import_incident(12) and follow the policy."
    )
