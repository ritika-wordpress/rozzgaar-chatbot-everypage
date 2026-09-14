/**
 * embed.js
 * --------
 * Drop this one script tag on any page of rozzgaar.in to load the Rozzgaar
 * chat assistant as a floating widget:
 *
 *   <script src="https://chatbot.rozzgaar.in/embed.js"
 *           data-base-url="https://chatbot.rozzgaar.in"></script>
 *
 * It does NOT talk to the chat backend directly — it just injects a
 * launcher button + an iframe pointing at this project's own index.html
 * (with ?embedded=1, which index.html/script.js already understand: it
 * auto-opens inside the iframe and hides its own internal launcher, since
 * THIS script draws the launcher on the host page instead). The iframe is
 * created once, up front, and only shown/hidden after that — never
 * destroyed — so the chat session (kept in the iframe's own sessionStorage)
 * survives being minimized and reopened.
 *
 * Config (all optional):
 *   - <script data-base-url="https://...">  — where index.html/style.css/
 *     assets/ live. Defaults to the directory this embed.js file itself
 *     was loaded from, so if embed.js and index.html are deployed together
 *     you don't need to set anything.
 *   - window.ROZZGAAR_CHATBOT_CONFIG = { baseUrl, zIndex }  — same, plus an
 *     optional stacking context override if the host page has its own
 *     high z-index elements (e.g. modals) that this widget must sit above
 *     or below.
 *
 * Safe to include on every page (guards against double-init if the tag
 * ever ends up on the page twice).
 */
(function () {
    "use strict";

    if (window.__rozzgaarChatbotEmbedded) {
        return;
    }
    window.__rozzgaarChatbotEmbedded = true;

    // ===================== Resolve config =====================

    var userConfig = window.ROZZGAAR_CHATBOT_CONFIG || {};

    var thisScript =
        document.currentScript ||
        (function () {
            // Fallback for older browsers: last <script src="...embed.js">
            // on the page at the time this IIFE runs.
            var scripts = document.getElementsByTagName("script");
            for (var i = scripts.length - 1; i >= 0; i--) {
                if (/embed\.js(\?|#|$)/.test(scripts[i].src)) {
                    return scripts[i];
                }
            }
            return null;
        })();

    function deriveBaseUrl() {
        if (userConfig.baseUrl) return userConfig.baseUrl;

        if (thisScript && thisScript.getAttribute("data-base-url")) {
            return thisScript.getAttribute("data-base-url");
        }

        if (thisScript && thisScript.src) {
            // Strip "embed.js" (plus any query string) off the script's
            // own URL to get the directory it's served from.
            return thisScript.src.replace(/embed\.js(\?.*)?$/, "");
        }

        // Last resort — same origin, root path.
        return "/";
    }

    var BASE_URL = deriveBaseUrl().replace(/\/+$/, "");
    var Z_INDEX = userConfig.zIndex || 999999;
    var WIDGET_SRC = BASE_URL + "/index.html?embedded=1";
    var LAUNCHER_ICON_SRC = BASE_URL + "/assets/rozzgaar-icon.png";

    // ===================== Inject scoped styles =====================
    // Prefixed classes so nothing here collides with the host page's CSS.

    var style = document.createElement("style");
    style.textContent = [
        "#rzg-embed-launcher {",
        "  position: fixed; right: 24px; bottom: 24px;",
        "  width: 58px; height: 58px; border-radius: 50%;",
        "  border: 3px solid #C0392B; background: #fff;",
        "  cursor: pointer; padding: 0;",
        "  box-shadow: 0 10px 26px rgba(0,0,0,0.28);",
        "  display: flex; align-items: center; justify-content: center;",
        "  z-index: " + Z_INDEX + ";",
        "  transition: transform 0.15s ease;",
        "}",
        "#rzg-embed-launcher:hover { transform: scale(1.06); }",
        "#rzg-embed-launcher.rzg-hidden { display: none; }",
        "#rzg-embed-launcher img { width: 34px; height: 34px; display: block; pointer-events: none; }",
        "#rzg-embed-frame {",
        "  position: fixed; right: 20px; bottom: 20px;",
        "  width: 380px; height: 560px;",
        "  max-width: calc(100vw - 24px); max-height: calc(100vh - 24px);",
        "  border: 0; border-radius: 14px;",
        "  box-shadow: 0 16px 40px rgba(0,0,0,0.22);",
        "  z-index: " + Z_INDEX + ";",
        "  background: transparent;",
        "  display: none;",
        "}",
        "#rzg-embed-frame.rzg-open { display: block; }",
        "@media (max-width: 420px) {",
        "  #rzg-embed-frame {",
        "    right: 0; bottom: 0; left: 0; top: 0;",
        "    width: 100%; height: 100%;",
        "    max-width: 100%; max-height: 100%;",
        "    border-radius: 0;",
        "  }",
        "  #rzg-embed-launcher { right: 16px; bottom: 16px; }",
        "}",
    ].join("\n");
    document.head.appendChild(style);

    // ===================== Build launcher + iframe =====================

    var launcher = document.createElement("button");
    launcher.type = "button";
    launcher.id = "rzg-embed-launcher";
    launcher.setAttribute("aria-label", "Open Rozzgaar chat assistant");

    var icon = document.createElement("img");
    icon.src = LAUNCHER_ICON_SRC;
    icon.alt = "";
    launcher.appendChild(icon);

    var frame = document.createElement("iframe");
    frame.id = "rzg-embed-frame";
    frame.src = WIDGET_SRC;
    frame.title = "Rozzgaar chat assistant";
    frame.setAttribute("allow", "microphone; autoplay");

    function openWidget() {
        frame.classList.add("rzg-open");
        launcher.classList.add("rzg-hidden");
    }

    function closeWidget() {
        frame.classList.remove("rzg-open");
        launcher.classList.remove("rzg-hidden");
    }

    launcher.addEventListener("click", openWidget);

    // The iframe's own script.js (embedded mode) posts this back to us
    // when the user taps its ➖ minimize button.
    window.addEventListener("message", function (event) {
        if (
            event.data &&
            event.data.type === "ROZZGAAR_CHATBOT_MINIMIZE" &&
            event.source === frame.contentWindow
        ) {
            closeWidget();
        }
    });

    function mount() {
        document.body.appendChild(frame);
        document.body.appendChild(launcher);
    }

    if (document.body) {
        mount();
    } else {
        document.addEventListener("DOMContentLoaded", mount);
    }
})();
