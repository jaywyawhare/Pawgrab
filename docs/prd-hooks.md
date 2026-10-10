# PRD — Pawgrab Hooks (working title)

_Status: Draft · Owner: @jaywyawhare · Updated 2026-10-11_

A product layer on top of the Pawgrab scraping engine that (1) harvests high-performing
posts from LinkedIn, Reddit and X, (2) extracts and scores the **hook lines** that are
actually driving engagement, (3) helps users write AEO/GEO-optimized posts using those
hooks, and (4) schedules and publishes them.

## 1. Summary

Short-form social growth is bottlenecked by the first line. The hook decides whether a
post is read. Pawgrab Hooks turns Pawgrab's scraping + extraction + scheduling stack into
an end-to-end "research → write → optimize → schedule" loop: find hooks that work right
now in your niche, generate post variants built around them, optimize the post so it is
also quotable by AI answer engines (AEO/GEO), and schedule it to the right platform.

## 2. Problem

- Writing a strong hook is the highest-leverage, lowest-reliability step in social posting.
- "Swipe files" of hooks go stale and are not niche- or platform-specific.
- No tool closes the loop from *what is working now* → *a drafted, optimized, scheduled post*.
- Separately, content is increasingly discovered through AI answers, so a post should be
  written to be both human-scroll-stopping and AI-quotable.

## 3. Goals & non-goals

### Goals
- G1: Surface the top-performing hook patterns for a given niche/keyword/subreddit, refreshed on a schedule.
- G2: Quantify *why* a hook works (engagement-normalized score + pattern tags), not just list posts.
- G3: Generate post drafts around a chosen hook, tuned per platform (LinkedIn / Reddit / X).
- G4: Apply AEO/GEO best practice to each draft so it is answer-first and quotable.
- G5: Schedule and publish (or export) posts, with a content calendar.

### Non-goals (v1)
- Not a full social CRM, DM automation, or ads manager.
- No engagement-pod / fake-engagement features.
- No guarantee of bypassing any platform's terms; see Risks.
- Not a general analytics suite for your own account (v2 candidate).

## 4. Target users

| Persona | Need | Primary surface |
| --- | --- | --- |
| Founder / solo builder | Grow reach without a ghostwriter | LinkedIn, X |
| Content marketer | Repeatable hook research + calendar | All three |
| Agency / ghostwriter | Hooks per client niche, bulk scheduling | LinkedIn, X |
| Community/dev-rel | Find resonant angles in subreddits | Reddit |

## 5. How it builds on Pawgrab (reuse, don't rebuild)

| Capability | Existing Pawgrab module | Use in this product |
| --- | --- | --- |
| Fetch + anti-bot + proxy rotation | `engine/fetcher.py`, `engine/antibot.py`, `engine/proxy_pool.py` | Reach source platforms reliably |
| Reddit ingestion | `engine/reddit.py`, `api/reddit.py` | Primary Reddit harvester |
| Search / discovery | `api/search.py`, `engine/search_provider.py` | Find candidate posts by keyword |
| Crawl + pagination | `api/crawl.py`, `engine/pagination.py` | Walk feeds / profiles / search pages |
| AI extraction | `pawgrab/ai/*`, `api/extract.py` | Structured extraction of post fields |
| Hooks primitive | `engine/hooks.py` | Hook-line detection/segmentation |
| Analytics | `engine/analytics.py` | Engagement normalization/scoring |
| Scheduler | `engine/scheduler.py`, `api/schedule.py`, `models/schedule.py` | Scheduled harvesting **and** post publishing |
| Job queue | `pawgrab/queue/*` (arq + Redis) | Async harvest/score/publish jobs |
| MCP server | `pawgrab/mcp/*` | Expose hook research as agent tools |

New components to add: source adapters (LinkedIn, X), hook scorer, post generator (AEO/GEO),
publisher adapters, and a web app/calendar UI (the repo already has a `dashboard/`).

## 6. Scope

### 6.1 Hook harvesting
- Input: niche keywords, hashtags, subreddits, profiles, or a seed URL.
- Output: normalized post records — author, text, hook line, timestamp, metrics (likes,
  comments, reposts, views where available), permalink.
- Sources, by access tier:
  - **Reddit** — official API preferred; Pawgrab `reddit` engine as fallback. (Lowest friction.)
  - **X** — official API tier where budget allows; otherwise scrape within ToS/legal review.
  - **LinkedIn** — hardest; start with public post URLs/search, flag ToS risk (see Risks).
- Refresh: scheduled harvest jobs per saved query (reuse scheduler + queue).

### 6.2 Hook extraction & scoring
- Extract the hook = first line / opening unit of each post (via `hooks.py` + AI fallback).
- Normalize engagement across post age and author follower count → an **engagement-rate
  score**, not raw likes (avoid big-account bias).
- Tag hook **patterns**: question, contrarian take, listicle promise, stat/number, story
  open, "how I/we", callout, curiosity gap, etc.
- Rank hooks per niche + platform; show pattern-level aggregates ("stat-led hooks
  outperform question hooks by X% in r/SaaS this week").

### 6.3 AEO/GEO post optimization
- Rewrite/generate the post so it is answer-first and quotable (see repo AEO notes in
  `~/dev/personal/aeo/`): direct claim up top, a concrete number + source, scannable
  structure, clear entity identity.
- Platform-tuned length/format (X thread vs LinkedIn vs Reddit).
- Optional: emit a companion long-form/blog version with schema + llms.txt-friendly
  structure for the user's own site, so social + AI-search reinforce each other.

### 6.4 Compose, schedule, publish
- Post composer with hook picker, variant generator (3–5 variants), and preview per platform.
- Content calendar; schedule via existing scheduler.
- Publishing: start with **draft export + manual/API publish** where platform APIs allow;
  full auto-publish gated on API access and ToS per platform.

### 6.5 v2+ candidates
- Own-account performance tracking + feedback loop into the scorer.
- A/B hook testing; best-time-to-post model; team workspaces; browser-extension capture.

## 7. Key user flows

1. **Research:** user enters niche → saved query → harvest job → ranked hook library.
2. **Compose:** pick a hook/pattern → generate variants → AEO/GEO optimize → preview.
3. **Schedule:** place on calendar → scheduler queues → publish/export at time.
4. **Learn (v2):** published post metrics flow back → refine scoring for that user's niche.

## 8. Data model (first pass)

- `Source` — platform, query definition, schedule.
- `Post` — raw harvested post (author, text, metrics, permalink, fetched_at).
- `Hook` — hook_text, pattern_tags[], parent Post, engagement_score, platform, niche.
- `Draft` — body, platform, hook_id, variants[], aeo_score, status.
- `ScheduledPost` — draft_id, platform account, run_at, state (reuse `models/schedule.py`).
- `Account` — connected platform credentials/tokens (encrypted).

## 9. Architecture

```
          ┌──────────── saved queries ────────────┐
          ▼                                        │
Source adapters (reddit/x/linkedin)  ──►  harvest jobs (arq+Redis)
          │  reuse fetcher/antibot/proxy/search     │
          ▼                                         │
   Post store  ──►  Hook extractor (hooks.py + AI)  ──►  Scorer (analytics)
                                                         │
                         Hook library / API / MCP  ◄─────┘
                                                         │
   Composer + AEO/GEO optimizer (ai/*)  ◄───────────────┘
          │
          ▼
   Scheduler (scheduler.py) ──► Publisher adapters ──► platforms / export
          │
          ▼
   Web dashboard (dashboard/) : library, composer, calendar
```

## 10. Success metrics

- Activation: % of new users who harvest ≥1 query and save ≥1 hook in week 1.
- Core value: # posts scheduled/published per active user per week.
- Quality: user-rated hook relevance; lift in engagement rate of posts using suggested
  hooks vs the user's baseline.
- Retention: week-4 retention of users who scheduled ≥3 posts.

## 11. Risks & mitigations

| Risk | Severity | Mitigation |
| --- | --- | --- |
| LinkedIn/X scraping violates ToS; legal exposure | High | Prefer official APIs; legal review before any scraping path; honor robots; rate-limit; store only what's needed; make scraping sources opt-in and region-aware |
| Anti-bot blocking / account bans on publish | High | Use official publishing APIs; never automate from a user's logged-in scrape session; separate read vs write paths |
| Platform API cost/limits (esp. X) | Medium | Tiered sources; cache; batch; let users bring their own API keys |
| Engagement data is partial/estimated | Medium | Normalize + label metrics as measured vs estimated; never fabricate |
| "Hook that worked" ≠ "hook that works for you" | Medium | Niche + recency filters; show pattern-level guidance, not blind copy; v2 personalization |
| AEO/GEO claims over-promised | Low | Tie to the evidence-based playbook; label vendor stats directional |
| PII / creator content handling | Medium | Store public data only; honor deletion/opt-out; no private messages |

## 12. Milestones

| Phase | Deliverable |
| --- | --- |
| M0 — spike | Reddit harvest → hook extraction → scored library (one niche), via existing modules |
| M1 — MVP | Saved queries + scheduled harvest, hook library UI, composer with AEO/GEO optimize, manual export |
| M2 — scheduling | Calendar + scheduler-driven publish/export; Reddit + X (API) sources |
| M3 — LinkedIn + publish | LinkedIn source (post-legal-review), publisher adapters, accounts |
| M4 — learning loop | Own-account metrics feedback, A/B hooks, best-time model |

## 13. Open questions

- Which platform is the wedge for v1 — Reddit (lowest friction) or LinkedIn (highest demand)?
- Official APIs vs scraping per platform — what's the legal/budget line we will and won't cross?
- Pricing model: per-seat SaaS, usage-based (harvest/generate credits), or BYO-API-key?
- Where does the UI live — extend `dashboard/`, or a separate web app consuming the API?
- Hook scoring: start heuristic, or train on harvested data from day one?
```

> Related: AEO/GEO method and the $0 playbook live in `~/dev/personal/aeo/` — reuse that for the optimization step.
