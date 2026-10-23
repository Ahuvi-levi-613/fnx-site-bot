// Voice dictation for the chat input (Hebrew), using the browser's built-in
// speech recognition (Chrome / Edge). No backend involved.
//
// Usage: add <script src="/static/dictation.js" defer></script> to the page.
// It attaches a mic button next to the chat input. To pick the input
// explicitly, mark it with data-dictation; otherwise the first text
// input / textarea inside a <form> is used.
//
// The dictated text is placed in the input; the user reviews it and
// presses send. Nothing is sent automatically.
//
// Styling hooks: .dictation-btn, .dictation-btn.recording
(function () {
  "use strict";

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return; // unsupported browser: no button at all

  const MIC_SVG =
    '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="9" y="2" width="6" height="12" rx="3"/>' +
    '<path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg>';

  const ERRORS = {
    "not-allowed": "אין הרשאה למיקרופון. אפשר לאשר אותה בהגדרות הדפדפן.",
    "service-not-allowed": "אין הרשאה למיקרופון. אפשר לאשר אותה בהגדרות הדפדפן.",
    "audio-capture": "לא נמצא מיקרופון.",
    "network": "שירות זיהוי הדיבור לא זמין כרגע (בעיית רשת).",
    "no-speech": "לא נשמע דיבור. נסו שוב.",
  };

  function findInput() {
    return (
      document.querySelector("[data-dictation]") ||
      document.querySelector('form input[type="text"], form input:not([type]), form textarea')
    );
  }

  function addDefaultStyle() {
    const style = document.createElement("style");
    // Sized like the design's send button; uses its color tokens when present.
    style.textContent =
      ".dictation-btn{width:44px;height:44px;flex-shrink:0;display:grid;place-items:center;" +
      "padding:0;border:0;border-radius:12px;cursor:pointer;" +
      "background:var(--navy-tint,#E9EDF7);color:var(--navy,#16285A)}" +
      ".dictation-btn.recording{background:var(--accent,#E8541E);color:#fff;" +
      "animation:dictation-pulse 1.2s infinite}" +
      "@keyframes dictation-pulse{50%{opacity:.6}}";
    // Prepend so the page's own CSS can override these defaults.
    document.head.prepend(style);
  }

  function setup() {
    const input = findInput();
    if (!input) return;

    addDefaultStyle();
    const btn = document.createElement("button");
    btn.type = "button"; // never submits the form
    btn.className = "dictation-btn";
    btn.innerHTML = MIC_SVG;
    const idleLabel = "הכתבה קולית";
    btn.title = idleLabel;
    btn.setAttribute("aria-label", idleLabel);
    input.insertAdjacentElement("afterend", btn);

    const rec = new Recognition();
    rec.lang = "he-IL";
    rec.interimResults = true;
    rec.continuous = false; // stops by itself after a pause
    rec.maxAlternatives = 1;

    let listening = false;
    let baseText = ""; // what was in the input before dictation started
    let placeholder = input.placeholder; // refreshed on each start (page may rotate it)

    function setInput(text) {
      input.value = text;
      // Let any framework / listener notice the change.
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function setListening(on) {
      listening = on;
      btn.classList.toggle("recording", on);
      const label = on ? "עצירת הקלטה" : idleLabel;
      btn.title = label;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("aria-pressed", String(on));
      input.placeholder = on ? "מקשיב..." : placeholder;
    }

    rec.onstart = () => setListening(true);

    rec.onresult = (event) => {
      let text = "";
      for (let i = 0; i < event.results.length; i++) {
        text += event.results[i][0].transcript;
      }
      const sep = baseText && !baseText.endsWith(" ") ? " " : "";
      setInput(baseText + sep + text.trim());
    };

    rec.onerror = (event) => {
      if (event.error === "aborted") return;
      const msg = ERRORS[event.error] || "ההכתבה נכשלה. נסו שוב.";
      input.placeholder = msg;
      setTimeout(() => {
        if (!listening) input.placeholder = placeholder;
      }, 4000);
    };

    rec.onend = () => {
      const msg = input.placeholder;
      setListening(false);
      // Keep an error message visible (onerror resets it later).
      if (msg !== "מקשיב...") input.placeholder = msg;
      input.focus();
    };

    btn.addEventListener("click", () => {
      if (listening) {
        rec.stop();
        return;
      }
      baseText = input.value;
      placeholder = input.placeholder;
      // Keep focus in the input so the page's rotating placeholder pauses.
      input.focus();
      try {
        rec.start();
      } catch (e) {
        // start() throws if already running; ignore.
      }
    });
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setup);
  } else {
    setup();
  }
})();
