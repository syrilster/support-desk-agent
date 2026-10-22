from datetime import date, datetime, timezone
from decimal import Decimal, InvalidOperation

from support_desk import guardrails as g
from support_desk.db import connect

MESSAGES = {
    "executed": "Refund issued.",
    "pending_approval": "Submitted for human approval. It has NOT been issued. "
                        "Tell the customer it is under review and do not promise approval.",
    "rejected": "Refund not allowed: {note}. Do not retry with other amounts. "
                "Tell the customer a human agent will follow up.",
}

def _money(value):
    try:
        return Decimal(str(value)).quantize(Decimal("0.01"))
    except (InvalidOperation, ValueError):
        return None

def _committed(cur, order_id, exclude_request_id=None) -> Decimal:
    refunded = cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM refunds "
        "WHERE order_id=%s AND status <> 'rejected'", (order_id,)
    ).fetchone()["s"]
    pending = cur.execute(
        "SELECT COALESCE(SUM(amount),0) AS s FROM refund_requests "
        "WHERE order_id=%s AND status='pending_approval' AND id <> COALESCE(%s, -1)",
        (order_id, exclude_request_id),
    ).fetchone()["s"]
    return refunded + pending


def _days_since_delivery(order):
    if order["status"] != "delivered" or not order["eta"]:
        return None
    return (date.today() - order["eta"]).days

def _insert_refund(cur, req):
    cur.execute(
        "INSERT INTO refunds (id, order_id, amount, status, requested_on) "
        "VALUES (%s, %s, %s, 'paid', current_date)",
        (f"RR{req['id']:04d}", req["order_id"], req["amount"]),
    )

def _view(row, duplicate=False):
    return {
        "request_id": row["id"],
        "order_id": row["order_id"],
        "amount": str(row["amount"]),
        "status": row["status"],
        "message": MESSAGES[row["status"]].format(note=row["decision_note"]),
        "duplicate": duplicate,
    }


def issue_refund(order_id: str, amount, reason: str, idempotency_key: str, customer_id: str) -> dict:
    amt = _money(amount)
    if amt is None or amt <= 0:
        return {"error": "amount must be a positive number"}
    reason = (reason or "").strip()[:500]

    with connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            # Lock the order first: concurrent requests on one order are serialized.
            order = cur.execute(
                "SELECT id, customer_id, total, status, eta FROM orders WHERE id=%s FOR UPDATE", (order_id,)
                ).fetchone()
            if not order or order["customer_id"] != customer_id:
                return {"error": f"Order {order_id} not found"}

            prior = cur.execute(
                "SELECT * FROM refund_requests WHERE idempotency_key=%s", (idempotency_key,)
            ).fetchone()
            if prior:
                return _view(prior, duplicate=True)

            remaining = order["total"] - _committed(cur, order_id)
            status, note, flags = "executed", None, []

            if amt > g.AUTO_APPROVE_HARD_CAP:
                status, note = "rejected", "amount exceeds the automatic refund cap"
            elif amt > remaining:
                status, note = "rejected", "amount exceeds what is left to refund on this order"
            else:
                if amt > g.AUTO_APPROVE_LIMIT:
                    flags.append(f"amount > {g.AUTO_APPROVE_LIMIT}")
                days = _days_since_delivery(order)
                if days is None:
                    flags.append(f"order status is {order['status']}")
                elif days > g.RETURN_WINDOW_DAYS:
                    flags.append(f"delivered {days} days ago")
                if flags:
                    status = "pending_approval"

            decided = None if status == "pending_approval" else datetime.now(timezone.utc)
            row = cur.execute(
                """INSERT INTO refund_requests
                   (idempotency_key, order_id, amount, reason, status, flags, decision_note, decided_at)
                   VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING *""",
                (idempotency_key, order_id, amt, reason, status, "; ".join(flags) or None, note, decided),
            ).fetchone()
            if status == "executed":
                _insert_refund(cur, row)
            return _view(row)


def decide(request_id: int, action: str, reviewer: str, amount=None, note=None) -> dict:
    """Human-only. Never register this as a model tool."""
    with connect() as conn:
        with conn.transaction():
            cur = conn.cursor()
            req = cur.execute(
                "SELECT * FROM refund_requests WHERE id=%s FOR UPDATE", (request_id,)
            ).fetchone()
            if not req or req["status"] != "pending_approval":
                return {"error": "request not found or already decided"}

            if action == "reject":
                status, amt = "rejected", req["amount"]
            elif action == "approve":
                amt = _money(amount) if amount is not None else req["amount"]
                order = cur.execute(
                    "SELECT total FROM orders WHERE id=%s FOR UPDATE", (req["order_id"],)
                ).fetchone()
                remaining = order["total"] - _committed(cur, req["order_id"], request_id)
                if amt is None or amt <= 0 or amt > g.AUTO_APPROVE_HARD_CAP or amt > remaining:
                    return {"error": f"amount must be > 0, <= {g.AUTO_APPROVE_HARD_CAP}  and <= {remaining}"}
                status = "executed"
            else:
                return {"error": "action must be approve or reject"}

            row = cur.execute(
                """UPDATE refund_requests SET status=%s, amount=%s, reviewer=%s,
                   decision_note=%s, decided_at=now() WHERE id=%s RETURNING *""",
                (status, amt, reviewer, note, request_id),
            ).fetchone()
            if status == "executed":
                _insert_refund(cur, row)
            return _view(row)