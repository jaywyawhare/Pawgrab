# CloakBrowser Feature Parity — Plan / Middle State

Branch: `fix/extraction-and-antibot` · Local only (not pushed) · 765 tests passing

Goal: implement all CloakBrowser anti-bot features into Pawgrab's engine.

---

## Commits (local)

| SHA | Message |
|-----|---------|
| `f12fb16` | antibot: cloakbrowser-style seeded fingerprints, geoip proxy coherence, and human input emulation |
| `9acb40f` | antibot: seed the shared browser context from one coherent fingerprint profile |

---

## Done

### New modules

- **`pawgrab/engine/fingerprint.py`** — CloakBrowser `--fingerprint=seed`.
  `build_profile(seed)` draws one *coherent* Safari/macOS identity from a single
  seeded RNG: viewport ↔ screen ↔ GPU ↔ hardware_concurrency ↔ device_memory ↔
  UA ↔ timezone ↔ locale. Non-zero seed = stable identity across runs; `0`/`None`
  = fresh random (range 10000–99999, matching CloakBrowser). String seeds
  (e.g. `session_id`) hash deterministically.

- **`pawgrab/engine/geoip.py`** — CloakBrowser `geoip=True`.
  `resolve_proxy_geo(proxy)` makes one curl_cffi call *through the proxy* to
  ip-api.com → aligns browser timezone / locale / geolocation / Accept-Language
  to the proxy exit IP. Cached per-proxy (1 h TTL), lock-guarded, best-effort
  (returns `None` on failure so a fetch never blocks). Country→locale table keeps
  language plausible (e.g. BR keeps en-US primary but offers pt-BR).

- **`pawgrab/engine/humanize.py`** — CloakBrowser `humanize=True`.
  `human_move` (cubic-Bézier path + ease-in-out + overshoot), `human_click`
  (move → down → hold → up), `human_type` (per-char delays, self-correcting
  typos, thinking pauses), `human_scroll` (accelerate→cruise→decelerate wheel).
  All degrade gracefully to the plain call on any Playwright error.

### Wiring (`browser.py`, `fetcher.py`)

- `_build_evasion_script(profile=...)` — injected JS GPU/hw values now come from
  the profile (agrees with the context viewport/timezone/UA). Old signature kept.
- `_context_kwargs(profile=..., geo=...)` — uses the coherent profile; a resolved
  `ProxyGeo` overrides timezone/locale/Accept-Language/geolocation (proxy IP wins).
- `_new_stealth_page` — builds a profile, resolves proxy geo for proxied contexts.
- `acquire_session_page` — profile seeded from `session_id` (stable per session).
- `start()` — shared persistent context seeded from one coherent profile.
- CF Turnstile click routed through `human_click` when humanize on.
- `_execute_actions` CLICK/TYPE routed through `human_click`/`human_type`.
- `scroll_to_bottom` uses `human_scroll` when humanize on.

### Config (`config.py`) — all default-on

`humanize_interactions`, `geoip_coherence`, `geoip_timeout_seconds` (5.0),
`fingerprint_seed` (0 = random).

### Tests (+40)

- `tests/test_fingerprint.py` — determinism, seed range, hw↔GPU coherence,
  tz↔locale coherence, Safari/macOS identity, Pro/Max memory.
- `tests/test_geoip.py` — disabled/no-proxy paths, tz+locale resolution, BR
  Portuguese, caching (one session per proxy), fail-status + exception → None.
- `tests/test_humanize.py` — Bézier endpoints, curve sampling, press/release,
  per-char typing, fallbacks to click/fill/JS-scroll.
- `tests/test_engine_browser.py` — evasion script honors profile; `_context_kwargs`
  uses profile; geo overrides profile timezone/Accept-Language/geolocation.
- `tests/test_page_actions.py` — humanize-off dispatch + new humanized CLICK/TYPE.

### Already present before this work (no change needed)

Canvas/WebGL/audio noise · `navigator.webdriver=false` + CDP signal removal ·
WebRTC leak prevention (forced proxied-only UDP → WebRTC candidate already *is*
the proxy IP) · SOCKS5 + HTTP proxy · persistent contexts · curl_cffi Safari
TLS impersonation (JA3/JA4).

---

## The one irreducible gap (cannot implement in code)

CloakBrowser ships a **recompiled Chromium binary — 66 C++ source-level patches**.
Fingerprints baked in at compile time have no JS-injection seam. Pawgrab uses
Patchright *runtime JS stealth*, which is structurally one tier below and always
will be (property-descriptor tells, `Function.prototype.toString` leaks, timing).

Closing this means swapping the browser **binary**, not writing more Python. It is
the same infra-bound ceiling already documented for CF-solving and fetch coverage —
code changes do not cross it.

**Update — the connect seam is now built.** `PAWGRAB_BROWSER_CDP_URL` makes the pool
`connect_over_cdp` to an externally-run patched Chromium (e.g. CloakBrowser) instead
of launching Patchright locally; every request then runs through a fresh context on
that browser with Pawgrab's JS stealth + seeded fingerprint layered on top. This does
not itself add the 66 C++ patches — the operator must run the patched binary — but the
Python side no longer blocks it. Per-context proxy can't be applied over CDP (the
remote browser's proxy is fixed at its own launch); Pawgrab logs and skips it.

---

## Remaining / optional (not done — decide before doing)

1. **Adopt a fingerprint-patched Chromium binary** (the real moat). ✅ **code seam
   done** — set `PAWGRAB_BROWSER_CDP_URL` to a running CloakBrowser's CDP endpoint and
   the pool connects over `connect_over_cdp` instead of launching locally. What remains
   is purely operational: run the patched binary (separately, e.g. in Docker) and point
   Pawgrab at it. No further Python needed.

2. **Humanize tuning knobs** — CloakBrowser exposes `human_config`
   (`mistype_chance`, `typing_delay`, `idle_between_actions`) and presets
   (`default`/`careful`). Pawgrab has these as module constants; could lift to
   config if per-request control is wanted. Low value unless requested.

3. **WebRTC public-IP spoof** — ✅ handled: proxied-only UDP flags + a JS
   `RTCPeerConnection` block in `browser.py`, so the observed candidate is the proxy
   IP. An explicit JS ICE-candidate rewrite would be belt-and-suspenders; skipped.

4. **Live validation** — run the new stack against a detection site
   (BrowserScan / bot.incolumitas / fingerprint.com) to measure real-world lift.
   Needs a working browser + (ideally) a residential proxy in the environment.
   Not run here.

5. **Platform selection flag** (`windows`/`macos`) — ✅ done:
   `PAWGRAB_FINGERPRINT_PLATFORM` selects a coherent macOS/Safari or Windows/Chrome
   identity (UA, GPU, viewport, client-hints kept coherent in `fingerprint.py`).

---

## Verification

- `ruff check` clean on all touched files.
- Full suite: **765 passed** (was 763 + 40 new − overlap; 2 page-action tests
  updated for the humanize default).
- Extraction untouched → WCXB score unaffected (dev 0.808 / test 0.851).
