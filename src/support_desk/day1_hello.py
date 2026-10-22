"""Day 1, part 1: one message in, response + usage + finish reason out."""
from support_desk.config import MODEL, get_client

SYSTEM = "You are a concise customer support assistant for an online store."


def main() -> None:
    client = get_client()
    response = client.chat.completions.create(
        model=MODEL,
        max_tokens=300,
        temperature=0.2,
        messages=[
            {"role": "system", "content": SYSTEM},
            {"role": "user", "content": "In two sentences, how should I ask for a refund?"},
        ],
    )
    choice = response.choices[0]
    print(choice.message.content)
    print("\n--- metadata ---")
    print("finish_reason:", choice.finish_reason)
    print("prompt_tokens:", response.usage.prompt_tokens)
    print("completion_tokens:", response.usage.completion_tokens)


if __name__ == "__main__":
    main()
