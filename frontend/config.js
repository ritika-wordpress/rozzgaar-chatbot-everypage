const CONFIG = {
    get API_BASE_URL() {
        return 'https://rozzgaar.in/apis';
    },

    get OPEN_KEY() {
        return 'rzg_open_9f3c7b1a2e4d6f8091b2c3d4e5f60718';
    },

    get CHAT_URL() {
        return 'http://127.0.0.1:8000/chat';

    },

    get TTS_URL() {
        return 'http://127.0.0.1:8000/tts/speak';

    },

    get REDIRECT_URL() {
        return 'https://rozzgaar.in/applicant/';
    },

    // Cross-origin handoff: chatbot.rozzgaar.in can't write to rozzgaar.in's
    // localStorage directly, so a successful login sends the browser to this
    // same-origin PHP page instead, carrying a one-time ticket. See
    // rozzgaar.in's handoff.php and the backend's /internal/redeem-ticket.
    get HANDOFF_URL() {
        return 'https://rozzgaar.in/chatbot-login.php';
    },

    get LOGIN_URL() {
        return 'https://rozzgaar.in/login';
    },

    get REGISTER_URL() {
        return 'https://rozzgaar.in/register';
    },

    EXCLUDED_PAGES: [
        {
            path: '/applicant/course-content',
            params: { slug: 'green-jobs-edp' }
        }
    ],

    isExcludedPage() {
        let loc;

        try {
            loc = window.top.location;
        } catch (e) {
            loc = window.location;
        }

        const currentParams = new URLSearchParams(loc.search);

        return this.EXCLUDED_PAGES.some(({ path, params }) => {
            if (loc.pathname !== path) {
                return false;
            }

            if (!params) {
                return true;
            }

            return Object.entries(params).every(
                ([key, value]) => currentParams.get(key) === value
            );
        });
    }
};

if (typeof window !== 'undefined') {
    window.CONFIG = CONFIG;
}

if (typeof module !== 'undefined' && module.exports) {
    module.exports = CONFIG;
}