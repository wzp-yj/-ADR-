# AIOS P1 Mobile Text Conversation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Deliver a usable ChatGPT-style Expo mobile client for persistent text conversations, retryable Turns, project clarification and memory-candidate decisions.

**Architecture:** The mobile app uses a small typed API client and a pure chat reducer. Server resources remain authoritative; the client creates a UUID before sending, renders an optimistic user message, then merges the returned Turn by IDs. API URL and last conversation ID are persisted locally, while voice remains an input adapter boundary.

**Tech Stack:** Expo 52, React Native 0.76, TypeScript 5.3, AsyncStorage, lucide-react-native, Jest Expo, React Native Testing Library.

**Design:** `docs/specs/2026-07-15-aios-p1-conversation-core-design.md` section 12.

**Status:** Completed and verified on 2026-07-15. Voice input remains the next independent milestone.

---

## Task 1: Mobile Recovery API Support

**Files:**

- Modify: `backend/app/conversation/service.py`
- Modify: `backend/app/api/memory.py`
- Modify: `backend/app/schemas/memory.py`
- Test: `backend/tests/api/test_conversations.py`
- Test: `backend/tests/api/test_memory_candidates.py`

- [ ] Write failing tests proving clarification messages persist candidate metadata and `GET /api/v1/memory-candidates?session_id=...&status=pending` returns only that conversation's pending candidates.
- [ ] Run the two API test modules and confirm the new assertions fail.
- [ ] Store `{type: "project_clarification", candidates: [...]}` in the clarification Assistant message metadata and add the filtered list endpoint.
- [ ] Run focused and full backend tests.
- [ ] Commit as `feat: expose mobile conversation recovery data`.

## Task 2: Mobile Dependencies And Typed API Client

**Files:**

- Modify: `mobile/package.json`
- Modify: `mobile/package-lock.json`
- Create: `mobile/src/api/types.ts`
- Create: `mobile/src/api/client.ts`
- Create: `mobile/src/api/client.test.ts`
- Create: `mobile/src/config.ts`
- Create: `mobile/.env.example`
- Modify: `mobile/tsconfig.json`

- [ ] Install Expo-compatible AsyncStorage, `lucide-react-native`, `react-native-svg`, Jest Expo and React Native Testing Library.
- [ ] Write failing tests for base URL normalization, stable API error parsing, conversation creation/listing, messages, Turn submission/retry and memory decisions.
- [ ] Implement `AIOSApiClient` with injected `fetch`, `X-Request-ID`, JSON/non-JSON handling and the exact backend contracts.
- [ ] Run mobile tests and TypeScript.
- [ ] Commit as `feat: add typed AIOS mobile API client`.

## Task 3: Optimistic Chat State

**Files:**

- Create: `mobile/src/chat/state.ts`
- Create: `mobile/src/chat/state.test.ts`

- [ ] Write failing reducer tests for message loading, optimistic append, successful ID merge, Provider failure, retry completion and deduplication.
- [ ] Implement a pure reducer whose pending message ID is the client message UUID and whose server merge replaces that temporary item without moving unrelated messages.
- [ ] Run reducer tests and TypeScript.
- [ ] Commit as `feat: model optimistic mobile chat state`.

## Task 4: Mobile Conversation Experience

**Files:**

- Replace: `mobile/App.tsx`
- Create: `mobile/src/components/ConversationDrawer.tsx`
- Create: `mobile/src/components/MessageBubble.tsx`
- Create: `mobile/src/components/MemoryCandidateBar.tsx`
- Create: `mobile/src/components/Composer.tsx`
- Create: `mobile/src/theme.ts`
- Create: `mobile/src/storage.ts`

- [ ] Implement startup loading: configured API URL, last conversation, conversation list, messages and pending memory candidates.
- [ ] Implement conversation drawer, new conversation, text composer, optimistic sending, failed Turn retry, project-candidate buttons and accept/reject memory actions.
- [ ] Keep the microphone icon visible but disabled with an accessibility label until the voice Provider milestone; do not create a second chat path.
- [ ] Add an API URL settings modal so a physical phone can use the computer's LAN address instead of `127.0.0.1`.
- [ ] Verify stable dimensions, keyboard avoidance, safe areas, loading/empty/error states and long text wrapping on narrow screens.
- [ ] Run mobile tests, TypeScript and Expo Doctor.
- [ ] Commit as `feat: build mobile text conversation experience`.

## Task 5: End-To-End Verification And Memory

**Files:**

- Modify: `docs/PROJECT_MEMORY.md`
- Modify: `docs/architecture/exec-architecture.html`

- [ ] Run backend tests and migration check.
- [ ] Run Web tests and production build.
- [ ] Run Mobile Jest, TypeScript, Expo configuration and Expo Doctor.
- [ ] Start current backend and Expo dev servers on available ports, verify live health and the mobile web bundle, and record URLs.
- [ ] Update project memory with exact counts, implemented boundaries and the next voice milestone.
- [ ] Commit as `docs: record mobile conversation milestone`.
