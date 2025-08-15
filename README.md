# AI AI Assistant (Monorepo)

This repository contains both the frontend and backend for an AI assistant built on LiveKit starters.

- `frontend`: Based on LiveKit Starter React (Next.js app)
- `backend`: Based on LiveKit Agent Starter Python

These projects were adapted from the original LiveKit example templates. See each subfolder for more details and per-service docs.

## Getting Started

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

## Attribution
This project leverages and adapts code from the LiveKit example templates.
- LiveKit Starter React
- LiveKit Agent Starter Python

Respect the licenses included within `frontend/LICENSE` and `backend/LICENSE`. 