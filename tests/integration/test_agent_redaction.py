"""Redaction canary over all six tools (#10; `_docs/api.md` -> *Redaction contract*).

Three imports hold catalog content made of canary strings that cannot occur by
coincidence, one for each place catalog content lives: the vendor display
name, the filename, the SKUs, the product names, a cell value quoted by a
validation message and an unexpected header name quoted by the header error.
Every tool is called on them, accepted and refused; no canary may appear in
any result or any `TOOL_CALL` row, and no key outside the allowed list.
"""

import json
import uuid

from app.services import agent_tools
from app.services.agent_tools import (
    get_import_attempts,
    get_import_diagnostics,
    get_import_incident,
    mark_needs_attention,
    resolve_alert,
    retry_failed_import,
)
from tests.integration.tooling import action_rows, claim, upload
from tests.unit.test_agent_tool_results import keys_at_any_depth


def test_no_canary_reaches_a_result_or_an_audit_row(client, migrated_engine, ns):
    suffix = uuid.uuid4().hex[:10]
    canary = {
        name: f"CANARY{name.upper()}{suffix}"
        for name in ("vendor", "file", "sku", "name", "cell", "header", "product")
    }

    # 1. VALIDATION_ERROR with row errors: the price cell is quoted, the SKU too (duplicate).
    rows_csv = (
        "sku,name,price,quantity\n"
        f"{canary['sku']},{canary['name']},{canary['cell']},1\n"
        f"{canary['sku']},{canary['name']},2.00,1\n"
    ).encode()
    row_errors = upload(
        client, ns.name(canary["vendor"]), rows_csv, filename=f"{canary['file']}.csv"
    )
    messages = " ".join(e["message"] for e in row_errors["validation_errors"])
    assert canary["cell"] in messages and canary["sku"] in messages  # the canaries are stored

    # 2. VALIDATION_ERROR with a header error quoting an unexpected header name.
    header_csv = f"sku,name,price,quantity,{canary['header']}\nA-1,Lamp,1.00,1,x\n".encode()
    header_error = upload(
        client, ns.name(canary["vendor"]), header_csv, filename=f"{canary['file']}.csv"
    )
    assert canary["header"] in header_error["validation_errors"][0]["message"]

    # 3. An injected TRANSIENT_STORAGE_TIMEOUT of canary products, retried successfully.
    products_csv = (
        "sku,name,price,quantity\n"
        f"{canary['product']}-1,{canary['name']} One,1.00,1\n"
        f"{canary['product']}-2,{canary['name']} Two,2.00,2\n"
    ).encode()
    transient = upload(
        client,
        ns.name(canary["vendor"]),
        products_csv,
        filename=f"{canary['file']}.csv",
        inject="true",
    )
    assert transient["failure_code"] == "TRANSIENT_STORAGE_TIMEOUT"

    results = []
    for body in (row_errors, header_error, transient):
        alert_id, import_id = body["alert"]["id"], body["id"]
        results += [
            get_import_incident(alert_id),
            get_import_attempts(import_id),
            get_import_diagnostics(import_id),
            mark_needs_attention(alert_id, "needs a look"),  # OPEN: refused
            resolve_alert(alert_id),  # refused unless COMPLETED
            retry_failed_import(import_id),  # refused for the validation errors
        ]
        assert claim(alert_id)
        results += [
            mark_needs_attention(alert_id, "needs corrected upload"),
            retry_failed_import(import_id),  # refused everywhere now
            resolve_alert(alert_id),
            get_import_incident(alert_id),
        ]
    outcomes = {r["outcome"] for r in results}
    assert outcomes == {"DONE", "REFUSED"}

    stored = []
    for body in (row_errors, header_error, transient):
        for action in action_rows(migrated_engine, body["alert"]["id"]):
            stored += [action["result"], action["reason_summary"]]
    assert len(stored) == 2 * 3 * 10

    for value in [*results, *stored]:
        serialised = json.dumps(value)
        for name, text in canary.items():
            assert text not in serialised, f"{name} canary leaked: {serialised}"
        assert keys_at_any_depth(value) <= agent_tools.ALLOWED_KEYS
