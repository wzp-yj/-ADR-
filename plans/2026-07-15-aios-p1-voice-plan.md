# AIOS P1-C Voice Interaction Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver switchable cloud/local push-to-talk voice input and optional spoken replies without creating a second conversation path.

**Architecture:** Expo records a short audio file and creates a durable `VoiceTranscription`. A completed transcription is referenced by the existing Turn API, which persists a `kind=transcript` user message and runs the normal context, memory and LLM pipeline. TTS is a non-authoritative output adapter; failure leaves the text Turn unchanged.

**Tech Stack:** Python 3.12, FastAPI, PostgreSQL 16, SQLAlchemy async, Pydantic v2, OpenAI/httpx adapters, Expo 52, `expo-audio ~0.3.5`, `expo-file-system ~18.0.12`, TypeScript, Jest.

**Design:** `docs/specs/2026-07-15-aios-p1-voice-design.md`

---

## Task 1: Retry Memory Idempotency

**Files:**

- Modify: `backend/tests/conversation/test_service.py`
- Modify: `backend/app/conversation/service.py`

- [x] Add a regression test proving Provider retry keeps the original memory candidate ID.
- [x] Run the focused test and observe two candidates.
- [x] Skip extraction when the Turn already owns candidates and append `memory.extraction.skipped`.
- [x] Run `backend/tests/conversation/test_service.py` and confirm `11 passed`.
- [x] Run the full backend suite before committing the milestone.

## Task 2: Typed Voice Contracts And Routing

**Files:**

- Replace: `backend/app/voice/base.py`
- Modify: `backend/app/voice/__init__.py`
- Create: `backend/app/voice/router.py`
- Create: `backend/app/voice/dependencies.py`
- Modify: `backend/app/config.py`
- Modify: `backend/.env.example`
- Test: `backend/tests/voice/test_contracts.py`
- Test: `backend/tests/voice/test_router.py`

- [x] Write failing tests for STT/TTS request validation, response metadata, explicit/default routing and missing Provider errors.
- [x] Run `.venv\Scripts\python.exe -m pytest backend\tests\voice\test_contracts.py backend\tests\voice\test_router.py -q` and confirm failures are caused by missing typed contracts.
- [x] Add `AudioFormat`, `STTRequest/Response/Chunk`, `TTSRequest/Response/Chunk`, usage and segment models.
- [x] Implement separate STT/TTS maps in `VoiceRouter`; never silently fall back.
- [x] Add settings for defaults, Alibaba key/workspace/base URL/model/voice, local STT/TTS URL/model and request limits.
- [x] Run focused tests and type/import checks.

## Task 3: Cloud And Local Provider Adapters

**Files:**

- Create: `backend/app/voice/providers/__init__.py`
- Create: `backend/app/voice/providers/aliyun.py`
- Create: `backend/app/voice/providers/funasr.py`
- Create: `backend/app/voice/providers/cosyvoice.py`
- Test: `backend/tests/voice/test_aliyun_provider.py`
- Test: `backend/tests/voice/test_local_providers.py`

- [x] Write failing transport-injected tests for Alibaba Qwen-ASR Data URL payload and normalized response.
- [x] Write failing tests for Alibaba TTS request, binary/URL response handling and provider error mapping.
- [x] Write failing tests for FunASR multipart `/v1/audio/transcriptions` conversion.
- [x] Write failing tests for CosyVoice request conversion and explicit output audio metadata.
- [x] Implement adapters with injected OpenAI/httpx clients; no Provider SDK type may escape the module.
- [x] Map authentication/configuration errors to typed non-retryable errors and timeout/429/5xx to typed retryable errors.
- [x] Run all `backend/tests/voice` tests.

## Task 4: Durable Transcription Resource

**Files:**

- Create: `backend/app/models/voice.py`
- Modify: `backend/app/models/__init__.py`
- Create: `backend/alembic/versions/0003_create_voice_transcriptions.py`
- Create: `backend/app/schemas/voice.py`
- Create: `backend/app/voice/service.py`
- Create: `backend/app/api/voice.py`
- Modify: `backend/app/api/router.py`
- Modify: `backend/app/conversation/service.py`
- Modify: `backend/app/schemas/conversation.py`
- Modify: `backend/app/api/conversations.py`
- Test: `backend/tests/models/test_voice_models.py`
- Test: `backend/tests/api/test_voice.py`
- Test: `backend/tests/api/test_conversations.py`

- [x] Write failing model tests for status, size, SHA-256, `(session_id, client_audio_id)` uniqueness and one-Turn binding.
- [x] Write failing API tests for multipart validation, 10 MiB limit, Provider unavailable, successful persisted transcription and duplicate upload response.
- [x] Prove with a commit spy that the transcription resource commits before STT invocation.
- [x] Write failing Turn tests for completed transcript input, wrong session, failed/not-ready transcription and second-use conflict.
- [x] Add migration, model, schemas and `TranscriptionService`.
- [x] Extend `ConversationService.create_turn` with typed message kind/metadata and atomic transcription binding.
- [x] Add provider capability, transcription and speech endpoints with stable error contracts.
- [x] Run API/model tests, full backend tests and Alembic upgrade/downgrade/upgrade/check on the protected test database.

## Task 5: Mobile Voice Transport And Audio Adapter

**Files:**

- Modify: `mobile/package.json`
- Modify: `mobile/package-lock.json`
- Modify: `mobile/app.json`
- Modify: `mobile/src/api/types.ts`
- Modify: `mobile/src/api/client.ts`
- Modify: `mobile/src/api/client.test.ts`
- Create: `mobile/src/voice/types.ts`
- Create: `mobile/src/voice/recorder.ts`
- Create: `mobile/src/voice/player.ts`
- Create: `mobile/src/voice/recorder.test.ts`
- Create: `mobile/src/voice/player.test.ts`
- Modify: `mobile/test/setup.ts` or the existing Jest setup when required

- [x] Install SDK-compatible `expo-audio` and `expo-file-system` with `npx expo install`.
- [x] Add the `expo-audio` config plugin and Chinese microphone permission text; do not enable background recording.
- [x] Write failing API client tests for capability discovery, multipart transcription, transcript Turn and binary TTS.
- [x] Implement FormData requests without forcing JSON `Content-Type` so the runtime adds the multipart boundary.
- [x] Write failing recorder tests for permission rejection, prepare/start/stop, 300 ms minimum, 60 second maximum and retained retry URI.
- [x] Write failing player tests for cache write, stop-before-replace and cleanup.
- [x] Implement `expo-audio` only inside the recorder/player adapters.
- [x] Run mobile Jest and `npx tsc --noEmit`.

## Task 6: Mobile Push-To-Talk Experience

**Files:**

- Modify: `mobile/App.tsx`
- Modify: `mobile/src/components/Composer.tsx`
- Modify: `mobile/src/components/components.test.tsx`
- Create: `mobile/src/components/VoiceStatusBar.tsx`
- Create: `mobile/src/voice/state.ts`
- Create: `mobile/src/voice/state.test.ts`
- Modify: `mobile/src/theme.ts` only when a new semantic state color is needed

- [x] Write failing reducer tests for idle, permission, recording, transcribing, sending, synthesizing, playing, retry and cancel transitions.
- [x] Replace the disabled microphone with press-in/press-out recording while preserving stable composer dimensions.
- [x] Show concise recording/transcribing/playing states and retry/cancel commands; do not add instructional copy.
- [x] After transcription, call the existing optimistic Turn path with `kind=transcript`.
- [x] Auto-synthesize only Assistant responses to voice-originated Turns; TTS errors leave text visible.
- [x] Stop playback before recording and on conversation switch.
- [x] Keep text sending, project clarification, memory decisions and reload recovery unchanged.
- [x] Run component/reducer tests, full mobile Jest and TypeScript.

## Task 7: Verification, Runtime And Memory

**Files:**

- Modify: `docs/architecture/exec-architecture.html`
- Modify: `docs/PROJECT_MEMORY.md`
- Modify: `docs/development-environment.md`

- [x] Run full backend tests and migration check.
- [x] Run Web tests and production build.
- [x] Run Mobile Jest, TypeScript, `expo install --check`, Expo config, Expo Doctor and Web export.
- [x] Start backend and Expo on free ports; verify live/ready, capability discovery and the mobile bundle.
- [x] Verify `390x844` and a desktop Web viewport for idle, recording-unavailable, transcribing, failure/retry and text fallback without overlap.
- [x] Where credentials are absent, run the complete flow against an injected fake Provider and clearly record that Alibaba/local live calls remain credential/service dependent.
- [x] Update the execution architecture with Voice Router, transcription persistence and standard Turn reuse.
- [x] Update project memory with exact tests, migrations, runtime URLs, configured/unconfigured Provider status and the next execution-task milestone.
- [x] Commit the completed P1-C milestone.
