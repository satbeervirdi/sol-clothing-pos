"""
Audit Logging Service for SOL POS & CRM.
Provides immutable traceability of business-critical events:
price changes, stock adjustments, returns, cancellations, customer edits.
"""
import json
import sqlite3
from datetime import datetime
from typing import Optional, Any


def log_audit(
    conn: sqlite3.Connection,
    entity_type: str,
    entity_id: Any,
    action: str,
    before_state: Optional[Any] = None,
    after_state: Optional[Any] = None,
    reason: str = "",
    user_id: int = 1
):
    """
    Records an immutable audit log entry within the caller's database transaction.
    """
    now = datetime.now().isoformat()
    before_json = json.dumps(before_state, default=str) if before_state is not None else None
    after_json = json.dumps(after_state, default=str) if after_state is not None else None

    conn.execute("""
    INSERT INTO audit_logs (
        entity_type, entity_id, action, before_state, after_state, reason, user_id, created_at
    )
    VALUES (?, ?, ?, ?, ?, ?, ?, ?)
    """, (
        entity_type.upper(),
        str(entity_id),
        action.upper(),
        before_json,
        after_json,
        reason or "",
        user_id,
        now
    ))
