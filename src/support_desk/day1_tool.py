"""Day 1, part 2: one tool, with the tool call -> tool result round trip done by hand."""
import json

from support_desk.config import MODEL, get_client

SYSTEM = (
    "You are a customer support assistant. Use tools to look up facts. "
    "Never guess order details."
)

ORDERS = {
    "A1001": {"status": "shipped", "carrier": "UPS", "eta": "2026-10-10"},
    "A1002": {"status": "processing", "carrier": None, "eta": None},
}

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "get_order_status",
            "description": (
                "Look up the current status of a customer order by its order ID "
                "(format: letter followed by digits, e.g. A1001). Returns status, carrier and ETA."
            ),
            "parameters": {
                "type": "object",
                "properties": {"order_id": {"type": "string", "description": "The order ID, e.g. A1001"}},
                "required": ["order_id"],
            },
        },
    }
]


def get_order_status(order_id: str) -> dict:
    return ORDERS.get(order_id, {"error": f"No order found with id {order_id}"})


def main() -> None:
    client = get_client()
    messages = [
        {"role": "system", "content": SYSTEM},
        {"role": "user", "content": "Where is my order A1001?"},
    ]

    first = client.chat.completions.create(
        model=MODEL, max_tokens=500, tools=TOOLS, messages=messages
    )
    choice = first.choices[0]
    print("1st finish_reason:", choice.finish_reason)

    if choice.finish_reason != "tool_calls":
        print(choice.message.content)
        return

    messages.append(choice.message)

    for call in choice.message.tool_calls:
        args = json.loads(call.function.arguments)
        print(f"tool call: {call.function.name}({args})")
        result = get_order_status(**args)
        messages.append(
            {"role": "tool", "tool_call_id": call.id, "content": json.dumps(result)}
        )

    second = client.chat.completions.create(
        model=MODEL, max_tokens=500, tools=TOOLS, messages=messages
    )
    print("2nd finish_reason:", second.choices[0].finish_reason)
    print(second.choices[0].message.content)


if __name__ == "__main__":
    main()
