"""Rules: view, add, and delete the URL-processing rules.

``GET /rules`` renders the ordered rule list (read-only connection). Adding and
deleting are the only writes the web app makes outside the archive worker, so
they open a short-lived read-write connection inside a thread (sqlite handles
are thread-affine) rather than through the read-only request dependency.
"""

import asyncio

from datastar_py.fastapi import (
    DatastarResponse,
    ReadSignals,
    ServerSentEventGenerator,
)
from fastapi import APIRouter, Depends
from fastapi.responses import HTMLResponse

from arciv.core.db import PageDatabase, Rule
from arciv.core.db.models import RULE_ACTIONS, RULE_MATCH_TYPES, validate_rule

from .. import config
from ..dependencies import get_db
from ..rendering import render

router = APIRouter()


def _result_patch(message: str, kind: str) -> DatastarResponse:
    """Patch the inline #rule-result alert (used for validation problems)."""
    fragment = render("partials/_rule_result.html", message=message, kind=kind)
    return DatastarResponse(ServerSentEventGenerator.patch_elements(fragment))


@router.get("/rules", response_class=HTMLResponse)
def rules(db: PageDatabase = Depends(get_db)) -> str:
    """List the URL rules in the order they are applied."""
    return render(
        "rules.html",
        rules=db.list_rules(),
        match_types=RULE_MATCH_TYPES,
        actions=RULE_ACTIONS,
    )


@router.post("/rules")
async def add_rule(signals: ReadSignals) -> DatastarResponse:
    """Add a rule from the Datastar signals, then reload the list.

    Validation problems are shown inline so the entered values are not lost;
    a valid rule is appended and the page reloads to show it in order.
    """
    data = signals or {}
    match_type = (data.get("match_type") or "").strip()
    pattern = (data.get("pattern") or "").strip()
    action = (data.get("action") or "").strip()
    replacement = (data.get("replacement") or "").strip() or None

    error = validate_rule(match_type, pattern, action, replacement)
    if error:
        return _result_patch(error, "error")

    rule = Rule(
        match_type=match_type,
        pattern=pattern,
        action=action,
        replacement=replacement,
    )
    await asyncio.to_thread(_insert_rule, rule)
    return DatastarResponse(ServerSentEventGenerator.redirect("/rules"))


@router.post("/rules/{rule_id}/delete")
async def delete_rule(rule_id: int) -> DatastarResponse:
    """Delete a rule by id, then reload the list."""
    await asyncio.to_thread(_delete_rule, rule_id)
    return DatastarResponse(ServerSentEventGenerator.redirect("/rules"))


def _insert_rule(rule: Rule) -> None:
    with PageDatabase(config.DB_PATH) as db:
        db.add_rule(rule)


def _delete_rule(rule_id: int) -> None:
    with PageDatabase(config.DB_PATH) as db:
        db.remove_rule(rule_id)
