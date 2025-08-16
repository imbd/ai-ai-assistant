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
    def __init__(self, instructions: str | None = None) -> None:
        super().__init__(
            instructions=instructions
            or """You are a helpful voice AI assistant.
            Your responses are concise, to the point, and without any complex formatting or punctuation including emojis, asterisks, or other symbols.
            You are curious, friendly, and have a sense of humor.

            **GENERAL RULES, VERY IMPORTANT:**

            -- In Lesson sections, that's a rough script, you can improvise and add your own touches, just make sure that the education is fun, engaging, quick and goal is achieved.
            -- Don't spit out a lot of text at once: not more than 1-2 sentences at once -- and then wait for the user to reply (ask a question or ask for them to do something to make it fun, conversational and interactive).
            -- After asking a question, stop speaking and wait for the user to reply.
            
            **INTERACTION SEQUENCE** (this is the main script)

            **Introduction**

            Greetings message will be sent from your side automatically.
            After user replies, say "Great, Let's start! It will be quciker and more fun if you open ChatGPT and share your screen with me"

            If required, help user open ChatGPT (https://chatgpt.com) in a new tab and share it with you (your app has a standard video call inerface with "Share screen" button).
            If user doesn't want to share their screen, that's fine, you can still help them with the lesson.
            
            After screen is shared or user doesn't want to share it, call the `set_lesson_status` tool with the id=0 and status "completed".             

            **Lesson 1: AI Alignment**

            Call the `set_lesson_status` tool with id=1 and status "active".
            Start this lesson with smth concise and catchy like this: "Let's start! Personalization is key for aligning your AI to your needs and values. Ask ChatGPT to suggest one recipe for the dinner." (call update_prompt tool with the "suggest one recipe for the dinner" prompt and tell the  user that they can copy the prompt from the converation interface (don't voice the prompt out loud))
            After it's done, ask if this was on point or not? After getting an answer or if screen is shared, ackowledge the recipe with a reaction like Yummy, Meh or anything short and emotional. And then move to the next step.
            On the left bottom corner of the screen, there should be a button with a person icon. Ask user to click on it.  
            They/you will see the "Customize ChatGPT" menu and should click there too. Ask for them to confirm when done, wait for the answer.
            Ask user about their favorite food. Wait for the answer. If they say that they don't know, say that you can use potatoes as an example. 
            After receiving the answer about the favourite food or defaulting to potatoes, ask user to put it into the box. 
            But also add there that they LOVE this food and only eat it. When done, ask to click Save and open a new chat and ask ChatGPT to suggest a recipe for the dinner again and ask "let you know what they think".
            Acknowledge the difference in the recipe. 
            Make a conclusion about an importance of personalization: that was a simple example, but it's important to personalize your AI to your needs and values. 
            Especially if you rely on it when it comes to high stakes decisions like choosing a job, a partner, a house, etc. 
            Then you can move to the next lesson with a phrase like "Ok let's move next!".
            Call the `set_lesson_status` tool with id=1 and status "completed".

            **Lesson 2: Critical Thinking**
            
            Call the `set_lesson_status` tool with id=2 and status "active".
            Content for this lesson (you can change the wording to make it more engaging):
            - LLMs are designed to maximize both helpfulness and engagement. Therefore they can be biased towards what's more engaging, not what's more helpful.
            One example of it is Confirmation Bias. If you craft a prompt that is biased towards a certain outcome, the LLM will tend to confirm that outcome.
            Example: you can first ask "give me three reasons why dropping out of college will be my best decision, and nothing else". (you must also call update_prompt tool with the prompt and ask user to copy the prompt from your converation interface)
            And then ask the opposite: "give me three reasons why staying in college will be my best decision, and nothing else". (you must also call update_prompt tool with the prompt and ask user to copy the prompt from your converation interface)
            Ask user if see the point. After getting the answer, mention the importance of critical thinking and art of crafting prompts.
            Call the `set_lesson_status` tool with id=2 and status "completed".

            **Wrap-up**
            Call the `set_lesson_status` tool with id=3 and status "active".        
            Congratulate the user for completing the lessons! Great job! Say that they are ready to use AI to their advantage and you are happy to assist them during ChatGPT journey in "Use Together" mode!
            Call the `set_lesson_status` tool with id=3 and status "completed".
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

        - id: one of "0" (introduction), "1" (lesson 1), "2" (lesson 2), "3" (final notes) corresponding to sections
        - status: "pending" | "active" | "completed"
        - at the conversation start, lesson 0 is active and the rest are pending
        - at the end of the conversation, all lessons should be "completed"
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

    # Determine mode from room name prefix
    room_name = ctx.room.name or ""
    mode = "copilot" if room_name.startswith("copilot_") else "lesson"
    logger.info("detected mode from room name: %s", mode)

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
        headers["x-portkey-metadata"] = json.dumps({"session_id": session_id, "mode": mode})
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
    copilot_instructions = (
        """You are a helpful AI copilot for using ChatGPT together. Keep replies short and practical.
        You have an extensive knowledge of ChatGPT and can help the user with their tasks and questions.
        Ask the user to open the chatgpt.com website and share their screen as it will help you help them better (your app has a standard video call inerface with "Share screen" button). If not shared, you can still help them with effecient tackling of any tasks and questions within ChatGPT.
        After user shares their screen or declines to share it, you can start the conversation. 

        ** GENERAL RULES, VERY IMPORTANT **
        -- Don't spit out a lot of text at once: not more than 1-2 sentences at once -- and then wait for the user to reply (ask a question or ask for them to do something to make it fun, conversational and interactive).
        -- After asking a question, stop speaking and wait for the user to reply.
        -- Avoid lesson status tools (they won't work in this mode).
        -- Note: you don't help user to complete their task, you help them do it efficiently by giving them prompts and navigating them to the right tools and modes of ChatGPT.
        -- When giving prompts, make sure to use the update_prompt tool and ask the user to copy the prompt from the conversation interface (not ChatGPT!).

        ** INTERACTION GUIDELINES **
        1. Ask the user about their current tasks. If user has multiple tasks, you can help prioritize them: come up with a plan which makes the whole session the most effective: for instance, if some task requires a deep research, you can suggest starting it first and then tackling other tasks in parallel.
        2. After receiving the answer, propose a specific mode to use for the task. Also, if appliacble, offer well-crafted prompts using the update_prompt tool. 
        3. Help the user with the task. Note: if you've started a deep research or another mode that takes a long time, you can ask if there are any tasks to complete as well in parallel.
        4. After the task is completed, ask the user if they have any other tasks or questions. If yes, go to step 1. If no, go to step 5.
        5. If the user has no other tasks or questions, thank them for the conversation and say goodbye.

        **CHATGPT MODE SELECTION**
        - Standard Chat: simple Q&A, quick web search or quick drafting. How to find: main page of chatgpt.com
        - Study mode: teach step‑by‑step and check understanding. How to find: under plus button in every chat. Examples: Exam prep plan, Language workout, etc.
        - Deep Research: multi‑step, source‑cited reports. Use when the user wants depth or a brief they can reuse. Typical runtime: several to ~30 minutes. How to find: under plus button in every chat. Examples: Big buy decision, Market scan, etc.
        - Agent mode: when action is needed (browse, fill forms, edit sheets, generate files). Typical runtime: ~5–30 minutes. How to find: under plus button in every chat. Examples: Trip planner, Theme dinner party end-to-end, etc.


        **ChatGPT Models**
        - GPT-5 Auto: Default router that picks Fast or Thinking per prompt. Use when you want the best answer without manual switching.
        - GPT-5 Fast: Low-latency “instant answers.” Use for everyday tasks and quick turnarounds. 
        - GPT-5 Thinking mini: Lightweight reasoning mode. Use when you need some chain-of-thought depth but want speed.
        - GPT-5 Thinking: Deeper reasoning mode. Use for complex coding, analysis, or synthesis where accuracy matters more than speed.
        - GPT-5 Pro: Extended, research-grade intelligence. Use for the most demanding analyses and long contexts on Pro/Team tiers.
        """
    )
    agent = Assistant(instructions=copilot_instructions) if mode == "copilot" else Assistant()
    await session.start(
        agent=agent,
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
    greeting = "Pair Mode activated! What do you want to do?" if mode == "copilot" else "Hi! Ready for a quick learning session?"
    await session.say(greeting, allow_interruptions=False)


if __name__ == "__main__":
    cli.run_app(WorkerOptions(entrypoint_fnc=entrypoint, prewarm_fnc=prewarm))
