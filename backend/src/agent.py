import logging
import base64
import os

from dotenv import load_dotenv
from livekit.agents import (
    NOT_GIVEN,
    Agent,
    AgentFalseInterruptionEvent,
    AgentSession,
    JobContext,
    JobProcess,
    MetricsCollectedEvent,
    RoomInputOptions,
    RunContext,
    WorkerOptions,
    cli,
    metrics,
    get_job_context,
)
from livekit.agents.llm import function_tool, ImageContent
from livekit.plugins import noise_cancellation, openai, silero
from livekit.plugins.turn_detector.multilingual import MultilingualModel
from livekit import rtc
import asyncio
import io
import httpx
import openai as openai_lib
from livekit.agents.utils.images import encode as lk_encode
from livekit.agents.utils.images import EncodeOptions as LKEncodeOptions, ResizeOptions as LKResizeOptions
import json
import uuid

logger = logging.getLogger("agent")

load_dotenv(".env")


class Assistant(Agent):
    def __init__(self) -> None:
        super().__init__(
            instructions="""You are a helpful voice AI assistant.
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.
            Do not solicit personal information. When asked about unknown private facts (e.g., the user's birthplace), say you don't know and do not ask them to share it.
            If user shares their screen, you will get a frame from it after each user turn.
            User will share their screen with you. Guide them through the following process:
            1. Open chatgpt.com in a new tab.
            2. Note their subscription plan based on the icon in the bottom left corner (Free, Plus or Pro).
            3. Ask them to click on the icon to see the "Customize ChatGPT" menu and click there.
            4. Then have a look at their custom instructions -- if not populated, give a few hints what to put there.
            5. After Custom Instructions are populated, return back to the chat and ask what they want to do. Help them choose the right mode based on the request: 
            -- "+" button + "Agent mode" if they want to get the best results and can wait for 5+ minutes.
            -- "+" button + "Web search" to make sure AI will use the latest information. Suggest to add "add citations" to the prompt.
            -- Suggest to add "Think hard" to the end of the prompt if they want to get a better answer.
            6. When you want to share a link or long text that should NOT be spoken aloud, call the `share_in_chat` tool with the content (and optional URL). Then speak briefly, e.g., "look in the chat, i've sent a link/text".

            INTERACTION SEQUENCE:

            -- In Lesson sections, that's a rough script, you can improvise and add your own touches, just make sure that the education is fun, engaging, quick and goal is achieved.
            -- Don't spit out a lot of text at once, make it fun, conversational and interactive.
            
            **Introduction**

            Greetings message will be sent from your side automatically.
            After user replies, say "Great, Let's start! It will be quciker and more fun if you open ChatGPT and share your screen with me"

            If required, help user open ChatGPT (https://chatgpt.com) in a new tab and share it with you (your app has a standard video call inerface with "Share screen" button).
            If user doesn't want to share their screen, that's fine, you can still help them with the lesson.
            
            After screen is shared or user doesn't want to share it, call the `set_lesson_status` tool with the introduction lesson id and status "complete". 
            Also, call the `set_lesson_status` tool with the lesson 1 id and status "active".

            **Lesson 1: Personalization**

            Start this lesson with smth concise and catchy like this: "Let's start! Personalization is key for aligning your AI to your needs and values. Ask ChatGPT to suggest one recipe for the dinner."
            After it's done, ask if this was on point or not? After that, move to the next step.
            On the left bottom corner of the screen, there should be a button with a person icon. Ask user to click on it.  They/you will see the "Customize ChatGPT" menu and should click there too. Ask for them to confirm when done, wait for the answer.
            Ask user about their favorite food. Wait for the answer. If they say that they don't know, say that you can use potatoes as an example. After receiving the answer about the favourite food or defaulting to potatoes, ask users to put it into the box. But also add that they LOVE this food and only eat it." When done, ask to open new chat and ask ChatGPT to suggest a recipe for the dinner again and ask "let you know what they think".
            Acknowledge the difference in the recipe. Make a conclusion about an importance of personalization: that was a simple example, but it's important to personalize your AI to your needs and values, especially if you rely on it when it comes to high stakes decisions like choosing a job, a partner, a house, etc. Then refer to the first recipe (not a personalized one) in a concise question like "Btw, do you know that you can only rely on Custom Instructions? Memory is not reliable from chat to chat. Ask in a new chat what was the first recipe?" Then you can move next lesson with a phrase like "Ok let's move next!".

            **Lesson 2: Safety**

            Improvise here. Make sure user understands that AI can hallucinate and make mistakes. That it's a powerful tool, but it's not perfect and should be used with caution.
            Give an interactive example (some concise prompt in a chat), and put an emphasis on the fact that high stakes decisions should be made with a human in the loop.
            """,
        )

    async def on_user_turn_completed(self, turn_ctx, new_message) -> None:
        # Attach the most recent screen frame (if any) to the new user message for vision-capable LLMs
        ctx = get_job_context()
        jpeg = ctx.proc.userdata.get("latest_screen_jpeg")
        if jpeg:
            data_url = "data:image/jpeg;base64," + base64.b64encode(jpeg).decode("utf-8")
            # Hint providers to use higher-detail vision when supported
            try:
                new_message.content.append(ImageContent(image=data_url, inference_detail="high"))
                logger.info("attached screen image to chat ctx: %d bytes", len(jpeg))
            except Exception:
                # Fallback without extra options if provider doesn't support inference_detail
                new_message.content.append(ImageContent(image=data_url))
                logger.info("attached screen image to chat ctx (basic): %d bytes", len(jpeg))
        await super().on_user_turn_completed(turn_ctx, new_message)

    @function_tool
    async def set_lesson_status(self, context: RunContext, id: str, status: str) -> str:
        """Update the frontend conversation status via the LiveKit data channel.

        - id: one of "0" (introduction), "1" (lesson 1), "2" (lesson 2), "3" (lesson 3), "4" (lesson 4) corresponding to sections
        - status: "pending" | "active" | "complete"
        - at the conversation start, lesson 0 is active and the rest are pending
        """
        ctx = get_job_context()
        payload = {"type": "lesson_status", "id": id, "status": status}
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                topic="lesson-status",
            )
            logger.info("published lesson status: %s", payload)
            return f"Updated lesson {id} to {status}."
        except Exception:
            logger.exception("failed to publish lesson status")
            return "Failed to update lesson status."

    @function_tool
    async def update_prompt(self, context: RunContext, text: str) -> str:
        """Set or update the suggested prompt shown in the UI.

        Sends a data message with type "prompt_update" and the latest prompt text.
        Call this multiple times as the prompt evolves.
        """
        ctx = get_job_context()
        payload = {"type": "prompt_update", "text": text}
        try:
            await ctx.room.local_participant.publish_data(
                json.dumps(payload).encode("utf-8"),
                topic="prompt-update",
            )
            logger.info("published prompt update: %s", {"len": len(text)})
            return "Prompt updated."
        except Exception:
            logger.exception("failed to publish prompt update")
            return "Failed to update prompt."


def prewarm(proc: JobProcess):
    proc.userdata["vad"] = silero.VAD.load()


async def entrypoint(ctx: JobContext):
    # Logging setup
    # Add any other context you want in all log entries here
    ctx.log_context_fields = {
        "room": ctx.room.name,
    }

    # Per-conversation session id for tracing/Portkey metadata
    session_id = uuid.uuid4().hex
    ctx.proc.userdata["session_id"] = session_id
    logger.info("new session started: session_id=%s", session_id)

    # Set up a voice AI pipeline. If PORTKEY_API_KEY is set, route LLM via Portkey.
    portkey_api_key = os.getenv("PORTKEY_API_KEY")
    if portkey_api_key:
        portkey_model = os.getenv("PORTKEY_LLM_MODEL", "gpt-4o")
        portkey_base_url = os.getenv("PORTKEY_BASE_URL", "https://api.portkey.ai/v1")
        headers = {}
        provider = os.getenv("PORTKEY_PROVIDER")
        config_id = os.getenv("PORTKEY_CONFIG")
        if provider:
            headers["x-portkey-provider"] = provider
        if config_id:
            headers["x-portkey-config"] = config_id
        upstream_openai = os.getenv("PORTKEY_UPSTREAM_OPENAI_API_KEY")
        if upstream_openai:
            headers["x-portkey-openai-api-key"] = upstream_openai
        # Attach Portkey metadata: include session_id so requests can be grouped per conversation
        headers["x-portkey-metadata"] = json.dumps({"session_id": session_id})
        # Build a custom AsyncClient so we can inject Portkey headers
        http_client = httpx.AsyncClient(
            timeout=httpx.Timeout(connect=15.0, read=5.0, write=5.0, pool=5.0),
            follow_redirects=True,
            limits=httpx.Limits(max_connections=50, max_keepalive_connections=50, keepalive_expiry=120),
            headers=headers or None,
        )
        # Portkey expects x-portkey-api-key in headers; do not send as Authorization
        http_client.headers["x-portkey-api-key"] = portkey_api_key
        # If user provided a virtual key slug, set both accepted headers
        vkey = os.getenv("PORTKEY_VIRTUAL_KEY")
        if vkey:
            #if not vkey.startswith("@"):
            #    vkey = "@" + vkey
            http_client.headers.setdefault("x-portkey-provider", vkey)
            http_client.headers.setdefault("x-portkey-virtual-key", vkey)
        oa_client = openai_lib.AsyncClient(api_key=None, base_url=portkey_base_url, http_client=http_client)
        llm_client = openai.LLM(model=portkey_model, client=oa_client)
        logger.info("Portkey enabled: model=%s base_url=%s provider=%s config=%s", portkey_model, portkey_base_url, bool(provider or vkey), bool(config_id))
    else:
        llm_client = openai.LLM(model="gpt-4o-mini")
        logger.info("Portkey disabled; using direct OpenAI model=%s", "gpt-4o-mini")

    session = AgentSession(
        # A Large Language Model (LLM) is your agent's brain, processing user input and generating a response
        # See all providers at https://docs.livekit.io/agents/integrations/llm/
        llm=llm_client,
        # Speech-to-text (STT) is your agent's ears, turning the user's speech into text that the LLM can understand
        # See all providers at https://docs.livekit.io/agents/integrations/stt/
        stt=openai.STT(model="gpt-4o-transcribe"),
        # Text-to-speech (TTS) is your agent's voice, turning the LLM's text into speech that the user can hear
        # See all providers at https://docs.livekit.io/agents/integrations/tts/
        tts=openai.TTS(voice="echo"),
        # VAD and turn detection are used to determine when the user is speaking and when the agent should respond
        # See more at https://docs.livekit.io/agents/build/turns
        turn_detection=MultilingualModel(),
        vad=ctx.proc.userdata["vad"],
        # allow the LLM to generate a response while waiting for the end of turn
        # See more at https://docs.livekit.io/agents/build/audio/#preemptive-generation
        preemptive_generation=False,
        userdata=ctx.proc.userdata,  # share process userdata with tools
    )
    
    # To use a realtime model instead of a voice pipeline, use the following session setup instead:
    # session = AgentSession(
    #     # See all providers at https://docs.livekit.io/agents/integrations/realtime/
    #     llm=openai.realtime.RealtimeModel()
    # )

    # sometimes background noise could interrupt the agent session, these are considered false positive interruptions
    # when it's detected, you may resume the agent's speech
    @session.on("agent_false_interruption")
    def _on_agent_false_interruption(ev: AgentFalseInterruptionEvent):
        logger.info("false positive interruption, resuming")
        session.generate_reply(instructions=ev.extra_instructions or NOT_GIVEN)

    # Metrics collection, to measure pipeline performance
    # For more information, see https://docs.livekit.io/agents/build/metrics/
    usage_collector = metrics.UsageCollector()

    @session.on("metrics_collected")
    def _on_metrics_collected(ev: MetricsCollectedEvent):
        metrics.log_metrics(ev.metrics)
        usage_collector.collect(ev.metrics)

    async def log_usage():
        summary = usage_collector.get_summary()
        logger.info(f"Usage: {summary}")

    ctx.add_shutdown_callback(log_usage)

    # Subscribe to screen-share video and keep latest JPEG in process userdata
    @ctx.room.on("track_subscribed")
    def _on_track_subscribed(track: rtc.RemoteTrack, publication: rtc.RemoteTrackPublication, participant: rtc.RemoteParticipant):
        try:
            is_video = isinstance(track, rtc.RemoteVideoTrack)
            # Capture any remote video track; frontend publishes screen as a video track
            if is_video:
                if not ctx.proc.userdata.get("_screen_capture_started"):
                    ctx.proc.userdata["_screen_capture_started"] = True
                    logger.info("video track subscribed; starting frame capture (treating as screen share)")
                    asyncio.create_task(_capture_screen_frames(ctx, track))
                else:
                    logger.info("video track subscribed; capture already running, ignoring additional track")
        except Exception:
            logger.exception("error handling track_subscribed")

    async def _capture_screen_frames(ctx: JobContext, video_track: rtc.RemoteVideoTrack):
        stream = rtc.VideoStream(video_track)
        # sample frames at a modest rate to avoid overhead
        async for frame in stream:
            try:
                jpeg_bytes = None

                # One-time diagnostics on first frame
                if not ctx.proc.userdata.get("_frame_diag_logged"):
                    try:
                        event_type = type(frame).__name__
                        frame_obj = getattr(frame, "frame", frame)
                        caps = {
                            "event_type": event_type,
                            "frame_type": type(frame_obj).__name__,
                        }
                        logger.info("video frame capabilities: %s", caps)
                    except Exception:
                        logger.debug("failed to log frame capabilities", exc_info=True)
                    finally:
                        ctx.proc.userdata["_frame_diag_logged"] = True

                # Unwrap frame if this is an event wrapper
                frame_obj = getattr(frame, "frame", frame)

                # Use LiveKit images.encode utility to JPEG-encode the frame
                try:
                    # Resize to 1024x1024 (fit) to improve OCR/vision robustness
                    jpeg_bytes = lk_encode(
                        frame_obj,
                        LKEncodeOptions(
                            format="JPEG",
                            resize_options=LKResizeOptions(width=1024, height=1024, strategy="scale_aspect_fit"),
                        ),
                    )
                except Exception:
                    logger.debug("images.encode failed", exc_info=True)

                if jpeg_bytes:
                    ctx.proc.userdata["latest_screen_jpeg"] = jpeg_bytes
                    logger.info("captured screen frame: %d bytes", len(jpeg_bytes))
                else:
                    logger.debug("frame conversion produced no bytes; waiting for next frame")
            except Exception:
                logger.exception("failed to convert video frame to JPEG")

    # # Add a virtual avatar to the session, if desired
    # # For other providers, see https://docs.livekit.io/agents/integrations/avatar/
    # avatar = hedra.AvatarSession(
    #   avatar_id="...",  # See https://docs.livekit.io/agents/integrations/avatar/hedra
    # )
    # # Start the avatar and wait for it to join
    # await avatar.start(session, room=ctx.room)

    # Start the session, which initializes the voice pipeline and warms up the models
    await session.start(
        agent=Assistant(),
        room=ctx.room,
        room_input_options=RoomInputOptions(
            # LiveKit Cloud enhanced noise cancellation
            # - If self-hosting, omit this parameter
            # - For telephony applications, use `BVCTelephony` for best results
            noise_cancellation=noise_cancellation.BVC(),
        ),
    )

    # Join the room and connect to the user
    await ctx.connect()

    # Proactive greeting at session start
    await session.say("Hi! Ready?", allow_interruptions=False)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
