from support_desk.db import connect
from support_desk.kb import search_kb, get_doc
from support_desk.embed import embed_search_with_snippets


def lookup_customer(email: str) -> dict:
    with connect() as conn:
        row = conn.execute(
            "SELECT id, name, email FROM customers WHERE lower(email) = lower(%s)",
            (email.strip(),),
        ).fetchone()
    return row if row else {"error": f"No customer found with email {email}"}


def list_orders(customer_id: str) -> dict:
    with connect() as conn:
        rows = conn.execute(
            "SELECT id, status, carrier, eta, total, placed_on FROM orders "
            "WHERE customer_id = %s ORDER BY placed_on DESC, id DESC",
            (customer_id,),
        ).fetchall()
    if not rows:
        return {"error": f"No orders found for customer {customer_id}"}
    return {"orders": rows}


def get_refund_status(order_id: str) -> dict:
    with connect() as conn:
        order = conn.execute("SELECT id FROM orders WHERE id = %s", (order_id,)).fetchone()
        if not order:
            return {"error": f"No order found with id {order_id}"}
        rows = conn.execute(
            "SELECT id, amount, status, requested_on FROM refunds WHERE order_id = %s",
            (order_id,),
        ).fetchall()
    if not rows:
        return {"order_id": order_id, "refunds": [], "note": "No refund has been requested for this order."}
    return {"order_id": order_id, "refunds": rows}


def search_kb_tool(query: str) -> dict:
    """Search the KB by embedding similarity (default)"""
    return embed_search_with_snippets(query, limit=5)

def search_kb_keyword_tool(query: str) -> dict:
    """Search the KB docs and return snippets."""
    results = search_kb(query, limit=5)
    if not results:
        return {"error": f"No documents matched '{query}'"}

    output = {"results": []}
    for doc_id, score in results:
        doc = get_doc(doc_id)
        if doc:
            # Extract first 150 chars around first match
            snippet = doc.body[:150] + "..." if len(doc.body) > 150 else doc.body
            output["results"].append({
                "id": doc_id,
                "title": doc.title,
                "score": score,
                "snippet": snippet
            })
    return output


def read_doc(doc_id: str) -> dict:
    doc = get_doc(doc_id)
    if not doc:
        return {"error": f"Unknown doc ID: {doc_id}"}
    return {"id": doc.id, "title": doc.title, "text": doc.body}


def run_tool(name: str, args: dict) -> dict:
    func = TOOL_FUNCS.get(name)
    if func is None:
        return {"error": f"Unknown tool: {name}"}
    try:
        return func(**args)
    except TypeError as e:
        return {"error": f"Bad arguments for {name}: {e}"}
    except Exception as e:
        return {"error": f"{name} failed: {e}"}


TOOL_FUNCS = {
    "lookup_customer": lookup_customer,
    "list_orders": list_orders,
    "get_refund_status": get_refund_status,
    "search_kb": search_kb_tool,  # embedding-based search as default
    "search_kb_keyword": search_kb_keyword_tool, # Keep keyword search as fallback
    "read_doc": read_doc
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "lookup_customer",
            "description": (
                "Find a customer by email address. Returns customer id, name and email. "
                "Call this first to get the customer id needed by list_orders."
            ),
            "parameters": {
                "type": "object",
                "properties": {"email": {"type": "string", "description": "Customer email address"}},
                "required": ["email"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "list_orders",
            "description": (
                "List all orders for a customer id (format C001), newest first. "
                "Returns order id, status, carrier, eta, total and date placed."
            ),
            "parameters": {
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "Customer id, e.g. C001"}},
                "required": ["customer_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "get_refund_status",
            "description": "Get refund records for one order id (format A1001). Returns amount and status.",
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order id, e.g. A1001"}},
                "required": ["order_id"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb",
            "description": "Search the knowledge base by semantic similarity (embedding-based). Works with synonyms and paraphrases.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query, e.g. 'return electronics'"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "search_kb_keyword",
            "description": "Keyword search. Use search_kb for normal queries.",
            "parameters": {
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Exact keyword query"}},
                "required": ["query"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_doc",
            "description": "Read the full text of one doc by ID, e.g. POL-001.",
            "parameters": {
                "type": "object",
                "properties": {"doc_id": {"type": "string", "description": "Document ID, e.g. POL-001"}},
                "required": ["doc_id"],
            },
        },
    }
]
