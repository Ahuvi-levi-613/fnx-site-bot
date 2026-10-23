// Voice dictation for the chat input (Hebrew), using the browser's built-in
// speech recognition (Chrome / Edge). No backend involved.
//
// Usage: add <script src="/static/dictation.js" defer></script> to the page.
// It attaches a mic button next to the chat input. To pick the input
// explicitly, mark it with data-dictation; otherwise the first text
// input / textarea inside a <form> is used.
//
// Behavior:
// - Click the mic: a short tone plays and recording starts. A live sound
//   wave shows next to the text while recording.
// - Recording keeps going through short pauses; it stops when the user
//   clicks the mic again, or after 10 seconds with no speech (another
//   tone plays).
// - The dictated text is placed in the input; the user reviews it and
//   presses send. Nothing is sent automatically.
//
// Styling hooks: .dictation-btn, .dictation-btn.recording, .dictation-wave
(function () {
  "use strict";

  const Recognition = window.SpeechRecognition || window.webkitSpeechRecognition;
  if (!Recognition) return; // unsupported browser: no button at all

  const MIC_SVG =
    '<svg viewBox="0 0 24 24" width="20" height="20" aria-hidden="true" fill="none" ' +
    'stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round">' +
    '<rect x="9" y="2" width="6" height="12" rx="3"/>' +
    '<path d="M5 10v1a7 7 0 0 0 14 0v-1"/><line x1="12" y1="18" x2="12" y2="22"/></svg>';

  const LISTENING = "מקשיב...";
  const IDLE_LABEL = "הכתבה קולית";
  const STOP_LABEL = "עצירת הקלטה";
  const BARS = 28; // bars in the wave
  const WAVE_STEP_MS = 70; // how often the wave shifts by one bar
  const SILENCE_STOP_MS = 10000; // auto-stop after this long with no speech

  const ERRORS = {
    "not-allowed": "אין הרשאה למיקרופון. אפשר לאשר אותה בהגדרות הדפדפן.",
    "service-not-allowed": "אין הרשאה למיקרופון. אפשר לאשר אותה בהגדרות הדפדפן.",
    "audio-capture": "לא נמצא מיקרופון.",
    "network": "שירות זיהוי הדיבור לא זמין כרגע (בעיית רשת).",
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
      ".dictation-btn.recording{background:var(--accent,#E8541E);color:#fff}" +
      ".dictation-wave{display:none;align-items:center;gap:2px;height:24px;" +
      "flex-shrink:0;margin-inline:6px;margin-bottom:10px;direction:ltr}" +
      ".dictation-wave.on{display:flex}" +
      ".dictation-wave i{display:block;width:2px;height:2px;border-radius:1px;" +
      "background:var(--muted,#5A6478);transition:height 60ms linear}";
    // Prepend so the page's own CSS can override these defaults.
    document.head.prepend(style);
  }

  // ---------- sounds (generated, no audio files) ----------
  let audioCtx = null;

  function getAudioCtx() {
    const Ctx = window.AudioContext || window.webkitAudioContext;
    if (!Ctx) return null;
    if (!audioCtx) audioCtx = new Ctx();
    if (audioCtx.state === "suspended") audioCtx.resume();
    return audioCtx;
  }

  // Two quick soft tones: rising for start, falling for stop.
  function chime(rising) {
    const ctx = getAudioCtx();
    if (!ctx) return;
    const notes = rising ? [660, 880] : [880, 660];
    const t0 = ctx.currentTime;
    notes.forEach((freq, i) => {
      const osc = ctx.createOscillator();
      const gain = ctx.createGain();
      osc.type = "sine";
      osc.frequency.value = freq;
      const start = t0 + i * 0.09;
      gain.gain.setValueAtTime(0, start);
      gain.gain.linearRampToValueAtTime(0.12, start + 0.015);
      gain.gain.exponentialRampToValueAtTime(0.001, start + 0.12);
      osc.connect(gain).connect(ctx.destination);
      osc.start(start);
      osc.stop(start + 0.13);
    });
  }

  // ---------- live wave (mic level) ----------
  function createWave() {
    const el = document.createElement("div");
    el.className = "dictation-wave";
    el.setAttribute("aria-hidden", "true");
    const bars = [];
    for (let i = 0; i < BARS; i++) {
      const b = document.createElement("i");
      el.appendChild(b);
      bars.push(b);
    }

    let stream = null;
    let source = null;
    let analyser = null;
    let timer = null;
    const levels = new Array(BARS).fill(0);

    function draw() {
      bars.forEach((b, i) => {
        b.style.height = Math.max(2, Math.round(levels[i] * 22)) + "px";
      });
    }

    function tick() {
      let level = 0;
      if (analyser) {
        const data = new Uint8Array(analyser.fftSize);
        analyser.getByteTimeDomainData(data);
        let sum = 0;
        for (let i = 0; i < data.length; i++) {
          const v = (data[i] - 128) / 128;
          sum += v * v;
        }
        // RMS, boosted so normal speech fills the bar height.
        level = Math.min(1, Math.sqrt(sum / data.length) * 5);
        if (level < 0.06) level = 0; // quiet -> flat dot
      }
      levels.shift();
      levels.push(level);
      draw();
    }

    async function start() {
      levels.fill(0);
      draw();
      el.classList.add("on");
      timer = setInterval(tick, WAVE_STEP_MS);
      // A second, read-only mic stream just for the level meter. If it
      // fails, dictation still works and the wave stays flat.
      try {
        const ctx = getAudioCtx();
        if (!ctx || !navigator.mediaDevices) return;
        stream = await navigator.mediaDevices.getUserMedia({ audio: true });
        if (!timer) {
          // stopped while waiting for permission
          stream.getTracks().forEach((t) => t.stop());
          stream = null;
          return;
        }
        source = ctx.createMediaStreamSource(stream);
        analyser = ctx.createAnalyser();
        analyser.fftSize = 512;
        source.connect(analyser);
      } catch (e) {
        // no level meter; ignore
      }
    }

    function stop() {
      clearInterval(timer);
      timer = null;
      el.classList.remove("on");
      if (source) source.disconnect();
      if (stream) stream.getTracks().forEach((t) => t.stop());
      source = null;
      analyser = null;
      stream = null;
    }

    return { el, start, stop };
  }

  // ---------- setup ----------
  function setup() {
    const input = findInput();
    if (!input) return;

    addDefaultStyle();

    // Silence is measured by recognized words, not mic level, so
    // background noise does not keep the recording alive.
    let lastSound = 0; // last time words were recognized
    let silenceTimer = null;
    const wave = createWave();
    input.insertAdjacentElement("afterend", wave.el);

    const btn = document.createElement("button");
    btn.type = "button"; // never submits the form
    btn.className = "dictation-btn";
    btn.innerHTML = MIC_SVG;
    btn.title = IDLE_LABEL;
    btn.setAttribute("aria-label", IDLE_LABEL);
    btn.setAttribute("aria-pressed", "false");
    wave.el.insertAdjacentElement("afterend", btn);

    const rec = new Recognition();
    rec.lang = "he-IL";
    rec.interimResults = true;
    rec.continuous = true; // keep going through pauses
    rec.maxAlternatives = 1;

    let wantOn = false; // the user wants recording on (until they click stop)
    let committed = ""; // input text + final text from earlier recognition sessions
    let sessionFinal = ""; // final text from the current recognition session
    let skipBefore = 0; // results of this session already sent/deleted by the user
    let lastWritten = ""; // what we last put in the input
    let placeholder = input.placeholder;
    let quickFails = 0; // sessions that ended right after starting
    let sessionStart = 0;

    function join(a, b) {
      if (!a) return b;
      if (!b) return a;
      return a.endsWith(" ") ? a + b : a + " " + b;
    }

    function setInput(text) {
      input.value = text;
      lastWritten = text;
      // Let any framework / listener notice the change.
      input.dispatchEvent(new Event("input", { bubbles: true }));
    }

    function setButton(on) {
      btn.classList.toggle("recording", on);
      const label = on ? STOP_LABEL : IDLE_LABEL;
      btn.title = label;
      btn.setAttribute("aria-label", label);
      btn.setAttribute("aria-pressed", String(on));
    }

    function startSession() {
      sessionFinal = "";
      skipBefore = 0;
      sessionStart = Date.now();
      try {
        rec.start();
      } catch (e) {
        // already running; ignore
      }
    }

    function begin() {
      wantOn = true;
      quickFails = 0;
      committed = input.value.trim();
      lastWritten = input.value;
      placeholder = input.placeholder;
      input.placeholder = LISTENING;
      // Keep focus in the input so the page's rotating placeholder pauses.
      input.focus();
      setButton(true);
      chime(true);
      wave.start();
      lastSound = Date.now();
      silenceTimer = setInterval(() => {
        if (Date.now() - lastSound >= SILENCE_STOP_MS) finish();
      }, 500);
      startSession();
    }

    // Stop everything. msg: optional error shown in the input for a few seconds.
    function finish(msg) {
      if (!wantOn) return;
      wantOn = false;
      clearInterval(silenceTimer);
      silenceTimer = null;
      setButton(false);
      wave.stop();
      chime(false);
      try {
        rec.stop();
      } catch (e) {
        // not running; ignore
      }
      input.placeholder = msg || placeholder;
      if (msg) {
        setTimeout(() => {
          if (!wantOn && input.placeholder === msg) input.placeholder = placeholder;
        }, 4000);
      }
      input.focus();
    }

    rec.onresult = (event) => {
      // Late results after stop are dropped, so sent text never comes back.
      if (!wantOn) return;
      lastSound = Date.now();
      // The user sent, cleared or edited the text: start from what is there
      // now and drop the words already shown before that.
      if (input.value !== lastWritten) {
        committed = input.value.trim();
        skipBefore = event.resultIndex;
      }
      let finalText = "";
      let interim = "";
      for (let i = skipBefore; i < event.results.length; i++) {
        const r = event.results[i];
        if (r.isFinal) finalText += r[0].transcript;
        else interim += r[0].transcript;
      }
      sessionFinal = finalText.trim();
      setInput(join(join(committed, sessionFinal), interim.trim()));
    };

    rec.onerror = (event) => {
      // Silence and our own stop are not errors; the session just restarts.
      if (event.error === "no-speech" || event.error === "aborted") return;
      finish(ERRORS[event.error] || "ההכתבה נכשלה. נסו שוב.");
    };

    rec.onend = () => {
      committed = join(committed, sessionFinal);
      sessionFinal = "";
      if (!wantOn) return;
      // The browser ended the session on its own (e.g. long silence):
      // restart, unless it keeps failing right away.
      quickFails = Date.now() - sessionStart < 1000 ? quickFails + 1 : 0;
      if (quickFails >= 3) {
        finish("ההכתבה נכשלה. נסו שוב.");
        return;
      }
      startSession();
    };

    btn.addEventListener("click", () => {
      if (wantOn) finish();
      else begin();
    });

    // Sending the message ends the recording.
    if (input.form) input.form.addEventListener("submit", () => finish());
  }

  if (document.readyState === "loading") {
    document.addEventListener("DOMContentLoaded", setup);
  } else {
    setup();
  }
})();
