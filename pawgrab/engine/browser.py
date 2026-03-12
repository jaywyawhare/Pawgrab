"""Patchright browser pool with reusable persistent contexts and stealth evasions."""

from __future__ import annotations

import asyncio
import random
import re
import shutil
import tempfile
from urllib.parse import urlparse

import structlog
from patchright.async_api import Browser, BrowserContext, Page, async_playwright

from pawgrab.config import settings
from pawgrab.engine.antibot import random_user_agent, stealth_headers

logger = structlog.get_logger()

_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]

_TIMEZONES = [
    "America/New_York",
    "America/Chicago",
    "America/Denver",
    "America/Los_Angeles",
    "Europe/London",
    "Europe/Berlin",
    "Europe/Paris",
]

_LOCALES = ["en-US", "en-GB", "en-CA", "en-AU"]

_APPLE_GPU_PROFILES = [
    ("Apple M1", 8, 30),
    ("Apple M1 Pro", 10, 15),
    ("Apple M1 Max", 10, 5),
    ("Apple M2", 8, 20),
    ("Apple M2 Pro", 12, 8),
    ("Apple M2 Max", 12, 3),
    ("Apple M3", 8, 10),
    ("Apple M3 Pro", 12, 5),
    ("Intel(R) Iris(TM) Plus Graphics 640", 4, 2),
    ("Intel(R) Iris(TM) Plus Graphics", 4, 2),
]

_APPLE_RENDERERS = [p[0] for p in _APPLE_GPU_PROFILES]

_HARMFUL_DEFAULT_ARGS = frozenset({
    "--enable-automation",
    "--disable-popup-blocking",
    "--disable-component-update",
    "--disable-default-apps",
    "--disable-extensions",
})

_STEALTH_CHROMIUM_ARGS = (
    "--disable-blink-features=AutomationControlled",
    "--no-first-run",
    "--no-default-browser-check",
    "--no-service-autorun",
    "--no-pings",
    "--test-type",
    "--hide-scrollbars",
    "--mute-audio",
    "--password-store=basic",
    "--use-mock-keychain",
    "--disable-infobars",
    "--disable-breakpad",
    "--disable-component-extensions-with-background-pages",
    "--disable-ipc-flooding-protection",
    "--disable-backgrounding-occluded-windows",
    "--disable-renderer-backgrounding",
    "--homepage=about:blank",

    "--fingerprinting-canvas-image-data-noise",
    "--fingerprinting-canvas-measuretext-noise",
    "--fingerprinting-client-rects-noise",

    "--webrtc-ip-handling-policy=disable_non_proxied_udp",
    "--force-webrtc-ip-handling-policy",
    "--enforce-webrtc-ip-permission-check",

    "--blink-settings=primaryHoverType=2,availableHoverTypes=2,"
    "primaryPointerType=4,availablePointerTypes=4",

    "--disable-gpu-sandbox",
    "--disable-partial-raster",
    "--disable-skia-runtime-opts",
    "--disable-2d-canvas-clip-aa",
    "--disable-lcd-text",
    "--force-color-profile=srgb",
    "--font-render-hinting=none",
    "--disable-font-subpixel-positioning",

    "--disable-domain-reliability",
    "--disable-client-side-phishing-detection",
    "--disable-sync",
    "--disable-translate",
    "--disable-voice-input",
    "--disable-hang-monitor",
    "--disable-prompt-on-repost",
    "--disable-background-networking",
    "--disable-default-apps",
    "--metrics-recording-only",
    "--safebrowsing-disable-auto-update",
    "--no-proxy-server",
    "--disable-cookie-encryption",

    "--disable-crash-reporter",
    "--crash-dumps-dir=/tmp",
    "--enable-features=NetworkService,NetworkServiceInProcess,"
    "TrustTokens,TrustTokensAlwaysAllowIssuance",

    "--disable-dev-shm-usage",
    "--disable-session-crashed-bubble",
    "--disable-search-engine-choice-screen",
    "--suppress-message-center-popups",
    "--noerrdialogs",
    "--disable-notifications",
    "--disable-logging",
    "--log-level=3",

    "--enable-async-dns",
    "--enable-tcp-fast-open",
    "--enable-web-bluetooth",
    "--enable-simple-cache-backend",
    "--enable-surface-synchronization",
    "--aggressive-cache-discard",
    "--ignore-gpu-blocklist",

    "--disable-threaded-animation",
    "--disable-threaded-scrolling",
    "--disable-checker-imaging",
    "--disable-image-animation-resync",
    "--disable-new-content-rendering-timeout",
    "--run-all-compositor-stages-before-draw",
    "--disable-layer-tree-host-memory-pressure",
    "--disable-background-timer-throttling",
    "--prerender-from-omnibox=disabled",

    "--autoplay-policy=user-gesture-required",
    "--disable-offer-upload-credit-cards",
    "--disable-offer-store-unmasked-wallet-cards",
    "--disable-cloud-import",
    "--disable-print-preview",
    "--disable-gesture-typing",
    "--disable-wake-on-wifi",

    "--window-size=1920,1080",
    "--window-position=0,0",
    "--start-maximized",
    "--disable-popup-blocking",

    "--lang=en-US,en",
    "--accept-lang=en-US,en;q=0.9",
    "--disable-features=IsolateOrigins,site-per-process,TranslateUI,"
    "AutofillServerCommunication,AudioServiceOutOfProcess,BlinkGenPropertyTrees",
)

_FINGERPRINT_EVASION_JS = """
(function() {
    const VENDOR = "Apple Inc.";
    const RENDERER = "__RENDERER__";

    function patchGetParameter(proto) {
        const orig = proto.getParameter;
        proto.getParameter = function(param) {
            if (param === 37445) return VENDOR;   // UNMASKED_VENDOR_WEBGL
            if (param === 37446) return RENDERER;  // UNMASKED_RENDERER_WEBGL
            return orig.call(this, param);
        };
    }

    patchGetParameter(WebGLRenderingContext.prototype);
    if (typeof WebGL2RenderingContext !== 'undefined') {
        patchGetParameter(WebGL2RenderingContext.prototype);
    }
})();

// __BEGIN_CANVAS_NOISE__
(function() {
    const origGetImageData = CanvasRenderingContext2D.prototype.getImageData;
    const origToDataURL = HTMLCanvasElement.prototype.toDataURL;

    // Per-session random noise seed (2-5% intensity, not 0.01%)
    const noiseR = (Math.random() * 3 + 1) | 0;  // 1-3 bit variation
    const noiseG = (Math.random() * 3 + 1) | 0;
    const noiseB = (Math.random() * 3 + 1) | 0;

    CanvasRenderingContext2D.prototype.getImageData = function() {
        const imageData = origGetImageData.apply(this, arguments);
        // Apply noise to fingerprint-sized reads (< 500KB = ~350x350 canvas)
        if (imageData.data.length < 500000) {
            const d = imageData.data;
            for (let i = 0; i < d.length; i += 4) {
                d[i]     = (d[i]     + noiseR) & 0xFF;  // R
                d[i + 1] = (d[i + 1] - noiseG) & 0xFF;  // G
                d[i + 2] = (d[i + 2] + noiseB) & 0xFF;  // B
                // Alpha untouched — modifying alpha is detectable
            }
        }
        return imageData;
    };

    // Also noise toDataURL for canvas fingerprinting via data: URIs
    HTMLCanvasElement.prototype.toDataURL = function() {
        const ctx = this.getContext('2d');
        if (ctx && this.width * this.height < 125000) {
            // Inject 1 noise pixel at random position
            const x = (Math.random() * this.width) | 0;
            const y = (Math.random() * this.height) | 0;
            const px = ctx.getImageData(x, y, 1, 1);
            px.data[0] = (px.data[0] + noiseR) & 0xFF;
            ctx.putImageData(px, x, y);
        }
        return origToDataURL.apply(this, arguments);
    };
})();
// __END_CANVAS_NOISE__

(function() {
    if (typeof AudioContext === 'undefined' && typeof webkitAudioContext === 'undefined') return;

    const AC = typeof AudioContext !== 'undefined' ? AudioContext : webkitAudioContext;
    const origCreateOscillator = AC.prototype.createOscillator;
    const origCreateDynamicsCompressor = AC.prototype.createDynamicsCompressor;
    const audioNoise = Math.random() * 0.0001;

    // Patch getFloatFrequencyData to add subtle noise
    const origGetFloat = AnalyserNode.prototype.getFloatFrequencyData;
    AnalyserNode.prototype.getFloatFrequencyData = function(array) {
        origGetFloat.call(this, array);
        for (let i = 0; i < array.length; i++) {
            array[i] += audioNoise * (i % 2 === 0 ? 1 : -1);
        }
    };
})();

Object.defineProperty(navigator, 'vendor', {
    get: () => 'Apple Computer, Inc.',
    configurable: true,
});
Object.defineProperty(navigator, 'platform', {
    get: () => 'MacIntel',
    configurable: true,
});
Object.defineProperty(navigator, 'deviceMemory', {
    get: () => __DEVICE_MEMORY__,
    configurable: true,
});
Object.defineProperty(navigator, 'hardwareConcurrency', {
    get: () => __HARDWARE_CONCURRENCY__,
    configurable: true,
});
Object.defineProperty(navigator, 'maxTouchPoints', {
    get: () => 0,  // macOS Safari = 0 touch points
    configurable: true,
});

(function() {
    const fakePlugins = [
        {name: 'PDF Viewer', filename: 'internal-pdf-viewer', description: 'Portable Document Format',
         length: 1, item: function(i) { return this[i]; },
         0: {type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format'}},
        {name: 'Chrome PDF Viewer', filename: 'internal-pdf-viewer', description: '',
         length: 1, item: function(i) { return this[i]; },
         0: {type: 'application/pdf', suffixes: 'pdf', description: ''}},
        {name: 'Chromium PDF Viewer', filename: 'internal-pdf-viewer', description: '',
         length: 1, item: function(i) { return this[i]; },
         0: {type: 'application/pdf', suffixes: 'pdf', description: ''}},
        {name: 'Microsoft Edge PDF Viewer', filename: 'internal-pdf-viewer', description: '',
         length: 1, item: function(i) { return this[i]; },
         0: {type: 'application/pdf', suffixes: 'pdf', description: ''}},
        {name: 'WebKit built-in PDF', filename: 'internal-pdf-viewer', description: '',
         length: 1, item: function(i) { return this[i]; },
         0: {type: 'application/pdf', suffixes: 'pdf', description: ''}},
    ];

    Object.defineProperty(navigator, 'plugins', {
        get: () => {
            const arr = fakePlugins;
            arr.item = function(i) { return this[i]; };
            arr.namedItem = function(name) { return this.find(p => p.name === name); };
            arr.refresh = function() {};
            return arr;
        },
        configurable: true,
    });

    Object.defineProperty(navigator, 'mimeTypes', {
        get: () => {
            const mimes = [{type: 'application/pdf', suffixes: 'pdf', description: 'Portable Document Format'}];
            mimes.item = function(i) { return this[i]; };
            mimes.namedItem = function(name) { return this.find(m => m.type === name); };
            return mimes;
        },
        configurable: true,
    });
})();

// __BEGIN_WEBRTC_BLOCK__
(function() {
    // Disable WebRTC data channels and peer connections to prevent real IP leak
    if (typeof RTCPeerConnection !== 'undefined') {
        const origRTC = RTCPeerConnection;
        window.RTCPeerConnection = function(config) {
            // Strip STUN/TURN servers to prevent IP enumeration
            if (config && config.iceServers) {
                config.iceServers = [];
            }
            return new origRTC(config);
        };
        window.RTCPeerConnection.prototype = origRTC.prototype;
    }
    // Also patch the webkit prefixed version
    if (typeof webkitRTCPeerConnection !== 'undefined') {
        window.webkitRTCPeerConnection = window.RTCPeerConnection;
    }
})();
// __END_WEBRTC_BLOCK__

if (navigator.permissions) {
    const origQuery = navigator.permissions.query;
    navigator.permissions.query = function(desc) {
        if (desc.name === 'notifications') {
            return Promise.resolve({state: 'prompt', onchange: null});
        }
        return origQuery.call(this, desc);
    };
}

// Remove window.chrome (Chromium-only, absent in Safari)
delete window.chrome;
// Prevent re-creation
Object.defineProperty(window, 'chrome', {
    get: () => undefined,
    configurable: true,
});

// Override navigator.webdriver (headless flag)
Object.defineProperty(navigator, 'webdriver', {
    get: () => false,
    configurable: true,
});

// Connection API
if ('connection' in navigator) {
    Object.defineProperty(navigator, 'connection', {
        get: () => undefined,
        configurable: true,
    });
}

// Battery API (Safari removed it years ago)
if ('getBattery' in navigator) {
    Object.defineProperty(navigator, 'getBattery', {
        get: () => undefined,
        configurable: true,
    });
}

// Bluetooth API (Safari doesn't expose it)
if ('bluetooth' in navigator) {
    Object.defineProperty(navigator, 'bluetooth', {
        get: () => undefined,
        configurable: true,
    });
}

// USB API
if ('usb' in navigator) {
    Object.defineProperty(navigator, 'usb', {
        get: () => undefined,
        configurable: true,
    });
}

// Speech synthesis voices — return macOS-like voice list
if (typeof speechSynthesis !== 'undefined') {
    const origGetVoices = speechSynthesis.getVoices;
    speechSynthesis.getVoices = function() {
        const voices = origGetVoices.call(this);
        if (voices.length === 0) {
            // Return at least macOS default voices
            return [{name: 'Samantha', lang: 'en-US', localService: true, voiceURI: 'Samantha', default: true}];
        }
        return voices;
    };
}

if (navigator.mediaDevices) {
    navigator.mediaDevices.enumerateDevices = function() {
        return Promise.resolve([]);
    };
}

if ('vibrate' in navigator) {
    Object.defineProperty(navigator, 'vibrate', {
        get: () => undefined,
        configurable: true,
    });
}

if (typeof SpeechRecognition !== 'undefined') {
    Object.defineProperty(window, 'SpeechRecognition', {
        get: () => undefined,
        configurable: true,
    });
}

if ('keyboard' in navigator) {
    Object.defineProperty(navigator, 'keyboard', {
        get: () => undefined,
        configurable: true,
    });
}

if ('serial' in navigator) {
    Object.defineProperty(navigator, 'serial', {
        get: () => undefined,
        configurable: true,
    });
}

if ('hid' in navigator) {
    Object.defineProperty(navigator, 'hid', {
        get: () => undefined,
        configurable: true,
    });
}

if ('presentation' in navigator) {
    Object.defineProperty(navigator, 'presentation', {
        get: () => undefined,
        configurable: true,
    });
}
"""


def _pick_gpu_profile() -> tuple[str, int, int]:
    """Pick a weighted-random GPU profile. Returns (renderer, hw_concurrency, device_memory)."""
    renderers, concurrencies, weights = zip(*_APPLE_GPU_PROFILES)
    renderer = random.choices(renderers, weights=weights, k=1)[0]
    idx = renderers.index(renderer)
    hw = concurrencies[idx]
    if "Pro" in renderer or "Max" in renderer:
        dev_mem = random.choice([16, 32])
    elif "Intel" in renderer:
        dev_mem = random.choice([4, 8])
    else:
        dev_mem = 8
    return renderer, hw, dev_mem


def _strip_section(script: str, tag: str) -> str:
    """Remove content between ``// __BEGIN_{tag}__`` and ``// __END_{tag}__`` markers."""
    pattern = re.compile(
        rf"// __BEGIN_{re.escape(tag)}__.*?// __END_{re.escape(tag)}__\n?",
        re.DOTALL,
    )
    return pattern.sub("", script)


def _build_evasion_script(browser_type: str = "chromium") -> str:
    """Build fingerprint evasion JS with randomized values matching a consistent profile.

    On Chromium, native flags handle canvas noise and WebRTC blocking, so the
    JS versions are stripped to avoid detectable ``Function.prototype.toString``
    leaks.  Firefox/WebKit keep the full script.
    """
    renderer, hw_concurrency, dev_memory = _pick_gpu_profile()
    script = _FINGERPRINT_EVASION_JS.replace("__RENDERER__", renderer)
    script = script.replace("__HARDWARE_CONCURRENCY__", str(hw_concurrency))
    script = script.replace("__DEVICE_MEMORY__", str(dev_memory))
    if browser_type == "chromium":
        script = _strip_section(script, "CANVAS_NOISE")
        script = _strip_section(script, "WEBRTC_BLOCK")
    return script


async def _apply_stealth(context: BrowserContext) -> None:
    """Apply playwright-stealth evasions to a browser context."""
    try:
        from playwright_stealth import Stealth

        stealth = Stealth()
        await stealth.apply_stealth_async(context)
    except ImportError:
        logger.debug("playwright_stealth_not_installed")


_SHADOW_DOM_FLATTEN_JS = """
(function flattenShadowDOM(root) {
    const elements = root.querySelectorAll('*');
    for (const el of elements) {
        if (el.shadowRoot) {
            const shadowContent = el.shadowRoot.innerHTML;
            const wrapper = document.createElement('div');
            wrapper.setAttribute('data-shadow-root', 'true');
            wrapper.innerHTML = shadowContent;
            el.appendChild(wrapper);
            flattenShadowDOM(wrapper);
        }
    }
})(document);
"""

_IFRAME_INLINE_JS = """
(function inlineIframes() {
    const iframes = document.querySelectorAll('iframe');
    for (const iframe of iframes) {
        try {
            const doc = iframe.contentDocument || iframe.contentWindow?.document;
            if (doc) {
                const wrapper = document.createElement('div');
                wrapper.setAttribute('data-iframe-src', iframe.src || '');
                wrapper.innerHTML = doc.body ? doc.body.innerHTML : '';
                iframe.parentNode.insertBefore(wrapper, iframe);
                iframe.remove();
            }
        } catch(e) { /* cross-origin, skip */ }
    }
})();
"""

_OVERLAY_REMOVAL_JS = """
(function removeOverlays() {
    // Remove elements with common overlay/modal/cookie-banner patterns
    const selectors = [
        '[class*="cookie"]', '[id*="cookie"]',
        '[class*="consent"]', '[id*="consent"]',
        '[class*="modal"]', '[id*="modal"]',
        '[class*="overlay"]', '[id*="overlay"]',
        '[class*="popup"]', '[id*="popup"]',
        '[class*="banner"]', '[id*="banner"]',
        '[class*="gdpr"]', '[id*="gdpr"]',
        '[class*="newsletter"]', '[id*="newsletter"]',
    ];

    for (const sel of selectors) {
        for (const el of document.querySelectorAll(sel)) {
            const style = window.getComputedStyle(el);
            const isOverlay = style.position === 'fixed' || style.position === 'sticky'
                || style.zIndex > 999;
            if (isOverlay) {
                el.remove();
            }
        }
    }

    // Remove any remaining fixed/sticky elements with high z-index (likely overlays)
    for (const el of document.querySelectorAll('*')) {
        const style = window.getComputedStyle(el);
        if ((style.position === 'fixed' || style.position === 'sticky')
            && parseInt(style.zIndex) > 9999
            && el.tagName !== 'HEADER') {
            el.remove();
        }
    }

    // Re-enable scrolling on body (often disabled by modals)
    document.body.style.overflow = 'auto';
    document.documentElement.style.overflow = 'auto';
})();
"""

_SCROLL_TO_BOTTOM_JS = """
async function scrollToBottom() {
    const delay = ms => new Promise(r => setTimeout(r, ms));
    let prevHeight = 0;
    let attempts = 0;
    const maxAttempts = 30;

    while (attempts < maxAttempts) {
        window.scrollTo(0, document.body.scrollHeight);
        await delay(800);
        const newHeight = document.body.scrollHeight;
        if (newHeight === prevHeight) {
            attempts++;
            if (attempts >= 3) break;
        } else {
            attempts = 0;
        }
        prevHeight = newHeight;
    }
    window.scrollTo(0, 0);
}
await scrollToBottom();
"""

_AD_TRACKER_DOMAINS = frozenset({
    "doubleclick.net",
    "adservice.google.com",
    "googlesyndication.com",
    "googletagservices.com",
    "googletagmanager.com",
    "google-analytics.com",
    "googleadservices.com",
    "analytics.google.com",
    "adsystem.com",
    "adnxs.com",
    "ads-twitter.com",
    "facebook.net",
    "fbcdn.net",
    "amazon-adsystem.com",
    "hotjar.com",
    "clarity.ms",
    "newrelic.com",
    "nr-data.net",
    "sentry.io",
    "segment.com",
    "mixpanel.com",
    "quantserve.com",
    "scorecardresearch.com",
    "criteo.com",
    "outbrain.com",
    "taboola.com",
})

_BLOCKED_MEDIA_TYPES = frozenset({"image", "media", "font"})


async def _route_handler(route, *, block_media: bool = False):
    """Block ad/tracker domains and optionally media resources."""
    req = route.request
    try:
        hostname = urlparse(req.url).hostname or ""
    except Exception:
        hostname = ""
    # Block known ad/tracker domains
    if any(hostname == d or hostname.endswith("." + d) for d in _AD_TRACKER_DOMAINS):
        return await route.abort()
    # Optionally block media resources (images, fonts, video/audio)
    if block_media and req.resource_type in _BLOCKED_MEDIA_TYPES:
        return await route.abort()
    return await route.continue_()


_CF_CHALLENGE_RE = re.compile(
    r"^https?://challenges\.cloudflare\.com/cdn-cgi/challenge-platform/.*"
)


def _detect_cloudflare(html: str) -> str | None:
    """Detect Cloudflare challenge type from page HTML.

    Returns one of ``"non-interactive"``, ``"managed"``, ``"interactive"``,
    ``"embedded_turnstile"``, or ``None`` if no CF challenge is detected.
    """
    if not html:
        return None
    for ctype in ("non-interactive", "managed", "interactive"):
        if f"cType: '{ctype}'" in html or f'cType: "{ctype}"' in html:
            return ctype
    if "challenges.cloudflare.com/turnstile" in html:
        return "embedded_turnstile"
    return None


_CF_BOX_SELECTOR = "#cf_turnstile div, #cf-turnstile div, .turnstile>div>div"
_CF_INTERSTITIAL_BOX_SELECTOR = ".main-content p+div>div>div"


async def _cf_page_content(page) -> str:
    """Get page content, handling errors gracefully."""
    try:
        return await page.content()
    except Exception:
        return ""


async def _cf_is_solved(page) -> bool:
    """Check whether the CF challenge has disappeared."""
    return "<title>Just a moment...</title>" not in await _cf_page_content(page)


async def solve_cloudflare(page, *, max_retries: int = 2) -> bool:
    """Attempt to solve a Cloudflare Turnstile challenge on *page*.

    Returns ``True`` if the challenge was solved and the page navigated to
    the real content, ``False`` otherwise.
    """
    try:
        await page.wait_for_load_state("networkidle", timeout=5_000)
    except Exception:
        pass

    html = await _cf_page_content(page)
    cf_type = _detect_cloudflare(html)
    if cf_type is None:
        return False

    logger.info("cf_challenge_detected", cf_type=cf_type)

    for attempt in range(max_retries + 1):
        if cf_type == "non-interactive":
            while "<title>Just a moment...</title>" in await _cf_page_content(page):
                try:
                    await page.wait_for_timeout(1_000)
                    await page.wait_for_load_state("load", timeout=5_000)
                except Exception:
                    break
            if await _cf_is_solved(page):
                return True
            if attempt == max_retries:
                return False
            await asyncio.sleep(2)
            continue

        try:
            if cf_type != "embedded_turnstile":
                while "Verifying you are human." in await _cf_page_content(page):
                    await page.wait_for_timeout(500)

            outer_box = None
            cf_frame = None
            for frame in page.frames:
                if _CF_CHALLENGE_RE.match(frame.url or ""):
                    cf_frame = frame
                    break

            if cf_frame is not None:
                await page.wait_for_load_state("load", timeout=5_000)

                if cf_type != "embedded_turnstile":
                    frame_el = await cf_frame.frame_element()
                    for _ in range(20):
                        if await frame_el.is_visible():
                            break
                        await page.wait_for_timeout(500)

                frame_el = await cf_frame.frame_element()
                outer_box = await frame_el.bounding_box()

            if not cf_frame or not outer_box:
                if await _cf_is_solved(page):
                    return True
                box_sel = (
                    _CF_BOX_SELECTOR if cf_type == "embedded_turnstile"
                    else _CF_INTERSTITIAL_BOX_SELECTOR
                )
                try:
                    outer_box = await page.locator(box_sel).last.bounding_box()
                except Exception:
                    pass

            if not outer_box:
                if attempt == max_retries:
                    return False
                await asyncio.sleep(2)
                continue

            x = outer_box["x"] + random.randint(26, 28)
            y = outer_box["y"] + random.randint(25, 27)
            await page.mouse.click(x, y, delay=random.randint(100, 200), button="left")

            try:
                await page.wait_for_load_state("networkidle", timeout=10_000)
            except Exception:
                pass

            if cf_type != "embedded_turnstile":
                for _ in range(100):
                    if await _cf_is_solved(page):
                        break
                    await page.wait_for_timeout(100)

            await page.wait_for_load_state("load", timeout=5_000)

            if await _cf_is_solved(page):
                return True

            logger.debug("cf_still_present_retrying", attempt=attempt)
        except Exception:
            logger.debug("cf_solve_attempt_failed", attempt=attempt)

        if attempt < max_retries:
            await asyncio.sleep(2)

    return False


class BrowserPool:
    def __init__(self, pool_size: int | None = None, browser_type: str | None = None):
        self._pool_size = pool_size or settings.browser_pool_size
        self._browser_type = browser_type or settings.browser_type
        self._browser: Browser | None = None
        self._pages: asyncio.Queue[Page] = asyncio.Queue()
        self._playwright = None
        self._started = False
        self._degraded = False
        self._persistent_contexts: dict[str, BrowserContext] = {}
        self._user_data_dir: str | None = None
        self._persistent_ctx: BrowserContext | None = None
        self._proxy_browser: Browser | None = None

    def _context_kwargs(
        self,
        proxy_url: str | None = None,
        geolocation: dict[str, float] | None = None,
    ) -> dict:
        """Build common context/launch kwargs for stealth sessions."""
        ua = random_user_agent()
        viewport = random.choice(_VIEWPORTS)
        timezone = random.choice(_TIMEZONES)
        locale = random.choice(_LOCALES)
        headers = stealth_headers(user_agent=ua, timezone=timezone)
        extra = {
            k: v for k, v in headers.items()
            if k not in ("User-Agent", "Accept-Encoding")
        }
        kwargs: dict = dict(
            user_agent=ua,
            locale=locale,
            timezone_id=timezone,
            viewport=viewport,
            screen={"width": viewport["width"], "height": viewport["height"]},
            extra_http_headers=extra,
            color_scheme="dark",
            device_scale_factor=2,
            is_mobile=False,
            has_touch=False,
            service_workers="allow",
            ignore_https_errors=True,
            permissions=["geolocation", "notifications"],
        )
        if proxy_url:
            kwargs["proxy"] = {"server": proxy_url}
        if geolocation:
            kwargs["geolocation"] = {
                "latitude": geolocation.get("latitude", 0),
                "longitude": geolocation.get("longitude", 0),
                "accuracy": geolocation.get("accuracy", 100),
            }
        return kwargs

    async def _new_stealth_page(
        self,
        proxy_url: str | None = None,
        geolocation: dict[str, float] | None = None,
    ) -> Page:
        """Create a new page with stealth evasions.

        For Chromium without a proxy, reuses the persistent context (shared
        cookies/localStorage make the browser look like a returning visitor).
        When proxy_url is set, a separate browser context is created.
        """
        if not proxy_url and self._persistent_ctx is not None:
            return await self._persistent_ctx.new_page()

        if proxy_url:
            if self._proxy_browser is None:
                launcher = await self._get_browser_launcher()
                is_chromium = self._browser_type == "chromium"
                self._proxy_browser = await launcher.launch(
                    headless=True,
                    args=list(_STEALTH_CHROMIUM_ARGS) if is_chromium else None,
                    ignore_default_args=list(_HARMFUL_DEFAULT_ARGS) if is_chromium else None,
                )
            ctx_kwargs = self._context_kwargs(proxy_url=proxy_url, geolocation=geolocation)
            ctx = await self._proxy_browser.new_context(**ctx_kwargs)
            if settings.stealth_mode:
                await _apply_stealth(ctx)
                evasion_js = _build_evasion_script(browser_type=self._browser_type)
                await ctx.add_init_script(evasion_js)
            await ctx.route("**/*", _route_handler)
            return await ctx.new_page()

        assert self._browser is not None
        ctx_kwargs = self._context_kwargs(geolocation=geolocation)
        ctx = await self._browser.new_context(**ctx_kwargs)
        if settings.stealth_mode:
            await _apply_stealth(ctx)
            evasion_js = _build_evasion_script(browser_type=self._browser_type)
            await ctx.add_init_script(evasion_js)
        await ctx.route("**/*", _route_handler)
        return await ctx.new_page()

    async def _get_browser_launcher(self):
        """Get the browser launcher based on configured browser type."""
        match self._browser_type:
            case "firefox":
                return self._playwright.firefox
            case "webkit":
                return self._playwright.webkit
            case _:
                return self._playwright.chromium

    async def start(self):
        if self._started:
            return
        self._playwright = await async_playwright().start()
        launcher = await self._get_browser_launcher()
        is_chromium = self._browser_type == "chromium"

        if is_chromium:
            self._user_data_dir = tempfile.mkdtemp(prefix="pawgrab_chrome_")
            ctx_kwargs = self._context_kwargs()
            ctx_kwargs.pop("permissions", None)
            self._persistent_ctx = await launcher.launch_persistent_context(
                self._user_data_dir,
                headless=True,
                args=list(_STEALTH_CHROMIUM_ARGS),
                ignore_default_args=list(_HARMFUL_DEFAULT_ARGS),
                **ctx_kwargs,
            )
            if settings.stealth_mode:
                await _apply_stealth(self._persistent_ctx)
                evasion_js = _build_evasion_script(browser_type="chromium")
                await self._persistent_ctx.add_init_script(evasion_js)
            await self._persistent_ctx.route("**/*", _route_handler)
            try:
                await self._persistent_ctx.grant_permissions(
                    ["geolocation", "notifications"],
                )
            except Exception:
                pass
            self._browser = None
            for _ in range(self._pool_size):
                page = await self._persistent_ctx.new_page()
                await self._pages.put(page)
        else:
            self._browser = await launcher.launch(headless=True)
            for _ in range(self._pool_size):
                page = await self._new_stealth_page()
                await self._pages.put(page)

        self._started = True
        logger.info(
            "browser_pool_started",
            size=self._pool_size,
            browser=self._browser_type,
            stealth=settings.stealth_mode,
        )

    async def replace_with_proxied_page(
        self,
        old_page: Page,
        proxy_url: str,
        geolocation: dict[str, float] | None = None,
    ) -> Page:
        """Close old_page and create a new stealth page with proxy."""
        is_persistent_page = (
            self._persistent_ctx is not None
            and old_page.context == self._persistent_ctx
        )
        try:
            if is_persistent_page:
                await old_page.close()
            else:
                await old_page.context.close()
        except Exception:
            pass
        return await self._new_stealth_page(proxy_url=proxy_url, geolocation=geolocation)

    async def acquire(self) -> Page:
        return await self._pages.get()

    async def release(self, page: Page):
        is_persistent_page = (
            self._persistent_ctx is not None
            and page.context == self._persistent_ctx
        )

        if is_persistent_page:
            try:
                await page.close()
            except Exception:
                logger.debug("page_close_failed_during_release")
        else:
            try:
                await page.context.close()
            except Exception:
                logger.debug("context_close_failed_during_release")

        if self._degraded:
            return
        if not self._persistent_ctx and not self._browser:
            return

        new_page = None
        try:
            new_page = await self._new_stealth_page()
        except Exception:
            logger.warning("stealth_page_creation_failed")
            try:
                if self._persistent_ctx is not None:
                    new_page = await self._persistent_ctx.new_page()
                elif self._browser is not None:
                    ctx = await self._browser.new_context()
                    new_page = await ctx.new_page()
            except Exception:
                logger.error("page_creation_failed_pool_degraded")
                self._degraded = True

        if new_page is not None:
            await self._pages.put(new_page)

    async def stop(self):
        if not self._started:
            return
        for ctx in self._persistent_contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._persistent_contexts.clear()

        while not self._pages.empty():
            page = self._pages.get_nowait()
            try:
                await page.close()
            except Exception:
                pass

        if self._persistent_ctx:
            try:
                await self._persistent_ctx.close()
            except Exception:
                pass
            self._persistent_ctx = None

        if self._proxy_browser:
            try:
                await self._proxy_browser.close()
            except Exception:
                pass
            self._proxy_browser = None

        if self._browser:
            await self._browser.close()
            self._browser = None

        if self._playwright:
            await self._playwright.stop()
            self._playwright = None

        if self._user_data_dir:
            shutil.rmtree(self._user_data_dir, ignore_errors=True)
            self._user_data_dir = None

        self._started = False
        logger.info("browser_pool_stopped")
