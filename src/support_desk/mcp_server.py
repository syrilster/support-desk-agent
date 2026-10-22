"""MCP server that exposes tools and KB docs as resources."""
import json
import sys
import traceback
from typing import Any

from mcp.server import Server
from mcp.types import (
    Resource,
    TextContent,
    Tool,
    ToolAnnotations,
)

from support_desk.db import connect
from support_desk.refunds import issue_refund
from support_desk.tools import (
    lookup_customer,
    list_orders,
    get_refund_status,
    search_kb_tool,
)

import uuid


PROCESS_TICKET = f"mcp-{uuid.uuid4().hex[:8]}"
VERIFIED: dict[str, str] = {}   # ticket_id -> customer_id
NEEDS_VERIFICATION = {
    "error": "Customer not verified. Ask the customer for their account email "
             "and call lookup_customer first."
}

server = Server("support-desk-agent")

def _ticket_id() -> str:
    try:
        meta = server.request_context.meta
        if meta is not None and (tid := meta.model_dump().get("ticket_id")):
            return str(tid)
    except LookupError:
        pass
    return PROCESS_TICKET


def _customer_id() -> str | None:
    # Trusted channel first: an id the host authenticated and sent in _meta.
    # Fallback: the customer whose email was verified in this ticket.
    try:
        meta = server.request_context.meta
        if meta is not None and (cid := meta.model_dump().get("customer_id")):
            return str(cid)
    except LookupError:
        pass
    return VERIFIED.get(_ticket_id())

def _owns(customer_id: str, order_id: str) -> bool:
    with connect() as conn:
        return conn.execute(
            "SELECT 1 FROM orders WHERE id=%s AND customer_id=%s", (order_id, customer_id)
        ).fetchone() is not None


# ===== TOOLS =====
# Registration (at import time)
# @server.call_tool() doesn't wrap your function for direct use. It builds an internal handler that wraps your function and stores it in a dict, server.request_handlers[types.CallToolRequest] = handler (mcp/server/lowlevel/server.py:592). @server.list_tools(), @server.list_resources() and @server.read_resource() register themselves the same way, each under its own request type.

# Runtime call chain
# 1. agent_mcp.py runs session.call_tool("lookup_customer", {...}), which sends a JSON-RPC tools/call message to the server process's stdin.
# 2. server.run(...) in your __main__ block loops over session.incoming_messages (line 681). It starts a task for each message, which goes through _handle_message to _handle_request.
# 3. _handle_request looks up self.request_handlers.get(type(req)) (line ~735) and awaits the matching handler(req).
# 4. For CallToolRequest, the wrapper does the following:
#    - It checks arguments against the tool's inputSchema. To do that it first calls your list_tools handler, which is why the schemas you advertise are enforced.
#    - It calls your handle_tool_call(tool_name, arguments).
#    - It normalizes your return value into a CallToolResult. Returning a list[TextContent] works.
#    - It converts any exception into an isError result.
# 5. The response goes back over stdout, and session.call_tool returns it in the client.

# So server.run() is the dispatch loop, and your decorated functions are only entries in its routing table.
@server.call_tool()
async def handle_tool_call(name: str, arguments: dict[str, Any]) -> list[TextContent]:
    """Handle tool calls from the agent."""
    try:
        if name == "lookup_customer":
            result = lookup_customer(**arguments)
            if isinstance(result, dict) and "id" in result:
                ticket = _ticket_id()
                if VERIFIED.get(ticket, result["id"]) != result["id"]:
                    result = {"error": "This conversation is already verified for another "
                                       "customer. Start a new ticket."}
                else:
                    VERIFIED[ticket] = result["id"]
        elif name in ("list_orders", "get_refund_status", "issue_refund"):
            cid = _customer_id()
            if not cid:
                result = NEEDS_VERIFICATION
            elif name == "list_orders":
                result = list_orders(customer_id=cid)   # model-supplied id is ignored
            elif not _owns(cid, arguments["order_id"]):
                result = {"error": f"Order {arguments['order_id']} not found"}
            elif name == "get_refund_status":
                result = get_refund_status(order_id=arguments["order_id"])
            else:
                result = issue_refund(
                    order_id=arguments["order_id"],
                    amount=arguments["amount"],
                    reason=arguments.get("reason", ""),
                    idempotency_key=f"{_ticket_id()}:{arguments['order_id']}",
                    customer_id=cid,
                )
        elif name == "search_kb":
            result = search_kb_tool(arguments["query"])
        else:
            result = {"error": f"Unknown tool: {name}"}
    except Exception:
        traceback.print_exc(file=sys.stderr)
        result = {"error": "Internal error while processing the request."}
    return [TextContent(type="text", text=json.dumps(result, default=str))]


# ===== TOOL DEFINITIONS =====
@server.list_tools()
async def list_tools() -> list[Tool]:
    """Advertise available tools."""
    return [
        Tool(
            name="lookup_customer",
            description="Find a customer by email address. Returns customer id, name and email. Call this first to get the customer id needed by list_orders.",
            inputSchema={
                "type": "object",
                "properties": {"email": {"type": "string", "description": "Customer email address"}},
                "required": ["email"],
            }
        ),
        Tool(
            name="list_orders",
            description="List all orders for a customer id (format C001), newest first. Returns order id, status, carrier, eta, total and date placed.",
            inputSchema={
                "type": "object",
                "properties": {"customer_id": {"type": "string", "description": "Customer id, e.g. C001"}},
                "required": ["customer_id"],
            }
        ),
        Tool(
            name="get_refund_status",
            description="Get refund records for one order id (format A1001). Returns amount and status.",
            inputSchema={
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "Order id, e.g. A1001"}},
                "required": ["order_id"],
            }
        ),
        Tool(
            name="search_kb",
            description="Search the knowledge base by semantic similarity (embedding-based). Works with synonyms and paraphrases.",
            inputSchema={
                "type": "object",
                "properties": {"query": {"type": "string", "description": "Search query"}},
                "required": ["query"],
            },
        ),
        Tool(
            name="issue_refund",
            description=(
                "Request a refund for an order. Large or unusual refunds are queued for human "
                "approval. The returned status says what actually happened; never claim a refund "
                "was issued unless status is 'executed'."
            ),
            inputSchema={
                "type": "object",
                "properties": {
                    "order_id": {"type": "string", "description": "Order id, e.g. A1008"},
                    "amount": {"type": "number", "description": "Refund amount in dollars"},
                    "reason": {"type": "string"},
                },
                "required": ["order_id", "amount", "reason"],
                "additionalProperties": False,
            },
            annotations=ToolAnnotations(readOnlyHint=False, destructiveHint=True, idempotentHint=True),
        ),
    ]


if __name__ == "__main__":
    import asyncio
    from mcp.server.stdio import stdio_server

    async def run():
        async with stdio_server() as (read_stream, write_stream):
            await server.run(read_stream, write_stream, server.create_initialization_options())

    asyncio.run(run())
