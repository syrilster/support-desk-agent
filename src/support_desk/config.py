import os

from dotenv import load_dotenv
from openai import OpenAI

load_dotenv()

MODEL = os.getenv("COPILOT_MODEL", "gpt-4o-mini")


def get_client() -> OpenAI:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")
    return OpenAI()
