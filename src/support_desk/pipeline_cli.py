"""Run the MCP-backed pipeline on one ticket.

PYTHONPATH=src python -m support_desk.pipeline_cli "my email is alice@example.com..."
"""
import asyncio
import sys
import uuid

from mcp import ClientSession
from mcp.client.stdio import stdio_client

from support_desk.agent_mcp import SERVER
from support_desk.config import get_async_client
from support_desk.pipeline import run_pipeline

async def amain() -> None:
    first = " ".join(sys.argv[1:]).strip()
    client = get_async_client()
    ticket_id = f"cli-{uuid.uuid4().hex[:8]}"   # one id per conversation
    history: list[str] = []

    async with stdio_client(SERVER) as (read, write):
        async with ClientSession(read, write) as session:
            await session.initialize()
            tools = (await session.list_tools()).tools

            ticket = first or input("ticket> ").strip()
            while ticket and ticket.lower() not in {"quit", "exit"}:
                if ticket.lower() == "/new":
                    ticket_id, history = f"cli-{uuid.uuid4().hex[:8]}", []
                    print("(new conversation)")
                else:
                    result = await run_pipeline(client, session, ticket, tools, ticket_id, history)
                    print()
                    print(result.render())
                    history.append(ticket)
                if first:          # a ticket passed on the command line runs once, as before
                    return
                ticket = input("\nticket> ").strip()


if __name__ == "__main__":
    asyncio.run(amain())