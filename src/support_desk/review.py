import getpass

from support_desk.db import connect
from support_desk.redact import redact
from support_desk.refunds import decide

def pending():
    with connect() as conn:
        return conn.execute(
            """SELECT r.*, o.total, o.status AS order_status, o.eta
               FROM refund_requests r JOIN orders o ON o.id = r.order_id
               WHERE r.status='pending_approval' ORDER BY r.created_at"""
        ).fetchall()


def main():
    reviewer = getpass.getuser()
    while True:
        rows = pending()
        if not rows:
            print("Queue empty.")
            return
        r = rows[0]
        print(f"\n#{r['id']}  order {r['order_id']} (total {r['total']}, {r['order_status']}, eta {r['eta']})")
        print(f"requested: {r['amount']}   flags: {r['flags']}")
        print(f"reason (untrusted, from model/customer): {redact(r['reason'])!r}")
        choice = input("[a]pprove  [e]dit amount  [r]eject  [s]kip  [q]uit > ").strip().lower()
        if choice == "q":
            return
        if choice == "s":
            rows.append(rows.pop(0)); continue
        if choice == "a":
            print(decide(r["id"], "approve", reviewer))
        elif choice == "e":
            print(decide(r["id"], "approve", reviewer, amount=input("new amount: "), note="edited by reviewer"))
        elif choice == "r":
            print(decide(r["id"], "reject", reviewer, note=input("reason: ")))


if __name__ == "__main__": main()