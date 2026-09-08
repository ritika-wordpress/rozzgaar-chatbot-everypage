
/*!
 * Rozzgaar Saarthi Chatbot Embed
 * --------------------------------
 * Add this ONE script to rozzgaar.in:
 *
 * <script
 *   src="https://chatbot.rozzgaar.in/embed.js"
 *   defer>
 * </script>
 */

(function () {
  "use strict";

  // ============================================================
  // CONFIGURATION
  // ============================================================

  // Your chatbot frontend
  // Change this ONLY if index.html is hosted somewhere else.
  var CHATBOT_URL =
    "https://chatbot.rozzgaar.in/index.html";

  // ============================================================
  // PREVENT DUPLICATE CHATBOT
  // ============================================================

  if (window.__ROZZGAAR_SAARTHI_EMBED__) {
    return;
  }

  window.__ROZZGAAR_SAARTHI_EMBED__ = true;

  // ============================================================
  // CSS
  // ============================================================

  var style = document.createElement("style");

  style.id = "rozzgaar-saarthi-embed-style";

  style.textContent = `
    #rzg-embed-launcher {
      position: fixed;
      right: 22px;
      bottom: 22px;

      width: 62px;
      height: 62px;

      border: 0;
      border-radius: 50%;

      background: #111827;
      color: #ffffff;

      font-size: 28px;
      line-height: 1;

      cursor: pointer;

      display: flex;
      align-items: center;
      justify-content: center;

      z-index: 2147483646;

      box-shadow:
        0 10px 30px rgba(0, 0, 0, 0.25);

      transition:
        transform 0.2s ease,
        box-shadow 0.2s ease;
    }

    #rzg-embed-launcher:hover {
      transform: translateY(-2px);

      box-shadow:
        0 14px 35px rgba(0, 0, 0, 0.30);
    }

    #rzg-embed-launcher:active {
      transform: scale(0.95);
    }

    #rzg-embed-frame {
      position: fixed;

      right: 22px;
      bottom: 22px;

      width: min(420px, calc(100vw - 24px));
      height: min(720px, calc(100vh - 36px));

      border: 0;
      border-radius: 20px;

      background: transparent;

      z-index: 2147483645;

      display: none;

      overflow: hidden;

      box-shadow:
        0 18px 60px rgba(0, 0, 0, 0.28);
    }

    @media (max-width: 600px) {

      #rzg-embed-frame {
        position: fixed;

        top: 0;
        right: 0;
        bottom: 0;
        left: 0;

        width: 100vw;
        height: 100vh;

        border-radius: 0;

        box-shadow: none;
      }

      #rzg-embed-launcher {
        right: 16px;
        bottom: 16px;

        width: 58px;
        height: 58px;
      }
    }
  `;

  document.head.appendChild(style);

  // ============================================================
  // CREATE CHATBOT BUTTON
  // ============================================================

  var launcher = document.createElement("button");

  launcher.type = "button";

  launcher.id = "rzg-embed-launcher";

  launcher.setAttribute(
    "aria-label",
    "Open Rozzgaar Saarthi"
  );

  launcher.setAttribute(
    "title",
    "Chat with Saarthi"
  );

  launcher.innerHTML = "💬";

  document.body.appendChild(launcher);

  // ============================================================
  // CREATE CHATBOT IFRAME
  // ============================================================

  var frame = document.createElement("iframe");

  frame.id = "rzg-embed-frame";

  frame.title = "Rozzgaar Saarthi Chatbot";

  frame.setAttribute(
    "allow",
    "microphone"
  );

  frame.setAttribute(
    "allowtransparency",
    "true"
  );

  frame.setAttribute(
    "loading",
    "eager"
  );

  frame.setAttribute(
    "referrerpolicy",
    "strict-origin-when-cross-origin"
  );

  // Tell the chatbot that it is embedded
  frame.src =
    CHATBOT_URL +
    "?embedded=1";

  document.body.appendChild(frame);

  // ============================================================
  // OPEN / CLOSE
  // ============================================================

  var opened = false;

  function openChat() {

    opened = true;

    frame.style.display = "block";

    launcher.style.display = "none";
  }

  function closeChat() {

    opened = false;

    frame.style.display = "none";

    launcher.style.display = "flex";
  }

  function toggleChat() {

    if (opened) {
      closeChat();
    } else {
      openChat();
    }
  }

  // ============================================================
  // BUTTON CLICK
  // ============================================================

  launcher.addEventListener(
    "click",
    toggleChat
  );

  // ============================================================
  // CHATBOT → WEBSITE COMMUNICATION
  // ============================================================

  window.addEventListener(
    "message",
    function (event) {

      // Security:
      // Only accept messages from our chatbot iframe.
      if (
        event.source !==
        frame.contentWindow
      ) {
        return;
      }

      var data = event.data || {};

      // Chatbot asks to minimize
      if (
        data.type ===
        "ROZZGAAR_CHATBOT_MINIMIZE"
      ) {
        closeChat();
      }

      // Chatbot asks to open
      if (
        data.type ===
        "ROZZGAAR_CHATBOT_OPEN"
      ) {
        openChat();
      }

    }
  );

  // ============================================================
  // OPTIONAL JAVASCRIPT API
  // ============================================================

  window.RozzgaarSaarthi = {

    open: function () {
      openChat();
    },

    close: function () {
      closeChat();
    },

    toggle: function () {
      toggleChat();
    }

  };

  // ============================================================
  // DEBUG MESSAGE
  // ============================================================

  console.log(
    "[Rozzgaar Saarthi] Chatbot embed loaded successfully."
  );

})();

