# PRD: AI Draft Copilot

## Vision

Give every fantasy manager a personal draft war room. During live or mock drafts on the StepByStepToolKit draft board, users open a chat panel and converse with an AI copilot that knows their roster, league settings, and real-time board state. Above the chat, a persistent "Best Available" bar highlights the top pick for their team right now — updating automatically as picks roll in. The copilot draws on ML projections (XGBoost + Ridge ensemble), positional scarcity analysis, and roster-need scoring to deliver recommendations that are specific to the user's league format, draft slot, and current roster composition.

## Target users

Fantasy football managers who use StepByStepToolKit to run their draft boards — ranging from casual owners who want "just tell me who to pick" to experienced players who want to debate strategy mid-draft.

## Success metrics

- **Adoption**: >30% of active draft sessions open the copilot at least once.
- **Engagement**: Average 3+ messages per copilot session.
- **Accuracy**: Copilot's #1 recommendation aligns with a defensible pick (per eval scenarios) >80% of the time.
- **Latency**: Recommendation response returns in <5 seconds for 90th percentile.

---

## User stories (MoSCoW)

### P0 — Must have

| # | Story | Value |
|---|-------|-------|
| S1 | As a user on the draft board, I can open a chat panel and type a message to the AI copilot so I can ask draft questions in natural language. | Core interaction model |
| S2 | As a user, I see the copilot's recommendation include a #1 pick, 2-3 alternatives, and a brief rationale tied to my roster needs and league format. | Core value proposition |
| S3 | As a user, I see a "Best Available" bar above the chat that shows the top recommended player for my team, updated automatically after each pick. | Glanceable decision support without needing to chat |
| S4 | As a user, the copilot knows my current roster, draft position, league size, scoring format, and roster slot configuration without me having to re-enter it. | Seamless context — no friction |
| S5 | As a user, the copilot factors in which players are still available on the board (not yet drafted) when making recommendations. | Recommendations must reflect real-time board state |
| S6 | As a user drafting in a Sleeper or ESPN league with live sync enabled, the copilot updates its recommendations automatically as new picks come in. | Live integration with existing sync polling |
| S7 | As a user, I can use the copilot during both live drafts and manual/mock drafts. | Works in all draft modes |

### P1 — Should have

| # | Story | Value |
|---|-------|-------|
| S8 | As a user, I can ask the copilot to compare two or more specific players side-by-side. | Common draft question |
| S9 | As a user, the copilot warns me about positional scarcity ("RBs are drying up — only 4 startable RBs left"). | Proactive strategic guidance |
| S10 | As a user, I see the copilot's responses stream in progressively (not all at once after a long wait). | Perceived performance and engagement |
| S11 | As a user, I can collapse/expand the copilot panel so it doesn't obscure the draft board when I don't need it. | Layout flexibility |

### P2 — Could have

| # | Story | Value |
|---|-------|-------|
| S12 | As a user, the copilot surfaces recent injury or depth chart news that affects its recommendation. | Risk-aware drafting |
| S13 | As a user, I can see a confidence indicator on recommendations (high/medium/low) based on model agreement. | Transparency |
| S14 | As a user, the copilot remembers my conversation history within a single draft session so I can refer back to earlier advice. | Continuity |

### Won't (this release)

| # | Story | Reason |
|---|-------|--------|
| W1 | Auto-draft: the copilot makes picks on my behalf. | High risk, low trust for v1 — recommendation only. |
| W2 | Cross-league copilot: advice that factors in my other leagues. | Scope creep; single-league context is hard enough. |
| W3 | Post-draft copilot chat (trade advice, waiver wire). | Separate feature; this PRD scopes to draft time only. |

---

## Assumptions & open questions

### Assumptions

1. **Existing ML models are sufficient.** The XGBoost + Ridge ensemble from AIAgent already produces VBD rankings and positional projections for the 2026 season. We will use these models as-is rather than retraining.
2. **Server-side AI orchestration.** The multi-agent pipeline (Coordinator → Roster → Value → Strategy → Projection → News) will run server-side on the Flask backend, not client-side. The existing Google ADK agent code will be adapted into Flask endpoints.
3. **Gemini API key availability.** The ADK agents use `gemini-2.5-flash`. We assume a valid API key is available in the deployment environment.
4. **Single concurrent draft per user.** A user only runs one draft at a time, so one copilot session per user is sufficient.
5. **Player projection data is pre-computed.** The pickle files with predictions are loaded at server start, not computed on-the-fly.

### Open questions

| # | Question | Impact | Recommended default |
|---|----------|--------|---------------------|
| Q1 | Should the copilot backend run as a separate service (FastAPI sidecar) or be embedded in the Flask app? | Architecture, deployment complexity, latency | Embed in Flask — avoids inter-service latency and deployment complexity. Port the agent logic as a Flask route that calls Gemini directly. |
| Q2 | Rate limiting: how many copilot requests per minute per user? | Cost (Gemini API calls), abuse prevention | 10 requests/minute per user. Each request runs the full 5-agent pipeline which makes multiple Gemini calls. |
| Q3 | Should the copilot work without an API key (degraded mode)? | UX for self-hosted users without a Gemini key | Yes — fall back to the existing rule-based `ai-suggest` logic (positional need + BPA) and show a banner: "AI Copilot requires API key configuration." |
| Q4 | Mobile layout: where does the chat panel go on small screens? | UX on phones/tablets | Reuse the existing mobile slide-up drawer — add a "Copilot" tab alongside "Available" and "Your Team". |
| Q5 | Do we ship the News agent (real-time web search) in v1? | Adds latency, requires Google Search API access | Ship it as P2 (Could have). Omit from the default pipeline to keep response times under 5s. |

---

## Risks

| Risk | Likelihood | Impact | Mitigation |
|------|-----------|--------|------------|
| **Gemini API latency spikes** cause copilot responses >10s | Medium | High — users lose trust and stop using it | Stream responses (S10). Set a 15s timeout with a friendly fallback ("I'm thinking hard — here's a quick suggestion based on your roster needs" + rule-based fallback). |
| **Gemini API cost** scales unexpectedly with heavy usage | Medium | Medium — operational cost | Rate limit (Q2). Use `gemini-2.5-flash` (cheapest). Cache identical board-state queries within a session. |
| **Stale model data** — pickle files not updated for new season | Low | High — wrong projections | Add a startup check that logs model season vs. current season. Surface a warning in the copilot UI if mismatched. |
| **Agent hallucination** — copilot recommends a player who's already drafted or doesn't exist | Low | High — erodes trust | Pre-filter available players server-side before passing to agents. Validate the recommended player name against the available list before returning to the client. |
| **Layout disruption** — copilot panel breaks existing board layout on various screen sizes | Medium | Medium — UX regression | Build copilot as a collapsible side panel (right side) that doesn't reflow the board. Test at 1024px, 1440px, and mobile breakpoints. |
| **Scope creep** — users expect post-draft advice, trade analysis, waiver wire help | High | Low — feature request, not failure | Clearly label as "Draft Copilot" and scope the UI to only appear during active drafts. Defer post-draft to W3. |

---

## Prioritization rationale

**Lens used: Value vs. Effort (MoSCoW)**

P0 stories (S1-S7) form the minimum viable copilot — without any one of them, the feature either doesn't function or delivers a broken experience. S4/S5/S6 in particular are what differentiate this from a generic ChatGPT window; the copilot must be contextually aware of the draft in progress.

P1 stories (S8-S11) significantly improve the experience but are not blockers. Streaming (S10) is borderline P0 for perceived performance but can be faked with a loading animation in v1 if needed.

P2 stories (S12-S13) add polish and depth but depend on additional API access (Google Search for news) and add latency.

**Launch risk flag:** S4 and S5 depend on resolving Q1 (architecture). If the agent pipeline cannot access draft board state efficiently, the entire feature's value collapses.

---

## Handoff

Ready for the **requirements-analyst** to decompose P0/P1 stories into testable acceptance criteria. Key inputs for that role:

- The existing `ai-suggest` endpoint already computes positional need scores, top targets, and best available — this is the rule-based baseline the copilot enhances.
- The AIAgent draft-copilot project at `/Users/kmaran3/Dropbox/Personal/AIAgent/draft-copilot/` contains the full agent definitions, tool implementations, and ML model loading code that will be ported.
- The draft board JS (`draft_board.js`) already has `fetchAISuggestions()` debounced after each pick — the copilot's "Best Available" bar should hook into the same trigger.
- Snake draft math, roster structures, and sync polling are all documented in the codebase and summarized above.
