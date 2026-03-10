"""Playwright browser pool with reusable contexts and stealth evasions.

Applies deep fingerprint spoofing to make Chromium look like Safari:
  - WebGL: spoofs UNMASKED_VENDOR/RENDERER to Apple GPU strings
  - Canvas: injects sub-pixel noise to randomize fingerprint hash
  - navigator: vendor, deviceMemory, hardwareConcurrency, maxTouchPoints
  - Timezone and locale randomized per context
"""

from __future__ import annotations

import asyncio
import random

import structlog
from playwright.async_api import Browser, BrowserContext, Page, async_playwright

from pawgrab.config import settings
from pawgrab.engine.antibot import random_user_agent, stealth_headers

logger = structlog.get_logger()

# Viewport sizes to randomize fingerprints
_VIEWPORTS = [
    {"width": 1920, "height": 1080},
    {"width": 1440, "height": 900},
    {"width": 1536, "height": 864},
    {"width": 1366, "height": 768},
    {"width": 2560, "height": 1440},
]

# Timezones weighted towards common US/EU zones
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

# Apple GPU renderer strings weighted by 2025-2026 market share.
# Each entry: (renderer, typical_hw_concurrency, weight)
_APPLE_GPU_PROFILES = [
    ("Apple M1", 8, 30),           # Still dominant in Safari traffic
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

# Flat list for backward-compatible access in tests
_APPLE_RENDERERS = [p[0] for p in _APPLE_GPU_PROFILES]

# JavaScript to inject BEFORE any page script runs.
# This overrides browser fingerprint APIs to match a Safari/macOS profile.
# Each __PLACEHOLDER__ is replaced at runtime with randomized values.
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
"""


def _pick_gpu_profile() -> tuple[str, int, int]:
    """Pick a weighted-random GPU profile. Returns (renderer, hw_concurrency, device_memory)."""
    renderers, concurrencies, weights = zip(*_APPLE_GPU_PROFILES)
    renderer = random.choices(renderers, weights=weights, k=1)[0]
    idx = renderers.index(renderer)
    hw = concurrencies[idx]
    # Device memory correlates with chip: M1/M2/M3 base = 8GB, Pro/Max = 16-32GB
    if "Pro" in renderer or "Max" in renderer:
        dev_mem = random.choice([16, 32])
    elif "Intel" in renderer:
        dev_mem = random.choice([4, 8])
    else:
        dev_mem = 8
    return renderer, hw, dev_mem


def _build_evasion_script() -> str:
    """Build fingerprint evasion JS with randomized values matching a consistent profile."""
    renderer, hw_concurrency, dev_memory = _pick_gpu_profile()
    script = _FINGERPRINT_EVASION_JS.replace("__RENDERER__", renderer)
    script = script.replace("__HARDWARE_CONCURRENCY__", str(hw_concurrency))
    script = script.replace("__DEVICE_MEMORY__", str(dev_memory))
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


class BrowserPool:
    def __init__(self, pool_size: int | None = None, browser_type: str | None = None):
        self._pool_size = pool_size or settings.browser_pool_size
        self._browser_type = browser_type or settings.browser_type
        self._browser: Browser | None = None
        self._pages: asyncio.Queue[Page] = asyncio.Queue()
        self._playwright = None
        self._started = False
        self._degraded = False
        # Persistent context pool for session reuse
        self._persistent_contexts: dict[str, BrowserContext] = {}

    async def _new_stealth_page(
        self,
        proxy_url: str | None = None,
        geolocation: dict[str, float] | None = None,
    ) -> Page:
        """Create a new page with stealth evasions and a Safari fingerprint.

        When proxy_url is set, the browser context routes all traffic through
        that proxy. Playwright sets proxy at context creation time, so a new
        context is required for each distinct proxy.
        """
        assert self._browser is not None
        ua = random_user_agent()
        viewport = random.choice(_VIEWPORTS)
        timezone = random.choice(_TIMEZONES)
        locale = random.choice(_LOCALES)
        headers = stealth_headers(user_agent=ua, timezone=timezone)
        extra = {
            k: v for k, v in headers.items()
            if k not in ("User-Agent", "Accept-Encoding")
        }
        ctx_kwargs: dict = dict(
            user_agent=ua,
            locale=locale,
            timezone_id=timezone,
            viewport=viewport,
            extra_http_headers=extra,
        )
        if proxy_url:
            ctx_kwargs["proxy"] = {"server": proxy_url}
        if geolocation:
            ctx_kwargs["geolocation"] = {
                "latitude": geolocation.get("latitude", 0),
                "longitude": geolocation.get("longitude", 0),
                "accuracy": geolocation.get("accuracy", 100),
            }
            ctx_kwargs["permissions"] = ["geolocation"]
        ctx = await self._browser.new_context(**ctx_kwargs)
        if settings.stealth_mode:
            await _apply_stealth(ctx)

            # Inject deep fingerprint evasion script before any page JS runs
            evasion_js = _build_evasion_script()
            await ctx.add_init_script(evasion_js)

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

        launch_args = []
        if self._browser_type == "chromium":
            launch_args = [
                "--disable-blink-features=AutomationControlled",
                "--no-first-run",
                "--no-default-browser-check",
                "--disable-component-update",
                "--disable-features=IsolateOrigins,site-per-process",
                "--hide-scrollbars",
                "--mute-audio",
            ]

        self._browser = await launcher.launch(
            headless=True,
            args=launch_args if launch_args else None,
        )
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
        """Close old_page's context and create a new stealth page with proxy."""
        try:
            await old_page.context.close()
        except Exception:
            pass
        return await self._new_stealth_page(proxy_url=proxy_url, geolocation=geolocation)

    async def acquire(self) -> Page:
        return await self._pages.get()

    async def release(self, page: Page):
        # Always close the old context
        try:
            await page.context.close()
        except Exception:
            logger.debug("context_close_failed_during_release")

        # Always return a page to the queue to prevent starvation
        if not self._browser or self._degraded:
            return

        new_page = None
        try:
            new_page = await self._new_stealth_page()
        except Exception:
            logger.warning("stealth_page_creation_failed")
            try:
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
        # Close persistent contexts
        for ctx in self._persistent_contexts.values():
            try:
                await ctx.close()
            except Exception:
                pass
        self._persistent_contexts.clear()

        while not self._pages.empty():
            page = self._pages.get_nowait()
            try:
                await page.context.close()
            except Exception:
                pass
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()
        self._started = False
        logger.info("browser_pool_stopped")
