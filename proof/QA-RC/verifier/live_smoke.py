"""Verifier live smoke: ONE DeepSeek JSON call through LLMClient.generate_json (schema-validated). Never prints keys.
(The Gnani kn-IN TTS->STT round trip was run once earlier; output in live_smoke.txt.)"""
import asyncio
from pydantic import BaseModel
from pareeksha.llm.factory import build_client
from pareeksha.llm.base import ChatMessage, LLMPurpose
from pareeksha.llm.config import LLMSettings

class Out(BaseModel):
    ok: bool
    word: str

async def main():
    s = LLMSettings(); c = build_client(s)
    print("llm_provider", s.llm_provider.value, "caller_model", s.deepseek_caller_model)
    r = await c.generate_json(purpose=list(LLMPurpose)[0], schema=Out, max_output_tokens=60,
        messages=[ChatMessage(role="user", content='Return JSON {"ok": true, "word": "pareeksha"}')])
    print("deepseek_ok", r.value if hasattr(r, "value") else r.model_dump().get("data"), "tokens", getattr(r, "usage", None))
asyncio.run(main())
