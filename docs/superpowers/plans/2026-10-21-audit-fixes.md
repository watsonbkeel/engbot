# Eng Audit Fixes Implementation Plan

> **For agentic workers:** Use superpowers:subagent-driven-development or executing-plans; tests precede behavior changes.

**Goal:** Deliver a corrected deployable ZIP and verified full-path tests.
**Architecture:** Keep public Store / student Tutor / Pi edge separation. One canonical miniprogram source. Add explicit contracts, durable turn recovery, and supported v3 flows.
**Tech Stack:** Python 3.11+, FastAPI/Pydantic/SQLite/HTTPX, Node tests for WeChat JS, ffmpeg/Edge TTS.
**Spec:** ../specs/2026-10-21-audit-fixes.md; ../../REQUIREMENTS_V3.md.

## Global Constraints
- No deployments, production credentials or mock providers in production.
- Use original WordMaster dictionary only; retain word IDs and historical maximum status.
- Current deployment is one student per service, no multiuser redesign.
- Field names and enums match REQUIREMENTS_V3 exactly; scene goal max200, generated max180; scene rounds6/8/10; listening9 grades x >=5, >=2 story/dialogue,60–180s.
- Tests involving models/ASR use clearly marked substitutes. Real-device claims require real evidence.

## Review Focus
- Delayed replies and requests from previous question never change current records.
- Partial commits and brain restarts replay the first decision, no duplicate evidence.
- Missing/malformed provider content and expired credentials have visible failures.
- Leaving pages while asynchronous calls finish causes no stale changes or audio.
- Help and answer echoes never count as independent production; end feedback preserved.

## Task 1: Shared contracts and public routes (root)
Files models.py, store.py, public_api.py; new scene_prompts.py/status.py/listening.py; tests/test_v3_public.py.
- [ ] Add failing tests for v3 config roundtrip, thinking migration, roles, daily scene limit, source prompts, status and protected listening audio.
- [ ] Run and record red results.
- [ ] Implement strict contracts + additive schema migrations + public features.
- [ ] Test malformed responses, traversal, background probe cancellation and original suite.

## Task 2: Learner state machine (learner_experience)
Files engine.py, prompts/scenes.md/student.md, tests/test_engine.py and tests/test_v3_learning.py.
- [ ] Reproduce faulty help/ending/imitation/evidence with regression assertions.
- [ ] Implement four modes, scene opening/rounds/review, contextual help and honest evidence.
- [ ] Protect resumes against transition failure; use engine/public journal boundary agreed with engineering.
- [ ] Run learning tests and hand over diff + results.

## Task 3: Reliable voice/provider boundary (engineering_audit)
Files brain_api.py, client.py, providers.py, pi/audio.py, pi/english_voice.py, new turn recovery module; tests/test_v3_reliability.py and related existing tests.
- [ ] Add regressions for lost response, stable replay after partial commit, malformed LLM, DNS timeout, Vosk cold initialization, legacy event ID.
- [ ] Implement server question version + Pi recovery, durable pending-turn recovery, protocol validation, grade speed and thinking, independent idle heartbeat.
- [ ] Run focused tests and coordinate API fields with root.

## Task 4: Shipped UI and listening assets (product_audit)
Files miniprogram/, tests_js/, scripts/build_miniprogram.py, scripts/make_listening.py, data/listening/*, docs/LISTENING.md.
- [ ] Add failing real-page-event tests for saving, bad connections, drafts, filtering, errors and late download.
- [ ] Repair canonical six-page app; no credentials; build standalone output from canonical source.
- [ ] Supply45 age-appropriate curated passages/dialogues plus real MP3 generation, resume and duration checks; attempt real Edge TTS with no user secrets.
- [ ] Verify actual shipped page logic, script syntax and audio manifests.

## Task 5: Integration and delivery (root + cross review)
- [ ] Original suite + new full HTTP flows + original audit scenarios turned into corrected-behavior tests.
- [ ] Independent code/spec review; fix blocking findings and rerun relevant tests.
- [ ] Refresh API/design/install/test documentation, upgrade/backup instructions and package checksums.
- [ ] Scan no actual credentials/caches; unzip and validate final ZIP; save deliverable.
