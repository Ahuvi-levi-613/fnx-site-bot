// Chat UI for /api/chat. Plain JS, no build step.
// Conversations are kept only in this browser (localStorage); the server stores nothing.
(function () {
  'use strict';

  const CONTACT_URL = 'https://www.fnx.co.il/customer-service/contact-us';
  const HISTORY_TURNS = 6; // how many previous turns go to the server for follow-ups
  const STORE_KEY = 'penny.chats.v1';
  const WORD_MS = 35;

  const ICON = {
    arrow: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M19 12H5"/><path d="M11 6l-6 6 6 6"/></svg>',
    ext: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M10 4H4v16h16v-6"/><path d="M14 4h6v6"/><path d="M20 4l-9 9"/></svg>',
    search: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="11" cy="11" r="7"/><path d="M21 21l-4.3-4.3"/><path d="M8.5 11h5"/></svg>',
    alert: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2.2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 8v5"/><path d="M12 16h.01"/></svg>',
    phone: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M22 16.9v3a2 2 0 0 1-2.2 2 19.8 19.8 0 0 1-8.6-3.1 19.5 19.5 0 0 1-6-6A19.8 19.8 0 0 1 2.1 4.2 2 2 0 0 1 4.1 2h3a2 2 0 0 1 2 1.7c.1.9.4 1.8.7 2.7a2 2 0 0 1-.5 2.1L8 9.8a16 16 0 0 0 6 6l1.3-1.3a2 2 0 0 1 2.1-.4c.9.3 1.8.6 2.7.7a2 2 0 0 1 1.7 2z"/></svg>',
    wa: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M21 11.5a8.4 8.4 0 0 1-12.3 7.5L3 21l2-5.6A8.4 8.4 0 1 1 21 11.5z"/></svg>',
    car: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M5 16l1.5-5.2A2 2 0 0 1 8.4 9.4h7.2a2 2 0 0 1 1.9 1.4L19 16"/><path d="M4 16h16v3H4z"/><circle cx="7.5" cy="19" r="1.5"/><circle cx="16.5" cy="19" r="1.5"/></svg>',
    home: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M3 11l9-7 9 7"/><path d="M5 10v10h14V10"/></svg>',
    plane: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M2 16l20-6-2-3-7 2-5-5-2 1 3 5-5 1.5-2-2-1.5.5z"/><path d="M3 21h18"/></svg>',
    mail: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><rect x="3" y="5" width="18" height="14" rx="2"/><path d="M3 7l9 6 9-6"/></svg>',
    clock: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></svg>',
    play: '<svg viewBox="0 0 24 24" fill="currentColor" aria-hidden="true"><path d="M17 5v14L6 12z"/></svg>',
    headset: '<svg viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="2" stroke-linecap="round" stroke-linejoin="round" aria-hidden="true"><path d="M4 14v-2a8 8 0 0 1 16 0v2"/><rect x="3" y="14" width="4" height="6" rx="1.5"/><rect x="17" y="14" width="4" height="6" rx="1.5"/></svg>'
  };

  // Example questions per area, phrased the way people actually ask.
  const CATEGORIES = [
    { key: 'car', label: 'רכב', icon: 'car', questions: [
      'איך מגישים תביעה על תאונת רכב?',
      "מה ההבדל בין ביטוח מקיף לביטוח צד ג'?",
      'נסדקה לי השמשה ברכב, איך מתקנים?'
    ] },
    { key: 'apartment', label: 'דירה', icon: 'home', questions: [
      'יש לי נזילה מהתקרה, איך מגישים תביעה?',
      'מה ההבדל בין ביטוח מבנה לביטוח תכולה?',
      'ביטוח הדירה מכסה פריצה?'
    ] },
    { key: 'travel', label: 'נסיעות לחו״ל', icon: 'plane', questions: [
      'אני טסה לאירופה עם הילדים, מה ביטוח הנסיעות מכסה?',
      'ביטוח נסיעות מכסה ביטול טיסה?',
      'המזוודה שלי לא הגיעה, מה עושים?'
    ] },
    { key: 'service', label: 'שירות לקוחות', icon: 'headset', questions: [
      'איך יוצרים קשר עם שירות הלקוחות?',
      'איך מבטלים פוליסה?',
      'אפשר לפנות אליכם בוואטסאפ?'
    ] }
  ];

  const PLACEHOLDERS = [
    'יש לי נזילה מהתקרה, איך מגישים תביעה?',
    'אפשר להוסיף נהג צעיר לביטוח הרכב?',
    'ביטוח נסיעות מכסה ביטול טיסה?',
    'מה מכסה ביטוח חובה?',
    'איך מבטלים פוליסה?'
  ];

  // Scripted walkthrough ("how Penny answers"). Texts are taken from real crawled pages; it is
  // played locally, never sent to the server and never saved as a conversation.
  const DEMO_SEEN_KEY = 'penny.demoSeen.v1';
  const PIPE = { page_title: 'נזקי צנרת | הפניקס', url: 'https://www.fnx.co.il/claims-customer-service/claims-appartment-insurance/pipeline-damage' };
  const CLAIM = { page_title: 'תביעות ביטוח דירה | הפניקס', url: 'https://www.fnx.co.il/claims-customer-service/claims-appartment-insurance/damage-to-the-apartment' };
  const DEMO = [
    { question: 'חזרתי הביתה והרצפה מלאה מים, מה עושים?', grounded: true, sources: [PIPE, CLAIM],
      answer: 'כך מגישים תביעה על נזק מים בביטוח דירה:\n' +
        '1. **מה להכין:** תמונות ממקום האירוע, וחשבונית או הצעת מחיר לתיקון. [2]\n' +
        '2. **איך מגישים:** מורידים מהאתר את טופס התביעה לנזק רכוש בדירה, ממלאים ושולחים יחד עם המסמכים. [2]\n' +
        '3. **שימו לב:** נזק לצנרת מכוסה רק אם נרכשה בפוליסה הרחבה לנזקי מים. [1]' },
    { question: 'וכמה יעלה לי ביטוח לדירת 4 חדרים?', grounded: false, sources: [],
      answer: 'מחירים לא מופיעים בדפי האתר, ולכן לא אנחש. בשירות הלקוחות יוכלו לתת הצעת מחיר:' },
    { question: 'והפוליסה שלי מכסה נזק מים?', grounded: true, sources: [PIPE],
      answer: 'את הפוליסה האישית שלך אני לא רואה, אבל אפשר להסביר מה כתוב באתר על הכיסוי:\n' +
        '- **מה מכוסה:** נזק לצנרת, ונזק למבנה או לתכולה שנגרם מהתבקעות או סתימה, אם נרכשה הרחבה לנזקי מים.\n' +
        '- **מה לא מכוסה:** עלות המים, וגם בלאי, קורוזיה וחלודה בצנרת. [1]\n' +
        'כדי לבדוק אם ההרחבה קיימת בפוליסה שלך, פנו לשירות הלקוחות.' }
  ];

  const GREETING = 'היי, אני פני. במה אפשר לעזור?';
  const LEDE = 'ספרו לי מה קרה, במילים שלכם. אני מחפשת בדפי אתר הפניקס ועונה עם קישור לדף שממנו לקחתי את התשובה.';

  // ---------- dom helpers ----------
  const $ = (id) => document.getElementById(id);
  const app = $('app'), inner = $('inner'), form = $('form'), q = $('q'), ask = $('ask'), sendBtn = $('send');
  const chatList = $('chatList');

  function h(tag, attrs, children) {
    const el = document.createElement(tag);
    if (attrs) {
      for (const k in attrs) {
        if (k === 'html') el.innerHTML = attrs[k]; // only used with the static ICON strings above
        else if (k === 'text') el.textContent = attrs[k];
        else if (k.startsWith('on')) el.addEventListener(k.slice(2), attrs[k]);
        else el.setAttribute(k, attrs[k]);
      }
    }
    (children || []).forEach((c) => { if (c) el.append(c); });
    return el;
  }
  const avatar = () => h('span', { class: 'avatar' }, [h('img', { src: '/static/favicon.ico', alt: '', width: '22', height: '22' })]);

  // ---------- storage (this browser only) ----------
  function loadChats() {
    try { return JSON.parse(localStorage.getItem(STORE_KEY)) || []; } catch (e) { return []; }
  }
  function saveChats() {
    try { localStorage.setItem(STORE_KEY, JSON.stringify(chats)); } catch (e) { /* private mode: keep in memory */ }
  }

  let chats = loadChats();
  let current = null; // the open chat object, or null for a fresh welcome screen
  let busy = false;
  let selectedCat = CATEGORIES[1].key;

  // ---------- sidebar ----------
  function dayLabel(ts) {
    const d = new Date(ts), now = new Date();
    const one = 24 * 3600 * 1000;
    const startToday = new Date(now.getFullYear(), now.getMonth(), now.getDate()).getTime();
    if (ts >= startToday) return 'היום';
    if (ts >= startToday - one) return 'אתמול';
    return d.getDate() + '.' + (d.getMonth() + 1) + '.' + d.getFullYear();
  }

  function renderList() {
    chatList.textContent = '';
    if (!chats.length) {
      chatList.append(h('p', { class: 'empty', text: 'עוד אין שיחות קודמות' }));
      return;
    }
    chats.slice().sort((a, b) => b.updated - a.updated).forEach((c) => {
      const item = h('button', { class: 'chat-item', type: 'button', onclick: () => { openChat(c.id); closeSide(); } }, [
        h('b', { text: c.title }),
        h('small', { text: dayLabel(c.updated) })
      ]);
      if (current && current.id === c.id) item.setAttribute('aria-current', 'true');
      chatList.append(item);
    });
  }

  function openSide() { app.classList.add('side-open'); $('menuBtn').setAttribute('aria-expanded', 'true'); }
  function closeSide() { app.classList.remove('side-open'); $('menuBtn').setAttribute('aria-expanded', 'false'); }

  // ---------- welcome ----------
  function renderWelcome() {
    inner.textContent = '';
    const examples = h('div', { class: 'examples' });
    const tabs = h('div', { class: 'cats', role: 'tablist', 'aria-label': 'נושאים' });

    function showCat(key) {
      selectedCat = key;
      const cat = CATEGORIES.find((c) => c.key === key);
      tabs.querySelectorAll('.cat').forEach((t) => t.setAttribute('aria-selected', String(t.dataset.key === key)));
      examples.textContent = '';
      cat.questions.forEach((text) => {
        examples.append(h('button', { class: 'ex', type: 'button', onclick: () => send(text) }, [
          h('span', { text: text }), h('span', { html: ICON.arrow, style: 'display:contents' })
        ]));
      });
    }

    CATEGORIES.forEach((c) => {
      tabs.append(h('button', { class: 'cat', type: 'button', role: 'tab', 'data-key': c.key, 'aria-selected': 'false', onclick: () => showCat(c.key) }, [
        h('span', { html: ICON[c.icon], style: 'display:contents' }), h('span', { text: c.label })
      ]));
    });

    inner.append(h('section', { class: 'welcome msg' }, [
      h('div', null, [
        h('h1', { text: GREETING }),
        h('p', { class: 'lede', text: LEDE + ' אפשר גם לבחור נושא ולהתחיל משאלה לדוגמה:' })
      ]),
      h('button', { class: 'demo-btn', type: 'button', onclick: playDemo }, [
        h('span', { class: 'play', html: ICON.play }),
        h('span', { text: 'איך פני עונה?' }),
        h('small', { text: 'הדגמה של חצי דקה' })
      ]),
      tabs,
      examples
    ]));
    showCat(selectedCat);
  }

  // ---------- answer formatting ----------
  // The server's answer is plain text, sometimes with numbered/bulleted lines, **bold** and a
  // trailing source URL. URLs are dropped from the text because sources are shown as cards.
  // A URL the model cited becomes a small "[n]" marker pointing at source card n.
  // If the answer names no URL, markers for every source go at the end.
  const normUrl = (u) => u.replace(/[.,)־]+$/, '').replace(/\/$/, '').toLowerCase();

  function cleanAnswer(text, sources) {
    sources = sources || [];
    const index = sources.map((x) => normUrl(x.url));
    let t = text
      // the model sometimes wraps a URL in brackets ("[https://...]", "[מקור: https://...]", "(https://...)"):
      // unwrap it, or a lone "[" is left next to the number
      .replace(/[[(]\s*(?:מקור\s*:?\s*)?(https?:\/\/[^\s\])]+)\s*[\])]/g, ' $1 ')
      .replace(/https?:\/\/[^\s\]]+/g, (u) => {
        const n = index.indexOf(normUrl(u));
        const tail = (u.match(/[.,)]+$/) || [''])[0]; // keep the sentence's own punctuation
        return (n >= 0 ? ' [' + (n + 1) + ']' : '') + tail;
      })
      .replace(/(\[\d+\])[ \t]+([.,])/g, '$1$2') // "[1] ." -> "[1]."
      .replace(/[ \t]+$/gm, '');
    // a short label line left at the end ("כתובת URL:"): drop it, keep its markers on the line above
    t = t.replace(/\n[ \t]*\**[^\n:[]{0,25}:\**((?:[ \t]*\[\d+\])*)[ \t]*$/, '$1');
    // markers alone on a line (anywhere): join them to the text line above, never a row of lone numbers
    t = t.replace(/\n\s*((?:\[\d+\][ \t]*)+)(?=\n|$)/g, ' $1');
    t = t.replace(/\n{3,}/g, '\n\n').trim();
    if (sources.length && !/\[\d+\]/.test(t)) t += ' ' + sources.map((x, i) => '[' + (i + 1) + ']').join(' ');
    return markersPerBlock(t);
  }

  // Source numbers go once at the end of each paragraph or list, not on every sentence/item:
  // collect a block's markers, drop them from its lines, put each number once after its last line.
  const LIST_LINE = /^\s*(?:\d+[.)]|[-*•])\s+/;
  function markersPerBlock(t) {
    const lines = t.split('\n');
    const kind = (l) => (!l.trim() ? 'blank' : LIST_LINE.test(l) ? 'list' : 'text');
    const out = [];
    let block = [], blockKind = null;
    const flush = () => {
      if (!block.length) return;
      const nums = [];
      const clean = block.map((l) => l.replace(/\s*\[(\d+)\]/g, (m, n) => {
        if (!nums.includes(n)) nums.push(n);
        return '';
      }).replace(/[ \t]+$/, ''));
      clean.forEach((l, i) => {
        // blank lines inside a list are kept as-is; numbers go on the last non-blank line
        if (i === clean.length - 1 && nums.length) l += ' ' + nums.map((n) => '[' + n + ']').join(' ');
        out.push(l);
      });
      block = []; blockKind = null;
    };
    lines.forEach((l, i) => {
      const k = kind(l);
      if (k === 'blank') {
        // a blank line between two list items keeps the list as one block
        const next = lines.slice(i + 1).find((x) => x.trim());
        if (blockKind === 'list' && next && LIST_LINE.test(next)) { block.push(l); return; }
        flush(); out.push(l); return;
      }
      if (blockKind && k !== blockKind) flush();
      block.push(l); blockKind = k;
    });
    flush();
    return out.join('\n');
  }

  function inline(parent, text) {
    text.split(/(\*\*[^*]+\*\*|\s*\[\d+\])/g).forEach((part) => {
      if (!part) return;
      const cite = part.match(/^\s*\[(\d+)\]$/);
      if (cite) parent.append(h('button', { class: 'cite', type: 'button', 'data-n': cite[1], 'aria-label': 'מקור ' + cite[1], text: cite[1] }));
      else if (part.startsWith('**') && part.endsWith('**') && part.length > 4) parent.append(h('b', { text: part.slice(2, -2) }));
      else parent.append(part.replace(/\*\*/g, ''));
    });
  }

  function formatInto(container, text) {
    container.textContent = '';
    let list = null, listType = null;
    text.split('\n').forEach((raw) => {
      const line = raw.trim();
      if (!line) { list = null; return; }
      const num = line.match(/^(\d+)[.)]\s+(.*)$/);
      const bul = line.match(/^[-*•]\s+(.*)$/);
      if (num || bul) {
        const type = num ? 'ol' : 'ul';
        if (!list || listType !== type) { list = h(type); listType = type; container.append(list); }
        const li = h('li'); const span = h('span'); inline(span, num ? num[2] : bul[1]); li.append(span); list.append(li);
      } else {
        list = null;
        const p = h('p'); inline(p, line); container.append(p);
      }
    });
  }

  function lastTextHost(container) {
    let el = container.lastElementChild;
    while (el && (el.tagName === 'OL' || el.tagName === 'UL' || el.tagName === 'LI')) el = el.lastElementChild;
    return el || container;
  }

  function sourcesBlock(sources) {
    const grid = h('div', { class: 'src-grid' });
    sources.forEach((s, i) => {
      let path = s.url;
      try { const u = new URL(s.url); path = u.host.replace(/^www\./, '') + decodeURI(u.pathname); } catch (e) { /* keep raw */ }
      grid.append(h('a', { class: 'src', 'data-n': String(i + 1), href: s.url, target: '_blank', rel: 'noopener' }, [
        h('span', { class: 'src-n', text: String(i + 1) }),
        h('span', { class: 'src-t' }, [h('b', { text: s.page_title || path }), h('small', { text: path })]),
        h('span', { html: ICON.ext, style: 'display:contents' })
      ]));
    });
    return h('div', { class: 'sources' }, [h('span', { text: 'מקורות מאתר הפניקס' }), grid]);
  }

  // ---------- messages ----------
  // The greeting stays, smaller, at the top of every conversation.
  function startThread() {
    inner.textContent = '';
    inner.append(h('section', { class: 'intro' }, [h('h2', { text: GREETING }), h('p', { text: LEDE })]));
  }

  function addUser(text) {
    inner.append(h('div', { class: 'user msg' }, [h('p', { text: text })]));
  }

  function addTyping() {
    const t = h('div', { class: 'typing msg' }, [avatar(), h('div', { class: 'dots', role: 'status', 'aria-label': 'פני מחפשת תשובה' }, [
      h('i'), h('i'), h('i'), h('span', { text: 'מחפשת בדפי האתר…' })
    ])]);
    inner.append(t);
    return t;
  }

  function addAnswer(turn, animate, cancelled) {
    const bubble = h('div', { class: 'bubble' });
    inner.append(h('div', { class: 'bot msg' }, [avatar(), bubble]));
    const text = cleanAnswer(turn.answer, turn.sources);
    const finish = () => { if (turn.sources.length) bubble.append(sourcesBlock(turn.sources)); };
    if (!animate) { formatInto(bubble, text); finish(); return Promise.resolve(); }

    // reveal word by word, keeping line breaks so lists form as they type
    const tokens = text.split(/(\s+)/);
    const caret = h('span', { class: 'caret' });
    const body = h('div', { style: 'display:contents' });
    bubble.append(body);
    return new Promise((resolve) => {
      let i = 0;
      (function tick() {
        if (cancelled && cancelled()) { resolve(); return; }
        i += 2;
        formatInto(body, tokens.slice(0, i).join(''));
        lastTextHost(body).append(caret);
        if (i < tokens.length) { setTimeout(tick, WORD_MS); return; }
        caret.remove();
        finish();
        resolve();
      })();
    });
  }

  // Contact options as listed on the site's service pages (car/apartment desk *5432, WhatsApp,
  // hours). Emails differ per topic, so they are left to the contact page linked last.
  function contactCards() {
    const ic = (name) => h('span', { html: ICON[name], style: 'display:contents' });
    const card = (href, icon, label, value, ltr, ext) => h('a', Object.assign({ class: 'ct', href: href }, ext ? { target: '_blank', rel: 'noopener' } : {}), [
      ic(icon), h('span', null, [h('small', { text: label }), h('b', ltr ? { text: value, dir: 'ltr' } : { text: value })])
    ]);
    return h('div', { class: 'contact-wrap' }, [
      h('div', { class: 'contacts' }, [
        card('tel:*5432', 'phone', 'טלפון', '*5432', true),
        card('https://wa.me/972549893455', 'wa', 'וואטסאפ', '054-9893455', true, true),
        card(CONTACT_URL, 'ext', 'באתר הפניקס', 'כל דרכי הקשר', false, true)
      ]),
      h('p', { class: 'hours' }, [ic('clock'), h('span', { text: "שעות פעילות: ימים א'-ה', 8:30-16:00" })])
    ]);
  }

  // grounded=false: either "not on the site" or a temporary outage - different titles, same contacts
  function addNotFound(turn) {
    const outage = turn.error || /תקלה/.test(turn.answer);
    const title = outage ? 'משהו השתבש לרגע' : 'את זה לא מצאתי באתר';
    const body = outage
      ? 'יש כרגע תקלה זמנית. אפשר לנסות שוב בעוד רגע, או לפנות ישירות לשירות הלקוחות:'
      : cleanAnswer(turn.answer).replace(/[.:]?\s*$/, ':');
    inner.append(h('div', { class: 'bot msg' }, [avatar(), h('div', { class: 'bubble nf' }, [
      h('div', { class: 'nf-head' }, [h('span', { class: 'nf-ico', html: outage ? ICON.alert : ICON.search }), h('span', { text: title })]),
      h('p', { text: body }),
      contactCards()
    ])]));
  }

  function renderTurn(turn, animate) {
    addUser(turn.question);
    if (turn.grounded) return addAnswer(turn, animate);
    addNotFound(turn);
    return Promise.resolve();
  }

  // ---------- navigation ----------
  // Home = welcome screen. A conversation or the demo pushes one history entry, so both the
  // "back" button and the browser's Back return home.
  let demoRun = 0; // bumping this cancels a running demo

  function showBackbar(demo) {
    $('backbar').hidden = false;
    $('demoBadge').hidden = !demo;
    if (!(history.state && history.state.penny)) history.pushState({ penny: true }, '');
  }

  function goHome() {
    if (busy) return;
    demoRun++;
    current = null;
    $('backbar').hidden = true;
    renderWelcome();
    renderList();
  }

  function back() {
    if (history.state && history.state.penny) history.back(); // popstate -> goHome
    else goHome();
  }

  // ---------- demo ----------
  const wait = (ms) => new Promise((r) => setTimeout(r, ms));

  async function playDemo() {
    if (busy) return;
    const run = ++demoRun;
    current = null;
    startThread();
    renderList();
    showBackbar(true);
    for (const turn of DEMO) {
      await wait(900);
      if (run !== demoRun) return;
      addUser(turn.question);
      await wait(400);
      const typing = addTyping();
      await wait(1400);
      typing.remove();
      if (run !== demoRun) return;
      if (turn.grounded) await addAnswer(turn, true, () => run !== demoRun);
      else addNotFound(turn);
      if (run !== demoRun) return;
    }
  }

  // ---------- chats ----------
  function newChat() {
    goHome();
    q.focus();
  }

  function openChat(id) {
    const c = chats.find((x) => x.id === id);
    if (!c || busy) return;
    demoRun++;
    current = c;
    startThread();
    c.turns.forEach((t) => renderTurn(t, false));
    showBackbar(false);
    renderList();
  }

  // Fit the input's height to its text (CSS max-height caps it, then it scrolls).
  function growInput() {
    q.style.height = 'auto';
    q.style.height = q.scrollHeight + 'px';
  }

  async function send(question) {
    question = (question || '').trim();
    if (!question || busy) return;
    busy = true; sendBtn.disabled = true; q.value = ''; growInput();

    if (!current) {
      demoRun++; // a question typed during the demo ends the demo
      current = { id: String(Date.now()), title: question.slice(0, 60), updated: Date.now(), turns: [] };
      chats.push(current);
      startThread();
      showBackbar(false);
    }
    const chat = current;
    const history = chat.turns.filter((t) => !t.error).slice(-HISTORY_TURNS).map((t) => ({ question: t.question, answer: t.answer }));

    addUser(question);
    const typing = addTyping();
    let turn;
    try {
      const res = await fetch('/api/chat', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify({ question: question, history: history })
      });
      if (!res.ok) throw new Error('HTTP ' + res.status);
      const data = await res.json();
      turn = { question: question, answer: data.answer, sources: data.sources || [], grounded: !!data.grounded };
    } catch (e) {
      turn = { question: question, answer: '', sources: [], grounded: false, error: true };
    }
    typing.remove();

    chat.turns.push(turn);
    chat.updated = Date.now();
    saveChats();
    renderList();

    if (current === chat) {
      if (turn.grounded) await addAnswer(turn, true);
      else addNotFound(turn);
    }
    busy = false; sendBtn.disabled = false;
    q.focus();
  }

  // ---------- rotating placeholder ----------
  let ph = 0;
  q.placeholder = PLACEHOLDERS[0];
  setInterval(() => {
    if (q.value || document.activeElement === q) return;
    ask.classList.add('swap');
    setTimeout(() => { ph = (ph + 1) % PLACEHOLDERS.length; q.placeholder = PLACEHOLDERS[ph]; ask.classList.remove('swap'); }, 300);
  }, 3200);

  // ---------- wiring ----------
  // a source number in the text scrolls to its card and flashes it
  inner.addEventListener('click', (e) => {
    const c = e.target.closest('.cite');
    const bubble = c && c.closest('.bubble');
    const card = bubble && bubble.querySelector('.src[data-n="' + c.dataset.n + '"]');
    if (!card) return;
    card.scrollIntoView({ behavior: 'smooth', block: 'nearest' });
    card.classList.remove('flash'); void card.offsetWidth; card.classList.add('flash');
  });
  form.addEventListener('submit', (e) => { e.preventDefault(); send(q.value); });
  // Multi-line input: Enter sends, Shift+Enter adds a line; the box grows with the text.
  q.addEventListener('keydown', (e) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.isComposing) { e.preventDefault(); form.requestSubmit(); }
  });
  q.addEventListener('input', growInput);
  $('newChat').addEventListener('click', () => { if (!busy) { newChat(); closeSide(); } });
  $('backBtn').addEventListener('click', back);
  $('homeLink').addEventListener('click', (e) => { e.preventDefault(); back(); closeSide(); });
  window.addEventListener('popstate', () => { if (!(history.state && history.state.penny)) goHome(); });
  $('menuBtn').addEventListener('click', () => (app.classList.contains('side-open') ? closeSide() : openSide()));
  $('scrim').addEventListener('click', closeSide);
  document.addEventListener('keydown', (e) => { if (e.key === 'Escape') closeSide(); });
  $('clearAll').addEventListener('click', () => {
    if (busy || !chats.length) return;
    if (!confirm('למחוק את כל השיחות השמורות בדפדפן הזה?')) return;
    chats = [];
    saveChats();
    newChat();
  });

  // first visit: play the demo once; afterwards it lives behind the "איך פני עונה?" button
  if (history.state && history.state.penny) history.replaceState(null, '');
  goHome();
  let seen = true;
  try { seen = !!localStorage.getItem(DEMO_SEEN_KEY); localStorage.setItem(DEMO_SEEN_KEY, '1'); } catch (e) { /* storage blocked: skip auto demo */ }
  if (!seen) setTimeout(() => { if (!current && !busy && $('backbar').hidden) playDemo(); }, 1200);
})();
