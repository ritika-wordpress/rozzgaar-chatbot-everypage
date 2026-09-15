// ===================== Widget Root =====================
// When this file is loaded directly on index.html, ROZZGAAR_ROOT is just
// `document`, same as always. When embed.js mounts the widget into a
// Shadow DOM on a host page (to keep styles isolated, no iframe), it sets
// window.ROZZGAAR_WIDGET_ROOT to that shadow root *before* this script
// runs, and every getElementById lookup below resolves within it instead.
const ROZZGAAR_ROOT = window.ROZZGAAR_WIDGET_ROOT || document;

// ===================== Configuration =====================
// Load config
// NOTE: named APP_CONFIG, not CONFIG — config.js already declares a global
// `const CONFIG`, and index.html loads both config.js and this file as
// separate <script> tags that share one global scope. A second top-level
// `const CONFIG` here throws "Identifier 'CONFIG' has already been declared",
// which silently aborts this entire file before anything gets wired up.
const APP_CONFIG = window.CONFIG || {
    API_BASE_URL: 'https://rozzgaar.in/apis',
    OPEN_KEY: 'rzg_open_9f3c7b1a2e4d6f8091b2c3d4e5f60718',
    CHAT_URL: 'http://localhost:8000/chat',
    TTS_URL: 'http://localhost:8000/tts/speak',
    REDIRECT_URL: 'https://rozzgaar.in/applicant/',
    HANDOFF_URL: 'https://rozzgaar.in/chatbot-login.php',
    LOGIN_URL: 'https://rozzgaar.in/login'
};

const API_CONFIG = {
    BASE_URL: APP_CONFIG.API_BASE_URL,
    OPEN_KEY: APP_CONFIG.OPEN_KEY,
    CHAT_URL: APP_CONFIG.CHAT_URL,
    TTS_URL: APP_CONFIG.TTS_URL,
    REDIRECT_URL: APP_CONFIG.REDIRECT_URL,
    HANDOFF_URL: APP_CONFIG.HANDOFF_URL,
    LOGIN_URL: APP_CONFIG.LOGIN_URL
};


// ===================== Page Exclusion Check =====================

(function () {

    if (
        window.CONFIG &&
        typeof window.CONFIG.isExcludedPage === "function" &&
        window.CONFIG.isExcludedPage()
    ) {

        const launcher =
            ROZZGAAR_ROOT.getElementById("launcherBtn");

        const appEl =
            ROZZGAAR_ROOT.getElementById("app");

        if (launcher)
            launcher.style.display = "none";

        if (appEl)
            appEl.style.display = "none";

        return;
    }


    // ===================== DOM Elements =====================

    const chat =
        ROZZGAAR_ROOT.getElementById("chat");

    const form =
        ROZZGAAR_ROOT.getElementById("composer");

    const input =
        ROZZGAAR_ROOT.getElementById("input");

    const statusEl =
        ROZZGAAR_ROOT.getElementById("status");

    const statusTextEl =
        ROZZGAAR_ROOT.getElementById("statusText");

    const brandNameEl =
        ROZZGAAR_ROOT.getElementById("brandName");

    const micBtn =
        ROZZGAAR_ROOT.getElementById("micBtn");

    const sendBtn =
        ROZZGAAR_ROOT.getElementById("sendBtn");

    const launcherBtn =
        ROZZGAAR_ROOT.getElementById("launcherBtn");

    const minimizeBtn =
        ROZZGAAR_ROOT.getElementById("minimizeBtn");

    const stopSpeakingBtn =
        ROZZGAAR_ROOT.getElementById("stopSpeakingBtn");

    const appEl =
        ROZZGAAR_ROOT.getElementById("app");


    // Persistent top actions
    const stickyLoginBtn =
        ROZZGAAR_ROOT.getElementById("stickyLoginBtn");

    const stickyRegisterBtn =
        ROZZGAAR_ROOT.getElementById("stickyRegisterBtn");

    const stickyExploreBtn =
        ROZZGAAR_ROOT.getElementById("stickyExploreBtn");


    // ===================== App State =====================

    let isOpen = false;

    let isVoiceEnabled = true;

    let isProcessing = false;

    let currentAudio = null;

    let ttsAbortController = null;

    // Lets the speaker button act as a real play/stop toggle: tapping it
    // while speaking stops playback; tapping it again afterwards replays
    // the same reply from the start, rather than doing nothing.
    let isSpeaking = false;

    let lastSpokenText = null;

    let lastSpokenLang = null;

    let awaitingField = null;

    let lastStateValue = null;

    let sessionId = null;

    let selectedLanguage = null;

    let languageChosen = false;

    let chosenLang = "en";

    let isLoading = false;

    let isOnline = null;

    let currentStreamController = null;


    // ===================== Embedded Mode =====================

    const isEmbedded =
        new URLSearchParams(
            window.location.search
        ).get("embedded") === "1";


    function notifyParent(type) {

        if (
            window.parent &&
            window.parent !== window
        ) {

            window.parent.postMessage(
                { type },
                "*"
            );
        }
    }


    // ===================== Payment / Enrollment =====================

    const ENROLL_CHECK_MARKER =
        "__enroll_check__";

    let awaitingPayment = false;

    let lastPaymentUrl = null;


    // ===================== Session Management =====================

    sessionId =
        sessionStorage.getItem(
            "rzg_session_id"
        );


    if (!sessionId) {

        sessionId =
            crypto.randomUUID();

        sessionStorage.setItem(
            "rzg_session_id",
            sessionId
        );
    }


    // ===================== UI Functions =====================

    function openWidget() {

        appEl.classList.add("open");

        launcherBtn.style.display = "none";

        if (languageChosen) {

            input.focus();
        }
    }


    function minimizeWidget() {

        appEl.classList.remove("open");

        launcherBtn.style.display = "flex";

        // If a reply was still streaming, snap it to full text.
        if (currentStreamController) {

            currentStreamController.skip();
        }

        // If the bot was still speaking, stop the audio instantly and
        // put the speaker button back into its default (triangle) state.
        stopSpeaking();

        if (isEmbedded) {

            notifyParent(
                "ROZZGAAR_CHATBOT_MINIMIZE"
            );
        }
    }


    if (isEmbedded) {

        launcherBtn.style.display = "none";

        openWidget();

    } else {

        launcherBtn.addEventListener(
            "click",
            openWidget
        );
    }


    minimizeBtn.addEventListener(
        "click",
        minimizeWidget
    );


    // ===================== STICKY TOP BUTTONS =====================

    function handleStickyAction(
        message,
        label
    ) {

        if (isProcessing)
            return;

        sendMessage(
            message,
            {
                displayText: label,
                hideUserBubble: false
            }
        );
    }


    if (stickyLoginBtn) {

        stickyLoginBtn.dataset.message =
            "login";

        stickyLoginBtn.addEventListener(
            "click",
            () => {

                handleStickyAction(
                    stickyLoginBtn.dataset.message,
                    stickyLoginBtn.textContent
                );
            }
        );
    }


    if (stickyRegisterBtn) {

        stickyRegisterBtn.dataset.message =
            "register";

        stickyRegisterBtn.addEventListener(
            "click",
            () => {

                handleStickyAction(
                    stickyRegisterBtn.dataset.message,
                    stickyRegisterBtn.textContent
                );
            }
        );
    }


    if (stickyExploreBtn) {

        stickyExploreBtn.dataset.message =
            "explore rozzgaar";

        stickyExploreBtn.addEventListener(
            "click",
            () => {

                handleStickyAction(
                    stickyExploreBtn.dataset.message,
                    stickyExploreBtn.textContent
                );
            }
        );
    }


    // ===================== Toast =====================

    function showToast(
        message,
        type = "info"
    ) {

        let container =
            ROZZGAAR_ROOT.getElementById(
                "toastContainer"
            );


        if (!container) {

            container =
                document.createElement(
                    "div"
                );

            container.id =
                "toastContainer";

            // ROZZGAAR_ROOT.body exists in normal (document) mode; a
            // ShadowRoot has no .body, so this falls back to appending
            // directly onto the shadow root itself in embedded mode.
            (ROZZGAAR_ROOT.body || ROZZGAAR_ROOT).appendChild(
                container
            );
        }


        const toast =
            document.createElement(
                "div"
            );

        toast.className =
            `toast toast-${type}`;

        toast.textContent =
            message;

        container.appendChild(
            toast
        );


        setTimeout(
            () => {

                toast.style.opacity =
                    "0";

                toast.style.transition =
                    "opacity 0.3s";


                setTimeout(
                    () => {

                        toast.remove();

                    },
                    300
                );

            },
            5000
        );
    }


    // ===================== Add Message =====================

    function addMessage(
        text,
        who
    ) {

        const msg =
            document.createElement(
                "div"
            );

        msg.className =
            `msg ${who}`;


        const bubble =
            document.createElement(
                "div"
            );

        bubble.className =
            "bubble";


        msg.appendChild(
            bubble
        );

        chat.appendChild(
            msg
        );


        chat.scrollTop =
            chat.scrollHeight;


        if (
            who === "bot" &&
            text
        ) {

            streamBubbleText(
                bubble,
                text
            );

        } else {

            bubble.textContent =
                text;
        }


        return msg;
    }


    // ===================== Bubble Text Streaming =====================

    // Reveal a bot reply gradually (word by word) instead of dropping the
    // whole message in at once. Minimizing the chat instantly reveals
    // the rest (see minimizeWidget()).
    function streamBubbleText(
        bubble,
        text
    ) {

        const tokens =
            text.match(/\S+\s*/g) ||
            [text];

        let i = 0;
        let finished = false;

        const controller = {

            skip() {

                if (finished) return;

                finished = true;

                bubble.textContent =
                    text;

                chat.scrollTop =
                    chat.scrollHeight;

                if (
                    currentStreamController ===
                    controller
                ) {

                    currentStreamController =
                        null;
                }
            }
        };

        currentStreamController =
            controller;

        function step() {

            if (finished) return;

            if (i >= tokens.length) {

                finished = true;

                if (
                    currentStreamController ===
                    controller
                ) {

                    currentStreamController =
                        null;
                }

                return;
            }

            bubble.textContent +=
                tokens[i];

            i += 1;

            chat.scrollTop =
                chat.scrollHeight;

            setTimeout(step, 28);
        }

        step();
    }


    // ===================== Typing Indicator =====================

    function addTyping() {

        const msg =
            document.createElement(
                "div"
            );

        msg.className =
            "msg bot typing";


        const bubble =
            document.createElement(
                "div"
            );

        bubble.className =
            "bubble";


        bubble.innerHTML = `
            <span class="dot"></span>
            <span class="dot"></span>
            <span class="dot"></span>
        `;


        msg.appendChild(
            bubble
        );

        chat.appendChild(
            msg
        );


        chat.scrollTop =
            chat.scrollHeight;


        return msg;
    }


    // ===================== Quick Replies =====================

    function addQuickReplies(options) {

        if (!options || !options.length)
            return;

        const wrap =
            document.createElement("div");

        wrap.className =
            "quick-replies";

        const buttons =
            options.map((opt) => {

                const btn =
                    document.createElement("button");

                btn.type = "button";

                btn.className =
                    "quick-reply-btn";

                btn.textContent =
                    opt.label;

                btn.addEventListener(
                    "click",
                    () => {

                        if (isProcessing)
                            return;

                        buttons.forEach(
                            (b) => (b.disabled = true)
                        );

                        sendMessage(
                            opt.message,
                            { displayText: opt.label }
                        );
                    }
                );

                wrap.appendChild(btn);

                return btn;
            });

        chat.appendChild(wrap);

        chat.scrollTop =
            chat.scrollHeight;
    }


    // ===================== Field Picker (Title / State / District) =====

    function addFieldPicker(options) {

        if (!options || !options.length)
            return;

        const wrap =
            document.createElement("div");

        wrap.className =
            "field-picker";

        const select =
            document.createElement("select");

        select.className =
            "field-picker-select";

        const placeholder =
            document.createElement("option");

        placeholder.value = "";
        placeholder.textContent =
            "Select…";
        placeholder.disabled = true;
        placeholder.selected = true;

        select.appendChild(
            placeholder
        );

        options.forEach((opt) => {

            const o =
                document.createElement("option");

            o.value = opt.value;
            o.textContent = opt.label;

            select.appendChild(o);
        });

        const btn =
            document.createElement("button");

        btn.type = "button";
        btn.className = "field-picker-btn";
        btn.textContent = "Select";
        btn.disabled = true;

        select.addEventListener(
            "change",
            () => {
                btn.disabled = !select.value;
            }
        );

        btn.addEventListener(
            "click",
            () => {

                if (isProcessing || !select.value)
                    return;

                select.disabled = true;
                btn.disabled = true;

                sendMessage(
                    select.value,
                    { displayText: select.options[select.selectedIndex].textContent }
                );
            }
        );

        wrap.appendChild(select);
        wrap.appendChild(btn);

        chat.appendChild(wrap);

        chat.scrollTop =
            chat.scrollHeight;
    }


    // ===================== Course Cards =====================

    function addCourseCards(courses, loggedIn) {

        if (!courses || !courses.length)
            return;

        const wrap =
            document.createElement("div");

        wrap.className =
            "course-cards";

        courses.forEach((course) => {

            const card =
                document.createElement("div");

            card.className =
                "course-card";

            const info =
                document.createElement("div");

            info.className =
                "course-card-info";

            const title =
                document.createElement("div");

            title.className =
                "course-card-title";

            title.textContent =
                course.title;

            info.appendChild(title);

            if (course.price) {

                const price =
                    document.createElement("div");

                price.className =
                    "course-card-price";

                price.textContent =
                    course.price;

                info.appendChild(price);
            }

            const btn =
                document.createElement("button");

            btn.type = "button";

            btn.className =
                "course-card-btn";

            btn.textContent =
                loggedIn
                    ? "Enroll"
                    : "Log in & Enroll";

            btn.addEventListener(
                "click",
                () => {

                    if (isProcessing)
                        return;

                    btn.disabled = true;

                    // Open a blank tab synchronously, inside the click
                    // handler itself — this is the only way browsers
                    // reliably allow a new-tab open. We fill in the real
                    // payment URL once the backend responds (a window
                    // opened *after* an async fetch resolves gets blocked
                    // as a popup almost everywhere, which is why Enroll
                    // could silently fail to redirect).
                    let paymentWindow = null;

                    try {
                        paymentWindow =
                            window.open("", "_blank");
                    } catch (e) {
                        // popup blocked outright — the fallback link
                        // rendered alongside the reply still works.
                    }

                    sendMessage(
                        `__enroll__${course.kind || "course"}:${course.slug}`,
                        {
                            displayText:
                                `Enroll me in "${course.title}"`,
                            paymentWindow,
                        }
                    );
                }
            );

            card.appendChild(info);
            card.appendChild(btn);

            wrap.appendChild(card);
        });

        chat.appendChild(wrap);

        chat.scrollTop =
            chat.scrollHeight;
    }


    // ===================== Payment Link Bubble =====================

    function addPaymentLink(url, status = "pending") {

        const msg =
            document.createElement("div");

        msg.className =
            "msg bot";

        const bubble =
            document.createElement("div");

        bubble.className =
            `bubble payment-bubble payment-${status}`;

        const badge =
            document.createElement("span");

        badge.className =
            `payment-badge payment-badge-${status}`;

        bubble.appendChild(badge);

        const link =
            document.createElement("a");

        link.href = url;
        link.target = "_blank";
        link.rel = "noopener";

        link.textContent =
            "Open payment page →";

        link.className =
            "payment-link";

        bubble.appendChild(link);

        msg.appendChild(bubble);

        chat.appendChild(msg);

        chat.scrollTop =
            chat.scrollHeight;

        return msg;
    }


    // ===================== Status =====================

    function setStatus(
        online
    ) {

        isOnline =
            online;


        const strings =
            t(chosenLang);


        if (statusTextEl) {

            statusTextEl.textContent =
                online
                    ? strings.online
                    : strings.offline;
        }


        statusEl.className =
            "status" +
            (
                online
                    ? " online"
                    : ""
            );
    }


    // ===================== Password Display =====================

    function displayTextFor(
        rawText
    ) {

        if (
            awaitingField === "password" ||
            awaitingField === "login_password"
        ) {

            return "•".repeat(
                Math.min(
                    rawText.length,
                    20
                )
            );
        }


        return rawText;
    }


    // ===================== Field Normalization =====================

    /**
     * Check whether the current field expects an email.
     */
    function isEmailField() {
        return (
            awaitingField === "email" ||
            awaitingField === "identifier"
        );
    }

    /**
     * Check whether the current field expects a contact / mobile number.
     */
    function isMobileField() {
        return (
            awaitingField === "mobile" ||
            awaitingField === "phone" ||
            awaitingField === "contact"
        );
    }

    /**
     * Normalize spoken/typed honorifics.
     *
     * IMPORTANT:
     * This is ONLY applied to the salutation field.
     *
     * Examples:
     *
     * mister       -> Mr
     * Mr           -> Mr
     * misses       -> Mrs
     * missus       -> Mrs
     * Mrs          -> Mrs
     * miss         -> Ms
     * Ms           -> Ms
     * doctor       -> Dr
     * Dr           -> Dr
     */
    function normalizeSalutationInput(text) {

        if (typeof text !== "string") {
            return text;
        }

        const value =
            text
                .trim()
                .replace(/[.。!?;,]+$/u, "")
                .trim()
                .toLowerCase();

        const aliases = {

            "mister": "Mr",
            "mr": "Mr",
            "mr.": "Mr",

            "misses": "Mrs",
            "missus": "Mrs",
            "mrs": "Mrs",
            "mrs.": "Mrs",

            "miss": "Ms",
            "ms": "Ms",
            "ms.": "Ms",

            "doctor": "Dr",
            "dr": "Dr",
            "dr.": "Dr"
        };

        if (aliases[value]) {
            return aliases[value];
        }

        return text
            .trim()
            .replace(/[.。!?;,]+$/u, "")
            .trim();
    }

    /**
     * Normalize spoken/typed email addresses.
     *
     * Email is ALWAYS treated as English input.
     *
     * Examples:
     *
     * john dot smith at gmail dot com
     * ->
     * john.smith@gmail.com
     */
    function normalizeEmailInput(text) {

        if (typeof text !== "string") {
            return text;
        }

        let value =
            text
                .replace(/[।!?;,]+$/u, "")
                .trim()
                .toLowerCase();

        value =
            value
                .replace(
                    /\b(?:at the rate|at rate|at sign|at the rate sign|at)\b/gi,
                    "@"
                )
                .replace(
                    /\b(?:dot|period|full stop)\b/gi,
                    "."
                )
                .replace(
                    /\b(?:underscore|under score)\b/gi,
                    "_"
                )
                .replace(
                    /\b(?:dash|hyphen)\b/gi,
                    "-"
                )
                .replace(
                    /\b(?:plus)\b/gi,
                    "+"
                );

        value =
            value.replace(/\s+/g, "");

        value =
            value
                .replace(/\.+@/g, "@")
                .replace(/@\.+/g, "@")
                .replace(/\.{2,}/g, ".")
                .replace(/^[@.]+|[@.]+$/g, "");

        return value;
    }

    /**
     * Normalize spoken/typed mobile / contact numbers so they always end
     * up as plain English (Arabic) digits before display or sending —
     * no matter whether the person typed, or spoke, in Hindi.
     *
     * Handles:
     *  - Devanagari numerals (०-९)  -> 0-9
     *  - Spoken digit words, English  ("nine", "oh")       -> 9, 0
     *  - Spoken digit words, Hindi    ("नौ", "sat", "do")  -> 9, 7, 2
     *  - Strips spaces/dashes speech recognition adds between digits
     *  - Preserves a leading "+" (country code) if present
     *
     * Examples:
     *
     * ९८७६५ ४३२१०        -> 9876543210
     * नौ आठ सात छह पांच   -> 987 65...
     * nine eight seven six five four three two one zero -> 9876543210
     * +91 98765 43210     -> +919876543210
     */
    const DEVANAGARI_DIGITS = {
        "०": "0", "१": "1", "२": "2", "३": "3", "४": "4",
        "५": "5", "६": "6", "७": "7", "८": "8", "९": "9"
    };

    const SPOKEN_DIGIT_WORDS = {
        // English
        "zero": "0", "oh": "0", "o": "0",
        "one": "1", "two": "2", "three": "3", "four": "4",
        "five": "5", "six": "6", "seven": "7", "eight": "8", "nine": "9",

        // Hindi, romanized (speech recognizers sometimes transliterate)
        "shunya": "0", "ek": "1", "do": "2", "teen": "3", "tin": "3",
        "char": "4", "chaar": "4", "paanch": "5", "panch": "5",
        "chhe": "6", "che": "6", "saat": "7", "sat": "7",
        "aath": "8", "aat": "8", "nau": "9",

        // Hindi, Devanagari script
        "शून्य": "0", "एक": "1", "दो": "2", "तीन": "3", "चार": "4",
        "पांच": "5", "पाँच": "5", "छह": "6", "छे": "6",
        "सात": "7", "आठ": "8", "नौ": "9"
    };

    function normalizeMobileInput(text) {

        if (typeof text !== "string") {
            return text;
        }

        let value =
            text.trim();

        // Devanagari digits -> plain English digits.
        value =
            value.replace(
                /[०-९]/g,
                (d) => DEVANAGARI_DIGITS[d] || d
            );

        // Spoken digit words (English or Hindi) -> digits.
        value =
            value
                .split(/\s+/)
                .map((word) => {

                    const clean =
                        word
                            .toLowerCase()
                            .replace(/[.,!?।]+$/u, "");

                    return SPOKEN_DIGIT_WORDS[clean] !== undefined
                        ? SPOKEN_DIGIT_WORDS[clean]
                        : word;
                })
                .join(" ");

        // Preserve a leading "+" (country code), strip everything else
        // that isn't a plain English digit (spaces, dashes, punctuation,
        // any leftover non-Latin characters).
        const hasCountryCode =
            /^\s*\+/.test(value);

        value =
            value.replace(/[^0-9]/g, "");

        if (hasCountryCode) {
            value = "+" + value;
        }

        return value;
    }


    // ===================== Voice Functions =====================

    function base64ToBlob(
        base64,
        mimeType
    ) {

        const byteCharacters =
            atob(base64);

        const byteNumbers =
            new Array(
                byteCharacters.length
            );


        for (
            let i = 0;
            i < byteCharacters.length;
            i++
        ) {

            byteNumbers[i] =
                byteCharacters.charCodeAt(
                    i
                );
        }


        const byteArray =
            new Uint8Array(
                byteNumbers
            );


        return new Blob(
            [byteArray],
            {
                type: mimeType
            }
        );
    }


    function setSpeakingUI(speaking) {

        isSpeaking =
            speaking;

        if (!stopSpeakingBtn)
            return;

        // Enabled as soon as there's something to (re)play, and stays
        // enabled after speech ends or is stopped — that's what lets a
        // second tap replay the same reply instead of the button going
        // dead once speech finishes.
        stopSpeakingBtn.disabled =
            !lastSpokenText;

        stopSpeakingBtn.classList.toggle(
            "speaking",
            speaking
        );
    }


    async function speak(text, lang) {

        if (!isVoiceEnabled || !text)
            return;

        text = text.trim();

        if (!text)
            return;

        // Remembered BEFORE stopSpeaking() below runs, so the button is
        // already re-enabled even while this new speech is starting up.
        lastSpokenText = text;

        lastSpokenLang = lang;

        stopSpeaking();

        ttsAbortController =
            new AbortController();

        // Backend TTS first.
        try {

            const response =
                await fetch(
                    API_CONFIG.TTS_URL,
                    {
                        method: "POST",
                        headers: {
                            "Content-Type":
                                "application/json"
                        },
                        body: JSON.stringify({
                            text: text,
                            lang: lang || "en"
                        }),
                        signal:
                            ttsAbortController.signal
                    }
                );

            if (response.ok) {

                const audioBlob =
                    await response.blob();

                if (audioBlob.size > 0) {

                    const audioUrl =
                        URL.createObjectURL(
                            audioBlob
                        );

                    currentAudio =
                        new Audio(audioUrl);

                    setSpeakingUI(true);

                    currentAudio.onended =
                        () => {

                            if (currentAudio) {
                                URL.revokeObjectURL(
                                    currentAudio.src
                                );
                            }

                            setSpeakingUI(false);
                        };

                    currentAudio.onerror =
                        () => setSpeakingUI(false);

                    await currentAudio.play();

                    return;
                }
            }

        } catch (error) {

            // Fall through to the browser fallback below,
            // unless this was an intentional stop().
            if (error?.name === "AbortError")
                return;
        }

        // Browser fallback.
        if ("speechSynthesis" in window) {

            const utterance =
                new SpeechSynthesisUtterance(
                    text
                );

            utterance.lang =
                lang === "hi"
                    ? "hi-IN"
                    : "en-IN";

            utterance.onstart =
                () => setSpeakingUI(true);

            utterance.onend =
                () => setSpeakingUI(false);

            utterance.onerror =
                () => setSpeakingUI(false);

            window.speechSynthesis.speak(
                utterance
            );
        }
    }


    function stopSpeaking() {

        if (ttsAbortController) {

            ttsAbortController.abort();

            ttsAbortController =
                null;
        }


        if (currentAudio) {

            currentAudio.pause();

            currentAudio.currentTime =
                0;

            currentAudio =
                null;
        }


        window.speechSynthesis?.cancel();

        setSpeakingUI(false);
    }


    if (stopSpeakingBtn) {

        stopSpeakingBtn.addEventListener(
            "click",
            () => {

                // Toggle: stop if currently speaking; otherwise replay the
                // last reply that was spoken, if there is one.
                if (isSpeaking) {
                    stopSpeaking();
                } else if (lastSpokenText) {
                    speak(lastSpokenText, lastSpokenLang);
                }
            }
        );
    }


    // ===================== Language =====================

    const LANG_STORAGE_KEY =
        "rzg_chat_language";


    function t(lang) {

        if (lang === "hi") {

            return {

                brandName: "सारथी",

                online: "ऑनलाइन",

                offline: "ऑफलाइन",

                quickLogin:
                    "🔑 लॉगिन",

                quickRegister:
                    "📝 रजिस्टर",

                quickExplore:
                    "📚 एक्सप्लोर"
            };
        }


        return {

            brandName: "Saarthi",

            online: "Online",

            offline: "Offline",

            quickLogin:
                "🔑 Login",

            quickRegister:
                "📝 Register",

            quickExplore:
                "📚 Explore"
        };
    }


    function applyUIStrings(
        lang = chosenLang
    ) {

        const strings =
            t(lang);


        chosenLang =
            lang;


        if (brandNameEl) {

            brandNameEl.textContent =
                strings.brandName;
        }


        if (stickyLoginBtn) {

            stickyLoginBtn.textContent =
                strings.quickLogin;
        }


        if (stickyRegisterBtn) {

            stickyRegisterBtn.textContent =
                strings.quickRegister;
        }


        if (stickyExploreBtn) {

            stickyExploreBtn.textContent =
                strings.quickExplore;
        }


        if (statusTextEl && isOnline !== null) {

            statusTextEl.textContent =
                isOnline
                    ? strings.online
                    : strings.offline;
        }


        // The toggle button always shows the language you'd switch TO,
        // not the one you're currently in.
        if (langToggleBtn) {

            const switchingTo =
                lang === "hi"
                    ? "en"
                    : "hi";

            langToggleBtn.textContent =
                switchingTo === "hi"
                    ? "हिं"
                    : "EN";

            const toggleLabel =
                switchingTo === "hi"
                    ? "Switch to Hindi"
                    : "Switch to English";

            langToggleBtn.title =
                toggleLabel;

            langToggleBtn.setAttribute(
                "aria-label",
                toggleLabel
            );
        }
    }


    function revealChatIn(
        lang,
        {
            speakGreeting = false
        } = {}
    ) {

        chosenLang =
            lang;

        languageChosen =
            true;


        applyUIStrings(
            lang
        );


        input.focus();


        /*
         * IMPORTANT:
         *
         * Welcome message has intentionally
         * been removed.
         *
         * The chatbot now opens silently.
         */


        const showReg =
            sessionStorage.getItem(
                "show_registration"
            ) === "true";


        if (showReg) {

            sessionStorage.removeItem(
                "show_registration"
            );


            sendMessage(
                "register",
                {
                    hideUserBubble: true
                }
            );
        }
    }


    // ===================== Language Toggle =====================

    const langToggleBtn =
        ROZZGAAR_ROOT.getElementById(
            "langToggleBtn"
        );


    function toggleLanguage() {

        const newLang =
            chosenLang === "hi"
                ? "en"
                : "hi";


        chosenLang =
            newLang;


        sessionStorage.setItem(
            LANG_STORAGE_KEY,
            newLang
        );


        applyUIStrings(
            newLang
        );
    }


    if (langToggleBtn) {

        langToggleBtn.addEventListener(
            "click",
            toggleLanguage
        );
    }


    // ===================== Send Message =====================

    async function sendMessage(
        text,
        opts = {}
    ) {

        if (!opts.hideUserBubble) {

            addMessage(
                opts.displayText ||
                    displayTextFor(text),
                "user"
            );
        }


        const prevAwaitingField =
            awaitingField;


        isProcessing =
            true;


        const typingEl =
            addTyping();


        try {

            const res =
                await fetch(
                    API_CONFIG.CHAT_URL,
                    {
                        method: "POST",

                        headers: {
                            "Content-Type":
                                "application/json"
                        },

                        body: JSON.stringify({
                            message: text,
                            session_id: sessionId,
                            lang: chosenLang
                        })
                    }
                );

            const data =
                await res.json();

            typingEl.remove();

            addMessage(
                data.reply,
                "bot"
            );

            if (data.reply) {

                speak(
                    data.reply,
                    data.lang || chosenLang
                );
            }


            // Store the next field requested by the backend.
            awaitingField =
                data.awaiting_field ||
                null;


            // Email / mobile fields are always handled in plain
            // English, even mid-Hindi conversation.
            const isEnglishOnlyField =
                isEmailField() ||
                isMobileField();

            input.setAttribute(
                "lang",
                isEnglishOnlyField
                    ? "en"
                    : (
                        chosenLang === "hi"
                            ? "hi"
                            : "en"
                    )
            );

            input.setAttribute(
                "spellcheck",
                isEnglishOnlyField
                    ? "false"
                    : "true"
            );

            input.setAttribute(
                "autocomplete",
                isEmailField()
                    ? "email"
                    : isMobileField()
                    ? "tel"
                    : "off"
            );

            input.setAttribute(
                "inputmode",
                isEmailField()
                    ? "email"
                    : isMobileField()
                    ? "tel"
                    : "text"
            );


            const isPasswordField =
                awaitingField === "password" ||
                awaitingField === "login_password";

            input.type =
                isPasswordField
                    ? "password"
                    : "text";


            if (
                prevAwaitingField === "state"
            ) {

                lastStateValue =
                    text;
            }


            setStatus(true);


            // ================= LOGIN SUCCESS =================

            if (
                data.redirect === "dashboard"
            ) {

                if (data.user_name) {

                    sessionStorage.setItem(
                        "rzg_user_name",
                        data.user_name
                    );
                }

                if (data.handoff_ticket) {

                    window.location.href =
                        `${API_CONFIG.HANDOFF_URL}?ticket=${encodeURIComponent(
                            data.handoff_ticket
                        )}&redirect=${encodeURIComponent(
                            API_CONFIG.REDIRECT_URL
                        )}`;

                } else {

                    window.location.href =
                        API_CONFIG.REDIRECT_URL;
                }
            }


            // ================= PAYMENT =================
            // Send the user straight to the real checkout URL the backend
            // built (rozzgaar.in/applicant/course-payment?type=...&id=...)
            // — no handoff-ticket wrapping here, since that route isn't
            // what actually lands on the correct payment page. Reuse the
            // tab we pre-opened synchronously in the Enroll click handler
            // when we have one (setting a window's location after the
            // fact is allowed even though opening a *new* one isn't), and
            // only fall back to a fresh window.open — which browsers may
            // block since we're past the original click by now — if that
            // pre-opened tab isn't available. The tappable link rendered
            // alongside the reply is the reliable fallback either way.

            if (data.payment_url) {

                awaitingPayment =
                    true;

                lastPaymentUrl =
                    data.payment_url;

                let opened =
                    false;

                if (
                    opts.paymentWindow &&
                    !opts.paymentWindow.closed
                ) {

                    try {

                        opts.paymentWindow.location.href =
                            data.payment_url;

                        opened =
                            true;

                    } catch (e) {
                        // fall through to window.open / the link below
                    }
                }

                if (!opened) {

                    window.open(
                        data.payment_url,
                        "_blank",
                        "noopener"
                    );
                }

                const paymentStatus =
                    data.reply &&
                    data.reply.includes("⚠️")
                        ? "fail"
                        : "pending";

                addPaymentLink(
                    data.payment_url,
                    paymentStatus
                );

            } else {

                if (
                    opts.paymentWindow &&
                    !opts.paymentWindow.closed
                ) {

                    opts.paymentWindow.close();
                }

                awaitingPayment =
                    false;
            }


            // ================= COURSE CARDS =================
            // Every course the backend hands back is rendered as its own
            // tappable card (with an Enroll / Log in & Enroll button) —
            // this is what makes "Explore" actually let the user act on
            // what's shown instead of just reading a text summary.

            if (data.courses && data.courses.length) {

                addCourseCards(
                    data.courses,
                    !!data.logged_in
                );
            }


            // ================= QUICK REPLIES =================
            // Menu-style options the backend offers next (Login / Register
            // / Explore / Enrollments, "I've completed payment", Yes/No,
            // etc.) — rendered as tappable buttons instead of being silently
            // dropped.

            if (data.quick_replies && data.quick_replies.length) {

                addQuickReplies(
                    data.quick_replies
                );
            }


            // ================= FIELD PICKER =================
            // For fields with a fixed/looked-up list (Title, State,
            // District during registration), show a dropdown the user can
            // pick from — on top of, not instead of, the text box below,
            // so typing the answer out by hand still works exactly as
            // before.

            if (data.field_options && data.field_options.length) {

                addFieldPicker(
                    data.field_options
                );
            }


        } catch (err) {

            typingEl.remove();

            addMessage(
                "I'm having trouble connecting right now. Please try again in a moment.",
                "bot"
            );

            setStatus(false);

        } finally {

            isProcessing =
                false;
        }
    }


    // ===================== Chat Form =====================

    form.addEventListener(
        "submit",
        async (e) => {

            e.preventDefault();


            let text =
                input.value.trim();


            if (!text)
                return;


            if (
                awaitingField === "email" ||
                awaitingField === "identifier"
            ) {

                text =
                    normalizeEmailInput(
                        text
                    );

            } else if (
                isMobileField()
            ) {

                text =
                    normalizeMobileInput(
                        text
                    );

            } else if (
                awaitingField === "salutation"
            ) {

                text =
                    normalizeSalutationInput(
                        text
                    );
            }


            input.value = "";


            sendMessage(
                text
            );
        }
    );


    // ===================== Voice Input =====================

    const SpeechRecognition =
        window.SpeechRecognition ||
        window.webkitSpeechRecognition;


    if (SpeechRecognition) {

        const recognizer =
            new SpeechRecognition();


        recognizer.continuous =
            false;

        recognizer.interimResults =
            true;

        recognizer.maxAlternatives =
            3;


        let recording =
            false;

        let finalTranscript =
            "";

        // The Web Speech API auto-stops listening after it detects a short
        // silence, and that timeout isn't configurable — restarting
        // automatically when it stops on its own (rather than the user
        // tapping the mic to end it) is the only way to give people a
        // little more time to speak, e.g. if they pause briefly to think.
        let manualStop =
            false;

        let autoRestartsLeft =
            0;

        const MAX_AUTO_RESTARTS =
            2;


        micBtn.addEventListener(
            "click",
            () => {

                if (recording) {

                    // User is deliberately ending it now — don't let
                    // onend's auto-restart kick in after this.
                    manualStop =
                        true;

                    recognizer.stop();

                    return;
                }


                stopSpeaking();


                finalTranscript =
                    "";

                manualStop =
                    false;

                autoRestartsLeft =
                    MAX_AUTO_RESTARTS;


                if (isEmailField()) {

                    recognizer.lang =
                        "en-IN";

                } else if (
                    awaitingField ===
                    "salutation"
                ) {

                    recognizer.lang =
                        "en-IN";

                } else {

                    recognizer.lang =
                        chosenLang === "hi"
                            ? "hi-IN"
                            : "en-IN";
                }


                try {

                    recognizer.start();

                    recording =
                        true;

                    micBtn.classList.add(
                        "recording"
                    );

                } catch (_) {

                    // Already running.
                }
            }
        );


        recognizer.onresult =
            (event) => {

                let interim =
                    "";


                for (
                    let i =
                        event.resultIndex;
                    i <
                        event.results.length;
                    i++
                ) {

                    const transcript =
                        event.results[i][0]
                            .transcript
                            .trim();


                    if (
                        event.results[i]
                            .isFinal
                    ) {

                        finalTranscript +=
                            (
                                finalTranscript
                                    ? " "
                                    : ""
                            ) +
                            transcript;

                    } else {

                        interim +=
                            transcript;
                    }
                }


                const liveText =
                    finalTranscript ||
                    interim;


                if (
                    isEmailField()
                ) {

                    input.value =
                        normalizeEmailInput(
                            liveText
                        );

                } else if (
                    isMobileField()
                ) {

                    input.value =
                        normalizeMobileInput(
                            liveText
                        );

                } else if (
                    awaitingField ===
                    "salutation"
                ) {

                    input.value =
                        normalizeSalutationInput(
                            liveText
                        );

                } else {

                    input.value =
                        liveText.replace(
                            /[।!?;,]+$/u,
                            ""
                        );
                }
            };


        recognizer.onerror =
            (event) => {

                if (
                    event.error !==
                        "aborted" &&
                    event.error !==
                        "no-speech"
                ) {

                    showToast(
                        "Voice input could not be understood. Please try again or type your message.",
                        "error"
                    );
                }
            };


        recognizer.onend =
            () => {

                // The browser stopped listening on its own (its internal
                // silence timeout), not because the user tapped the mic to
                // stop — restart automatically to give a bit more time to
                // speak, instead of cutting off the moment they pause.
                if (
                    !manualStop &&
                    autoRestartsLeft > 0
                ) {

                    autoRestartsLeft -= 1;

                    try {

                        recognizer.start();

                        return;

                    } catch (_) {
                        // Already running, or genuinely can't restart —
                        // fall through to the normal stop/cleanup below.
                    }
                }


                recording =
                    false;


                micBtn.classList.remove(
                    "recording"
                );


                if (finalTranscript) {

                    if (
                        isEmailField()
                    ) {

                        input.value =
                            normalizeEmailInput(
                                finalTranscript
                            );

                    } else if (
                        isMobileField()
                    ) {

                        input.value =
                            normalizeMobileInput(
                                finalTranscript
                            );

                    } else if (
                        awaitingField ===
                        "salutation"
                    ) {

                        input.value =
                            normalizeSalutationInput(
                                finalTranscript
                            );

                    } else {

                        input.value =
                            finalTranscript
                                .trim()
                                .replace(
                                    /[।!?;,]+$/u,
                                    ""
                                );
                    }
                }
            };

    } else {

        micBtn.style.display =
            "none";
    }


    // ===================== Initialize =====================

    /*
     * Chat opens directly.
     *
     * No welcome message.
     * No automatic greeting.
     * No language-selection gate.
     *
     * Previously selected language is restored.
     */

    const storedLang =
        sessionStorage.getItem(
            LANG_STORAGE_KEY
        ) || "en";


    revealChatIn(
        storedLang
    );


    // ===================== Health Check =====================

    fetch(
        API_CONFIG.CHAT_URL.replace(
            "/chat",
            "/health"
        )
    )
        .then(
            (r) =>
                r.ok
                    ? setStatus(true)
                    : setStatus(false)
        )
        .catch(
            () =>
                setStatus(false)
        );


    // ===================== Escape Key =====================

    document.addEventListener(
        "keydown",
        (e) => {

            if (
                e.key === "Escape" &&
                appEl.classList.contains(
                    "open"
                )
            ) {

                minimizeWidget();
            }
        }
    );


    // ===================== Payment Recheck =====================

    document.addEventListener(
        "visibilitychange",
        () => {

            if (
                document.visibilityState ===
                    "visible" &&
                awaitingPayment &&
                languageChosen &&
                !isProcessing
            ) {

                sendMessage(
                    ENROLL_CHECK_MARKER,
                    {
                        hideUserBubble: true
                    }
                );
            }
        }
    );


})();