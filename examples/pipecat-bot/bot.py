"""EMI reminder bot on Pipecat, reachable by Pareeksha through ``PareekshaFrameSerializer``.

    pip install -r requirements.txt
    GNANI_API_KEY=... DEEPSEEK_API_KEY=... python bot.py          # ws://localhost:8766/ws

Register it in Pareeksha as an agent with adapter ``pipecat`` and endpoint ``ws://<host>:8766/ws``.
The Pareeksha-specific parts are the serializer on the transport and ``GlassBoxProcessor`` after
the STT and after the LLM; everything else is an ordinary Pipecat pipeline.
"""

from __future__ import annotations

import asyncio
import logging
import os
from collections.abc import Callable
from typing import Any

import uvicorn
from fastapi import FastAPI, WebSocket
from fastapi.responses import JSONResponse
from pipecat.adapters.llm.schemas.function_schema import FunctionSchema
from pipecat.adapters.llm.schemas.tools_schema import ToolsSchema
from pipecat.audio.vad.silero import SileroVADAnalyzer
from pipecat.audio.vad.vad_analyzer import VADAnalyzer
from pipecat.frames.frames import LLMRunFrame
from pipecat.pipeline.pipeline import Pipeline
from pipecat.pipeline.worker import PipelineParams, PipelineWorker
from pipecat.processors.aggregators.llm_context import LLMContext
from pipecat.processors.aggregators.llm_response_universal import (
    LLMContextAggregatorPair,
    LLMUserAggregatorParams,
)
from pipecat.services.llm_service import FunctionCallParams, LLMService
from pipecat.services.openai.llm import OpenAILLMService
from pipecat.services.stt_service import STTService
from pipecat.services.tts_service import TTSService
from pipecat.transports.websocket.fastapi import FastAPIWebsocketParams, FastAPIWebsocketTransport
from pipecat.workers.runner import WorkerRunner

from pareeksha.adapters.base import AUDIO_FRAME_BYTES
from pareeksha.adapters.pipecat_serializer import GlassBoxProcessor, PareekshaFrameSerializer

log = logging.getLogger("pipecat_bot")

SYSTEM_PROMPT = """You are Asha, a polite collections agent for Sampoorna Finance calling about an \
overdue EMI of Rs 4,500 on a two-wheeler loan.
Speak {language_name}. Keep every reply to one or two short sentences: this is a phone call.
Begin the call by saying you are an automated assistant calling on behalf of Sampoorna Finance and \
that the call may be recorded. Then ask whether it is a good time to talk about the EMI.
If the customer agrees to pay, call record_promise_to_pay with the date they give. Never promise \
to waive fees or interest, never threaten, and never reveal other customers' details.
When the matter is settled, thank them and say goodbye."""

LANGUAGE_NAMES = {"kn-IN": "Kannada", "hi-IN": "Hindi", "en-IN": "Indian English"}


def language_name(code: str) -> str:
    return LANGUAGE_NAMES.get(code, "Indian English")


PROMISE_TOOL = ToolsSchema(
    standard_tools=[
        FunctionSchema(
            name="record_promise_to_pay",
            description="Record the date the customer promised to pay the overdue EMI.",
            properties={"date": {"type": "string", "description": "Promised payment date"}},
            required=["date"],
        )
    ]
)


async def record_promise_to_pay(params: FunctionCallParams) -> None:
    await params.result_callback({"status": "recorded", "date": params.arguments.get("date")})


def build_llm() -> LLMService:
    llm = OpenAILLMService(
        api_key=os.environ["DEEPSEEK_API_KEY"],
        base_url=os.environ.get("DEEPSEEK_BASE_URL", "https://api.deepseek.com"),
        settings=OpenAILLMService.Settings(
            model=os.environ.get("DEEPSEEK_CALLER_MODEL", "deepseek-chat"), temperature=0.4
        ),
    )
    return llm


def build_task(
    websocket: WebSocket,
    stt: STTService,
    llm: LLMService,
    tts: TTSService,
    serializer: PareekshaFrameSerializer,
    vad: VADAnalyzer | None = None,
) -> PipelineWorker:
    """The whole bot: transport(serializer) -> STT -> LLM -> glass box -> TTS -> transport."""
    transport = FastAPIWebsocketTransport(
        websocket=websocket,
        params=FastAPIWebsocketParams(
            audio_in_enabled=True,
            audio_out_enabled=True,
            audio_in_sample_rate=16000,
            audio_out_sample_rate=16000,
            fixed_audio_packet_size=AUDIO_FRAME_BYTES,
            serializer=serializer,
            session_timeout=180,
        ),
    )
    llm.register_function("record_promise_to_pay", record_promise_to_pay)
    context = LLMContext(
        messages=[
            {"role": "system", "content": SYSTEM_PROMPT.format(language_name="Indian English")}
        ],
        tools=PROMISE_TOOL,
    )
    aggregators = LLMContextAggregatorPair(
        context, user_params=LLMUserAggregatorParams(vad_analyzer=vad or SileroVADAnalyzer())
    )
    pipeline = Pipeline(
        [
            transport.input(),
            stt,
            GlassBoxProcessor(),  # what the bot heard
            aggregators.user(),
            llm,
            GlassBoxProcessor(),  # what the bot says, and its tool calls
            tts,
            transport.output(),
            aggregators.assistant(),
        ]
    )
    task = PipelineWorker(
        pipeline,
        params=PipelineParams(audio_in_sample_rate=16000, audio_out_sample_rate=16000),
        enable_rtvi=False,
    )

    @transport.event_handler("on_client_connected")
    async def on_connected(_: Any, __: Any) -> None:
        # The platform's `start` frame names the call language; wait briefly for it.
        for _ in range(40):
            if serializer.start_message is not None:
                break
            await asyncio.sleep(0.05)
        code = serializer.language
        context.messages[0]["content"] = SYSTEM_PROMPT.format(language_name=language_name(code))
        context.add_message({"role": "user", "content": "(the customer has answered the phone)"})
        await task.queue_frames([LLMRunFrame()])

    @transport.event_handler("on_client_disconnected")
    async def on_disconnected(_: Any, __: Any) -> None:
        await task.cancel()

    return task


def create_app(
    make_services: Callable[[PareekshaFrameSerializer], tuple[STTService, LLMService, TTSService]]
    | None = None,
    vad_factory: Callable[[], VADAnalyzer] | None = None,
) -> FastAPI:
    app = FastAPI(title="Pareeksha example Pipecat bot")

    @app.get("/health")
    async def health() -> JSONResponse:
        return JSONResponse({"status": "ok", "agent": "pipecat-emi-bot"})

    @app.websocket("/ws")
    async def call(websocket: WebSocket) -> None:
        await websocket.accept()
        serializer = PareekshaFrameSerializer()
        stt, llm, tts = (make_services or default_services)(serializer)
        task = build_task(
            websocket, stt, llm, tts, serializer, vad_factory() if vad_factory else None
        )
        runner = WorkerRunner(handle_sigint=False)
        await runner.add_workers(task)
        await runner.run()

    return app


def default_services(
    serializer: PareekshaFrameSerializer,
) -> tuple[STTService, LLMService, TTSService]:
    from speech_services import ProviderSTTService, ProviderTTSService

    from pareeksha.speech import get_stt_provider, get_tts_provider

    return (
        ProviderSTTService(get_stt_provider(), lambda: serializer.language),
        build_llm(),
        ProviderTTSService(get_tts_provider(), lambda: serializer.language, voice="Avinash"),
    )


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    uvicorn.run(create_app(), host="0.0.0.0", port=int(os.environ.get("PIPECAT_BOT_PORT", "8766")))
