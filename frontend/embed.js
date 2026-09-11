/**
 * Rozzgaar Assistant — embed loader (no iframe)
 * -----------------------------------------------------------------------
 * Drop this on any rozzgaar.in page as a single <script> tag:
 *
 *   <script src="https://chatbot.rozzgaar.in/embed.js" defer></script>
 *
 * Unlike the earlier iframe-based version, this injects the widget's
 * markup, stylesheet, and scripts DIRECTLY into the host page. script.js
 * then runs as part of rozzgaar.in's own top-level document — no
 * cross-origin frame boundary, so the storage-access and
 * window.top.location issues that came up with the iframe approach don't
 * apply here at all.
 *
 * IMPORTANT — this trades that isolation for two new requirements:
 *
 *  1. CORS: script.js's fetch() calls to CHAT_URL/TTS_URL in config.js
 *     now run with rozzgaar.in as the request's origin (a genuine
 *     cross-origin request to chatbot.rozzgaar.in), not same-origin as
 *     before. Your FastAPI backend needs CORS middleware allowing
 *     https://rozzgaar.in as an allowed origin, or every /chat and
 *     /tts/speak call will fail.
 *
 *  2. ID collisions: the widget markup below uses ids like "app", "chat",
 *     "input", "composer", "status". If any rozzgaar.in page already uses
 *     one of these ids elsewhere in its own markup, getElementById calls
 *     (in this widget's own script.js, or possibly in rozzgaar.in's own
 *     scripts) could resolve to the wrong element. Worth checking your
 *     site's markup for conflicts before relying on this in production.
 *
 * Requirements this relies on (already true of this codebase):
 *  - frontend/style.css, script.js, config.js and the assets/ folder are
 *    all deployed together at the SAME origin as this embed.js file
 *    (e.g. everything under https://chatbot.rozzgaar.in/).
 *  - The widget markup below is a direct copy of frontend/index.html's
 *    <body> content (icon src attributes rewritten to absolute URLs,
 *    since relative paths would otherwise resolve against rozzgaar.in's
 *    own URL once injected there instead of chatbot.rozzgaar.in). If
 *    index.html's markup changes, this copy needs updating too — it is
 *    NOT fetched dynamically at runtime (fetching index.html cross-origin
 *    would itself require CORS on that response, which this deliberately
 *    avoids needing).
 */

(function () {
    "use strict";

    // ---- Guard against double-inclusion ------------------------------
    if (window.__rozzgaarChatbotEmbedded) {
        return;
    }
    window.__rozzgaarChatbotEmbedded = true;

    // Bump this string any time embed.js is redeployed, so a console.log
    // can confirm the browser actually fetched the new file rather than
    // an old cached copy.
    var EMBED_VERSION = "2024-embed-no-iframe-v1";
    console.log("[Rozzgaar embed.js] loaded, version:", EMBED_VERSION);

    // ---- Work out where the widget's static files live ---------------
    // Auto-detected from this very <script> tag's src, so the same
    // embed.js works unmodified on staging/production/localhost.
    var thisScript =
        document.currentScript ||
        (function () {
            var scripts = document.getElementsByTagName("script");
            return scripts[scripts.length - 1];
        })();

    var WIDGET_ORIGIN;

    try {
        WIDGET_ORIGIN = new URL(thisScript.src).origin;
    } catch (e) {
        WIDGET_ORIGIN = "https://chatbot.rozzgaar.in";
    }

    // ---- Excluded pages ------------------------------------------------
    // Mirrors CONFIG.EXCLUDED_PAGES / isExcludedPage() in frontend/config.js.
    // Kept as a separate copy here so the widget never even gets injected
    // on those pages. Safe to check window.location directly here (no
    // cross-origin concern) since embed.js always runs at the host page's
    // own top level.
    // NOTE: keep this in sync with frontend/config.js if that list changes.
    var EXCLUDED_PAGES = [
        { path: "/applicant/course-content", params: { slug: "green-jobs-edp" } }
    ];

    function isExcludedPage() {
        var loc = window.location;
        var currentParams = new URLSearchParams(loc.search);

        return EXCLUDED_PAGES.some(function (entry) {
            if (loc.pathname !== entry.path) {
                return false;
            }
            if (!entry.params) {
                return true;
            }
            return Object.keys(entry.params).every(function (key) {
                return currentParams.get(key) === entry.params[key];
            });
        });
    }

    // ---- Widget markup -------------------------------------------------
    // Direct copy of frontend/index.html's <body> content (minus the
    // <script> tags, loaded separately below so we can control ordering).
    // Icon src attributes are absolute (WIDGET_ORIGIN-based) since this
    // markup now lives on rozzgaar.in's own page.
    function widgetMarkup(origin) {
        return (
            '<button type="button" id="launcherBtn" class="launcher-btn" aria-label="Open Rozzgaar chat assistant">' +
            '<img src="' + origin + '/assets/rozzgaar-icon.png" alt="" class="launcher-icon" />' +
            '</button>' +
            '<div class="app" id="app">' +
            '<header class="topbar">' +
            '<div class="brand">' +
            '<span class="brand-dot"><img src="' + origin + '/assets/rozzgaar-icon.png" alt="Rozzgaar" class="brand-logo" /></span>' +
            '<div class="brand-text">' +
            '<span class="brand-name" id="brandName">Saarthi</span>' +
            '<span class="status" id="status"><span class="status-dot" id="statusDot"></span><span id="statusText">connecting…</span></span>' +
            '</div>' +
            '</div>' +
            '<div class="topbar-right">' +
            '<button type="button" id="langToggleBtn" class="icon-btn small lang-toggle-btn" title="Switch to Hindi" aria-label="Switch to Hindi">हिं</button>' +
            '<button type="button" id="stopSpeakingBtn" class="icon-btn small stop-speaking-btn" title="Stop speaking" aria-label="Stop speaking" disabled>' +
            '<svg class="speak-icon-triangle" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 4.5v15l14-7.5-14-7.5z"/></svg>' +
            '<svg class="speak-icon-square" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
            '<rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/>' +
            '</svg>' +
            '</button>' +
            '<button type="button" id="minimizeBtn" class="icon-btn small" title="Minimize">➖</button>' +
            '</div>' +
            '</header>' +
            '<nav class="sticky-actions" id="stickyActions" aria-label="Chatbot quick actions">' +
            '<button type="button" id="stickyLoginBtn" class="sticky-action-btn">🔑 Login</button>' +
            '<button type="button" id="stickyRegisterBtn" class="sticky-action-btn">📝 Register</button>' +
            '<button type="button" id="stickyExploreBtn" class="sticky-action-btn">📚 Explore</button>' +
            '</nav>' +
            '<div class="chat-body" id="chatBody">' +
            '<main class="chat" id="chat"></main>' +
            '<form class="composer" id="composer">' +
            '<input type="text" id="input" placeholder="Type your message here…" autocomplete="off" />' +
            '<button type="button" id="micBtn" class="icon-btn" title="Speak instead of typing">' +
            '<svg class="mic-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">' +
            '<path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
            '<path d="M19 11a7 7 0 0 1-14 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
            '<path d="M12 18v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>' +
            '</svg>' +
            '</button>' +
            '<button type="submit" class="send-btn" id="sendBtn" title="Send" aria-label="Send">' +
            '<svg class="send-icon-triangle" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 4.5v15l14-7.5-14-7.5z"/></svg>' +
            '</button>' +
            '</form>' +
            '</div>' +
            '</div>' +
            '<div id="toastContainer"></div>'
        );
    }

    // ---- Script loading helper ------------------------------------------
    // Plain <script src>, not fetch() — this does NOT require CORS headers
    // on config.js/script.js to execute (only fetch()/XHR reading a
    // cross-origin response body needs CORS; a normal script tag loads
    // and runs cross-origin fine either way).
    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            var script = document.createElement("script");
            script.src = src;
            script.onload = resolve;
            script.onerror = function () {
                reject(new Error("Failed to load " + src));
            };
            document.body.appendChild(script);
        });
    }

    async function init() {
        if (isExcludedPage()) {
            return;
        }

        // Stylesheet
        var link = document.createElement("link");
        link.rel = "stylesheet";
        link.href = WIDGET_ORIGIN + "/style.css";
        document.head.appendChild(link);

        // Widget markup
        var container = document.createElement("div");
        container.id = "rzg-widget-root";
        container.innerHTML = widgetMarkup(WIDGET_ORIGIN);
        document.body.appendChild(container);

        // config.js MUST finish loading (and set window.CONFIG) before
        // script.js runs, since script.js reads window.CONFIG at the top
        // of its own execution.
        try {
            await loadScript(WIDGET_ORIGIN + "/config.js");
            await loadScript(WIDGET_ORIGIN + "/script.js");
        } catch (err) {
            console.error("[Rozzgaar embed.js] failed to load widget scripts:", err);
        }
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", init);
    } else {
        init();
    }
})();
