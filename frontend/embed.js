/**
 * Rozzgaar Chatbot — embed loader (no iframe).
 *
 * Include this one file on any rozzgaar.in page:
 *
 *   <script src="https://chatbot.rozzgaar.in/embed.js" async></script>
 *
 * An earlier version of this loader put the widget in an iframe pointed
 * at chatbot.rozzgaar.in — but that subdomain isn't set up to allow
 * being framed, so the iframe just rendered blank. This version instead
 * mounts the real widget (same markup, same style.css, same script.js
 * used on chatbot.rozzgaar.in's own page) directly onto the host page,
 * inside a Shadow DOM root so its CSS can't leak onto — or be clobbered
 * by — the host page's own styles.
 *
 * script.js is unchanged apart from one thing: it now looks elements up
 * through `window.ROZZGAAR_WIDGET_ROOT` instead of hardcoding `document`,
 * falling back to `document` when that global isn't set (i.e. when it's
 * loaded normally by chatbot.rozzgaar.in/index.html). That's set below,
 * before script.js is loaded, so the exact same file runs in both places.
 */
(function () {
    "use strict";

    // Where the chatbot's static assets (style.css, script.js, config.js,
    // icons) are hosted. Update this if the subdomain ever changes.
    var CHATBOT_ORIGIN = "https://chatbot.rozzgaar.in";

    // Pages where the widget should not appear at all. Mirrors
    // CONFIG.EXCLUDED_PAGES in frontend/config.js — keep both in sync.
    var EXCLUDED_PAGES = [
        {
            path: "/applicant/course-content",
            params: { slug: "green-jobs-edp" }
        }
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

    if (isExcludedPage()) {
        return;
    }

    // Don't double-inject if the script is somehow included twice.
    if (window.__rozzgaarChatbotEmbedded) {
        return;
    }
    window.__rozzgaarChatbotEmbedded = true;

    // Same markup as chatbot.rozzgaar.in/index.html's <body>, minus the
    // <script> tags (loaded separately below, in order). Asset paths are
    // rewritten to absolute chatbot.rozzgaar.in URLs since this HTML is
    // inserted into the host page rather than served from that origin.
    var WIDGET_HTML = [
        '<link rel="stylesheet" href="' + CHATBOT_ORIGIN + '/style.css">',
        '<button type="button" id="launcherBtn" class="launcher-btn" aria-label="Open Rozzgaar chat assistant">',
        '  <img src="' + CHATBOT_ORIGIN + '/assets/rozzgaar-icon.png" alt="" class="launcher-icon" />',
        '</button>',
        '<div class="app" id="app">',
        '  <header class="topbar">',
        '    <div class="brand">',
        '      <span class="brand-dot"><img src="' + CHATBOT_ORIGIN + '/assets/rozzgaar-icon.png" alt="Rozzgaar" class="brand-logo" /></span>',
        '      <div class="brand-text">',
        '        <span class="brand-name" id="brandName">Saarthi</span>',
        '        <span class="status" id="status"><span class="status-dot" id="statusDot"></span><span id="statusText">connecting…</span></span>',
        '      </div>',
        '    </div>',
        '    <div class="topbar-right">',
        '      <button type="button" id="langToggleBtn" class="icon-btn small lang-toggle-btn" title="Switch to Hindi" aria-label="Switch to Hindi">हिं</button>',
        '      <button type="button" id="stopSpeakingBtn" class="icon-btn small stop-speaking-btn" title="Stop speaking" aria-label="Stop speaking" disabled>',
        '        <svg class="speak-icon-triangle" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 4.5v15l14-7.5-14-7.5z"/></svg>',
        '        <svg class="speak-icon-square" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><rect x="7" y="7" width="10" height="10" rx="1.5" fill="currentColor"/></svg>',
        '      </button>',
        '      <button type="button" id="minimizeBtn" class="icon-btn small minimize-btn" title="Minimize" aria-label="Minimize">',
        '        <svg class="minimize-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M5 12h14" stroke="currentColor" stroke-width="2.2" stroke-linecap="round"/></svg>',
        '      </button>',
        '    </div>',
        '  </header>',
        '  <nav class="sticky-actions" id="stickyActions" aria-label="Chatbot quick actions">',
        '    <button type="button" id="stickyLoginBtn" class="sticky-action-btn">🔑 Login</button>',
        '    <button type="button" id="stickyRegisterBtn" class="sticky-action-btn">📝 Register</button>',
        '    <button type="button" id="stickyExploreBtn" class="sticky-action-btn">📚 Explore</button>',
        '  </nav>',
        '  <div class="chat-body" id="chatBody">',
        '    <main class="chat" id="chat"></main>',
        '    <form class="composer" id="composer">',
        '      <input type="text" id="input" placeholder="Type your message here…" autocomplete="off" />',
        '      <button type="button" id="micBtn" class="icon-btn" title="Speak instead of typing">',
        '        <svg class="mic-icon" viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg" aria-hidden="true">',
        '          <path d="M12 15a3 3 0 0 0 3-3V6a3 3 0 0 0-6 0v6a3 3 0 0 0 3 3Z" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        '          <path d="M19 11a7 7 0 0 1-14 0" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        '          <path d="M12 18v3" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"/>',
        '        </svg>',
        '      </button>',
        '      <button type="submit" class="send-btn" id="sendBtn" title="Send" aria-label="Send">',
        '        <svg class="send-icon-triangle" viewBox="0 0 24 24" fill="currentColor" xmlns="http://www.w3.org/2000/svg" aria-hidden="true"><path d="M2 21l21-9L2 3v7l15 2-15 2v7z"/></svg>',
        '      </button>',
        '    </form>',
        '  </div>',
        '</div>',
        '<div id="toastContainer"></div>'
    ].join("\n");

    function loadScript(src) {
        return new Promise(function (resolve, reject) {
            var s = document.createElement("script");
            s.src = src;
            s.onload = resolve;
            s.onerror = function () {
                reject(new Error("Failed to load " + src));
            };
            document.body.appendChild(s);
        });
    }

    function mount() {
        var host = document.createElement("div");
        host.id = "rzg-embed-host";
        document.body.appendChild(host);

        var shadow = host.attachShadow({ mode: "open" });
        shadow.innerHTML = WIDGET_HTML;

        // config.js's isExcludedPage() and script.js's element lookups
        // both need to find things inside this shadow tree from here on.
        window.ROZZGAAR_WIDGET_ROOT = shadow;

        loadScript(CHATBOT_ORIGIN + "/config.js")
            .then(function () {
                return loadScript(CHATBOT_ORIGIN + "/script.js");
            })
            .catch(function (err) {
                console.error("Rozzgaar chatbot failed to load:", err);
            });
    }

    if (document.body) {
        mount();
    } else {
        document.addEventListener("DOMContentLoaded", mount);
    }
})();