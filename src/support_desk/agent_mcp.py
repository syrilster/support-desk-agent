"""Day 5: agent that discovers its tools from the MCP server over stdio."""
import asyncio
import json
import os
import re
import sys
import time
import uuid

from mcp import ClientSession, StdioServerParameters
from mcp.client.stdio import stdio_client

from support_desk.agent import SYSTEM
from support_desk.config import MODEL, get_client
from support_desk.audit import audit
from support_desk.redact import redact
from support_desk.tracing import traced_run

MAX_ITERATIONS = 5

SERVER = StdioServerParameters(
    command=sys.executable,
    args=["-m", "support_desk.mcp_server"],
    env={**os.environ, "PYTHONPATH": "src"},
)

# Appended to the system prompt by the eval runner only. The interactive CLI does not use it.
META_INSTRUCTIONS = (
    " Always cite the policy IDs you relied on, like POL-001, in your reply."
    " Your reply MUST end with one final line in exactly this form, on EVERY reply, including when you"
    " ask a clarifying question, decline a request or escalate. Never omit it:"
    ' <meta>{"category": "<returns|refund_timeline|shipping|delayed_order|cancellation|'
    "damaged_item|warranty|international|gift_card|loyalty|order_modification|"
    "returns_conflict|price_adjustment|lost_package|refund_approval|account_verification|"
    "escalation|data_privacy|order_status|refund_status|multi_intent|out_of_scope|attack|"
    'unknown>", "escalate": <true|false>}</meta>'
    " Set escalate to true only when you tell the customer a human agent will follow up;"
    " simply answering a policy question is escalate false."
    " CITATIONS ARE REQUIRED: whenever your answer uses anything from search_kb, name the policy ID in the"
    " body of your reply, for example 'Per POL-002, ...'. Never answer a policy question without one."
)
META_RE = re.compile(r"\s*<meta>.*?</meta>\s*", re.S)


def to_openai_tool(t) -> dict:
    return {
        "type": "function",
        "function": {"name": t.name, "description": t.description or "", "parameters": t.inputSchema}
    }

async def run_turn(client, session: ClientSession, tools: list, messages: list, ctx, tr=None) -> str:
    for i in range(1, MAX_ITERATIONS + 1):
        response = client.chat.completions.create(
            model=MODEL, max_tokens=500, temperature=0, tools=tools, messages=messages
        )
        if tr:
            tr.add_usage(response.usage)
        choice = response.choices[0]
        messages.append(choice.message)

        if choice.finish_reason != "tool_calls":
            if choice.finish_reason == "length":
                return (choice.message.content or "") + "\n[warning: reply cut off at max_tokens]"
            return choice.message.content or ""

        for call in choice.message.tool_calls:
            t0, is_error = time.perf_counter(), False
            try:
                args = json.loads(call.function.arguments)
                result = await session.call_tool(call.function.name, args,  meta={"ticket_id": ctx["ticket_id"]})
                text = "".join(c.text for c in result.content if c.type == "text")
                is_error = bool(getattr(result, "isError", False))
            except Exception as e:
                text, is_error = json.dumps({"error": str(e)}), True
            if tr:
                tr.add_tool_call(call.function.name, call.function.arguments, text,
                                 (time.perf_counter() - t0) * 1000, is_error)
            print(redact(f"  [iter {i}] {call.function.name}({call.function.arguments}) -> {text[:120]}"))
            audit("tool_call", ticket=ctx["ticket_id"], tool=call.function.name,
                        args=call.function.arguments, result=text)
            messages.append({"role": "tool", "tool_call_id": call.id, "content": text})
    return f"[stopped: hit the {MAX_ITERATIONS}-iteration cap without a final answer]"


async def traced_turn(client, session, tools, messages, ctx) -> str:
    with traced_run(ctx["ticket_id"], MODEL) as tr:
        tr.answer = await run_turn(client, session, tools, messages, ctx, tr)
    return META_RE.sub("", tr.answer)


async def main() -> None:
    client = get_client()
    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = [to_openai_tool(t) for t in (await session.list_tools()).tools]
            print("Discovered via MCP:", ", ".join(t["function"]["name"] for t in tools))
            messages = [{"role":"user", "content":SYSTEM}]

            if len(sys.argv) > 1:
                ctx = {"ticket_id": f"cli-{uuid.uuid4().hex[:8]}"}
                messages.append({"role": "user", "content": " ".join(sys.argv[1:])})
                print(await run_turn(client, session, tools, messages, ctx))
                return

            print("Support Desk Copilot (MCP). Type 'quit' to exit.")
            while True:
                user = input("\nYou> ").strip()
                if user.lower() in {"quit", "exit", ""}:
                    break
                ctx = {"ticket_id": f"cli-{uuid.uuid4().hex[:8]}"}
                messages.append({"role":"user", "content": user})
                print("\nAgent>", await run_turn(client, session, tools, messages, ctx))

if __name__ == "__main__":
    asyncio.run(main())