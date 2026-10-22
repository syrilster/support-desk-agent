import json
import sys

from support_desk.config import MODEL, get_client
from support_desk.tools import TOOLS, run_tool

SYSTEM = (
    "You are a customer support assistant for an online store. "
    "Use tools to look up facts and never guess the order details. "
    "To find a customer's orders you need their email address: ask for it if missing. "
    "If a tool returns an error, explain it plainly or try a different approach. Don't expose the internal error details to the user. "
    "Keep answers brief. Lead with orders that are still processing or in transit, and only "
    "mention delivered or cancelled orders if the customer asks or there are only a few. "
    "Present orders in the order the tool returned them. "
    "For delivered orders, the eta field is the delivery date: say 'delivered on <date>', not 'ETA'."
    "For ANY question about policies, refunds, returns, shipping, warranties or other company rules: "
    "For knowledge base searches: use search_kb with the user's exact words. "
    "Do NOT rephrase, expand, or interpret the query. Search for what they literally asked."
    "If search_kb returns no matches, say you don't know that policy."
    "DO NOT mention or discuss the fact that you are an AI or language model. Write as if you are a human customer support agent."
)

MAX_ITERATIONS = 5


def run_turn(client, messages: list) -> str:
    for i in range(1, MAX_ITERATIONS + 1):
        response = client.chat.completions.create(
            model=MODEL, max_tokens=500, tools=TOOLS, messages=messages
        )
        choice = response.choices[0]
        messages.append(choice.message)

        if choice.finish_reason != "tool_calls":
            if choice.finish_reason == "length":
                return (choice.message.content or "") + "\n[warning: reply cut off at max_tokens]"
            return choice.message.content or ""

        for call in choice.message.tool_calls:
            try:
                args = json.loads(call.function.arguments)
                result = run_tool(call.function.name, args)
            except json.JSONDecodeError as e:
                result = {"error": f"Arguments were not valid JSON: {e}"}
            print(f"  [iter {i}] {call.function.name}({call.function.arguments}) -> {json.dumps(result, default=str)[:120]}")
            messages.append(
                {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result, default=str)}
            )
    return f"[stopped: hit the {MAX_ITERATIONS}-iteration cap without a final answer]"


def main() -> None:
    client = get_client()
    messages = [{"role": "user", "content": SYSTEM}]

    if len(sys.argv) > 1:
        messages.append({"role": "user", "content": " ".join(sys.argv[1:])})
        print(run_turn(client, messages))
        return

    print("Support Desk Copilot. Type 'quit' to exit.")

    while True:
        user = input("\nyou> ").strip()
        if user.lower() in {"quit", "exit", ""}:
            break
        messages.append({"role": "user", "content": user})
        print("\nagent>", run_turn(client, messages))

if __name__ == "__main__":
    main()