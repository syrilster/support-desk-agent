import os

from dotenv import load_dotenv
from openai import AsyncOpenAI, OpenAI

load_dotenv()

MODEL = os.getenv("COPILOT_MODEL", "gpt-4o-mini")

def _require_key() -> None:
    if not os.getenv("OPENAI_API_KEY"):
        raise SystemExit("OPENAI_API_KEY is not set. Copy .env.example to .env and add your key.")


def get_client() -> OpenAI:
    _require_key()
    return OpenAI()

def get_async_client() -> AsyncOpenAI:
    _require_key()
    return AsyncOpenAI()
