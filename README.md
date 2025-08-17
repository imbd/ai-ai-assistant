https://ai-ai-assistant.vercel.app/

# ChatGPT Copilot

Equipped with up‑to‑date knowledge of the ChatGPT interface and features, this assistant helps you use ChatGPT efficiently!

## Modes

- **Pair Mode (Copilot)**: Practical “pairing” for doing tasks together in ChatGPT. The assistant suggests modes and prompts. Screen sharing is supported and recommended.

- **Lesson mode**: Guided, lightweight curriculum that teaches AI usage. The assistant updates lesson progress and shares short, copyable prompts during the session. Screen sharing is supported and recommended.

## Demo videos

- Pair mode (Copilot): [link pending]
- Lesson mode: [link pending]


## Getting Started

This repository contains both the frontend and backend for an AI assistant built on LiveKit starters.

- `frontend`: Based on LiveKit Starter React (Next.js app)
- `backend`: Based on LiveKit Agent Starter Python

These projects were adapted from the original LiveKit example templates. See each subfolder for more details and per-service docs.

## Stack & voice pipeline

- **LLM**: OpenAI (`gpt-4.1` by default)
- **STT**: OpenAI (`gpt-4o-transcribe`)
- **TTS**: OpenAI (voice `echo`)
- **Portkey (optional)**: Used only as a gateway for routing/observability/visibility. When configured, LLM traffic is routed via Portkey; otherwise the app talks directly to OpenAI. No other STT/TTS providers are used.

Defaults are configurable via environment variables.

### Backend (Python)
- Requirements: Python 3.11+, `uv`, or `pip`
- Install and run tests:
  ```bash
  cd backend
  uv venv || python3 -m venv .venv
  source .venv/bin/activate
  uv pip install -e . || pip install -e .
  pytest -q
  ```
- Run locally:
  ```bash
  task dev
  ```

### Frontend (Next.js)
- Requirements: Node 18+, `pnpm`
- Install and run:
  ```bash
  cd frontend
  pnpm install
  pnpm dev
  ```

## Environment
Copy and configure environment variables as needed:
- Frontend: copy `frontend/.env.example` to `frontend/.env.local`
- Backend: create `.env` in `backend/` based on service requirements
- Backend: requires `OPENAI_API_KEY`; Portkey (`PORTKEY_*`) is optional for LLM routing/visibility

## Attribution
This project leverages and adapts code from the LiveKit example templates.
- LiveKit Starter React
- LiveKit Agent Starter Python

Respect the licenses included within `frontend/LICENSE` and `backend/LICENSE`. 