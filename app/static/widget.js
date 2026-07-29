/* DHI Bot — einbettbares Chat-Widget.
 * Einbau auf einer Website:
 *   <script src="https://BOT-DOMAIN/widget.js" data-api="https://BOT-DOMAIN" defer></script>
 * Ohne data-api wird der Origin verwendet, von dem widget.js geladen wurde.
 */
(() => {
  const scriptEl = document.currentScript;
  const API = (scriptEl && scriptEl.dataset.api) || (scriptEl ? new URL(scriptEl.src).origin : "");

  const SUGGESTIONS = [
    "Wann ist der nächste Termin für Stufe 1+2?",
    "Was kostet die Hypnoseausbildung?",
    "Was ist der Unterschied zwischen DHI 1.0 und 2.0?",
    "Wie kann ich mich beraten lassen?",
  ];

  const host = document.createElement("div");
  host.id = "dhi-bot-widget";
  document.body.appendChild(host);
  const root = host.attachShadow({ mode: "open" });

  root.innerHTML = `
  <style>
    :host { all: initial; }
    * { box-sizing: border-box; font-family: -apple-system, "Segoe UI", Roboto, Arial, sans-serif; }
    .btn {
      position: fixed; right: 20px; bottom: 20px; z-index: 999999;
      width: 60px; height: 60px; border-radius: 50%; border: none; cursor: pointer;
      background: #1d3557; color: #fff; font-size: 26px;
      box-shadow: 0 4px 14px rgba(0,0,0,.25); transition: transform .15s;
    }
    .btn:hover { transform: scale(1.06); }
    .panel {
      position: fixed; right: 20px; bottom: 92px; z-index: 999999;
      width: 370px; max-width: calc(100vw - 32px); height: 540px; max-height: calc(100vh - 120px);
      background: #fff; border-radius: 14px; box-shadow: 0 10px 40px rgba(0,0,0,.28);
      display: none; flex-direction: column; overflow: hidden;
    }
    .panel.open { display: flex; }
    .head { background: #1d3557; color: #fff; padding: 14px 16px; }
    .head b { font-size: 15px; }
    .head small { display: block; opacity: .75; font-size: 11px; margin-top: 2px; }
    .msgs { flex: 1; overflow-y: auto; padding: 14px; background: #f4f6f8; position: relative; }
    .m { max-width: 85%; margin-bottom: 10px; padding: 9px 12px; border-radius: 12px;
         font-size: 13.5px; line-height: 1.45; white-space: pre-wrap; word-wrap: break-word; }
    .m.user { background: #1d3557; color: #fff; margin-left: auto; border-bottom-right-radius: 4px; }
    .m.bot  { background: #fff; color: #222; border: 1px solid #e3e7ec; border-bottom-left-radius: 4px; }
    .m.bot a { color: #1d6fb5; word-break: break-all; }
    .m.bot a.btnlink { display: inline-block; background: #1d3557; color: #fff;
      text-decoration: none; padding: 7px 13px; border-radius: 8px; font-size: 12.5px;
      font-weight: 600; margin: 6px 4px 2px 0; word-break: normal; }
    .m.bot a.btnlink:hover { background: #2a4d80; }
    .chips { padding: 0 14px 8px; background: #f4f6f8; display: flex; flex-wrap: wrap; gap: 6px; }
    .chip { border: 1px solid #b9c4d0; background: #fff; border-radius: 14px; padding: 5px 10px;
            font-size: 12px; cursor: pointer; color: #1d3557; }
    .chip:hover { background: #e8eef5; }
    .inp { display: flex; border-top: 1px solid #e3e7ec; background: #fff; }
    .inp textarea { flex: 1; border: none; resize: none; padding: 12px; font-size: 13.5px;
                    outline: none; height: 46px; }
    .inp button { border: none; background: none; color: #1d3557; font-size: 20px;
                  padding: 0 14px; cursor: pointer; }
    .foot { font-size: 10px; color: #8a94a0; text-align: center; padding: 5px 10px 7px; background: #fff; }
    .typing { display: inline-block; } .typing i { animation: b 1.2s infinite; font-style: normal; }
    .typing i:nth-child(2) { animation-delay: .2s; } .typing i:nth-child(3) { animation-delay: .4s; }
    @keyframes b { 0%,60%,100% { opacity:.25 } 30% { opacity:1 } }
  </style>
  <button class="btn" title="Chat öffnen">💬</button>
  <div class="panel" role="dialog" aria-label="DHI Chat-Assistent">
    <div class="head">
      <b>DHI-Assistent</b>
      <small>Beantwortet Fragen zu Ausbildung, Terminen &amp; Buchung</small>
    </div>
    <div class="msgs"></div>
    <div class="chips"></div>
    <div class="inp">
      <textarea placeholder="Ihre Frage…" rows="1" maxlength="1500"></textarea>
      <button title="Senden">➤</button>
    </div>
    <div class="foot">KI-Assistent · Antworten automatisiert &amp; ohne Gewähr · bitte keine sensiblen Gesundheitsdaten eingeben</div>
  </div>`;

  const btn = root.querySelector(".btn");
  const panel = root.querySelector(".panel");
  const msgs = root.querySelector(".msgs");
  const chips = root.querySelector(".chips");
  const ta = root.querySelector("textarea");
  const send = root.querySelector(".inp button");

  const history = [];
  let busy = false;

  const esc = (s) => s.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  // Mini-Renderer: [Beschriftung](URL) und nackte URLs werden zu Button-Links,
  // dazu **fett**, #-Ueberschriften und Listen — falls das Modell Markdown nutzt.
  const btnLabel = (u) => {
    if (u.includes("dhi2.de")) return "Jetzt Termin buchen";
    if (u.includes("wa.me")) return "WhatsApp öffnen";
    if (u.includes("seminarkalender")) return "Zum Seminarkalender";
    if (u.includes("kontakt")) return "Zur Kontaktseite";
    return "Mehr erfahren";
  };
  const render = (s) => {
    const btns = [];
    const mkBtn = (url, label) => {
      btns.push('<a class="btnlink" href="' + url + '" target="_blank" rel="noopener">' + label + "</a>");
      return "@@B" + (btns.length - 1) + "@@";
    };
    let h = esc(s);
    // [Label](URL) als Button
    h = h.replace(/\[([^\]\n]{1,60})\]\((https?:\/\/[^\s)]+)\)/g, (m, l, u) => mkBtn(u, l));
    // nackte URLs als Button mit Standard-Beschriftung (Satzzeichen am Ende abtrennen)
    h = h.replace(/(https?:\/\/[^\s<»«")]+)/g, (m) => {
      const u = m.replace(/[.,:;!?]+$/, "");
      return mkBtn(u, btnLabel(u)) + m.slice(u.length);
    });
    h = h.replace(/\*\*([^*\n]+)\*\*/g, "<b>$1</b>");
    h = h.replace(/^#{1,6}[ \t]*(.+)$/gm, "<b>$1</b>");
    h = h.replace(/^[ \t]*[-*•][ \t]+/gm, " • ");
    h = h.replace(/@@B(\d+)@@/g, (m, i) => btns[+i]);
    return h;
  };

  function add(role, html) {
    const d = document.createElement("div");
    d.className = "m " + role;
    d.innerHTML = html;
    msgs.appendChild(d);
    msgs.scrollTop = msgs.scrollHeight;
    return d;
  }

  function renderChips() {
    chips.innerHTML = "";
    SUGGESTIONS.forEach((q) => {
      const c = document.createElement("button");
      c.className = "chip";
      c.textContent = q;
      c.onclick = () => { ta.value = q; submit(); };
      chips.appendChild(c);
    });
  }

  async function submit() {
    const text = ta.value.trim();
    if (!text || busy) return;
    busy = true;
    chips.innerHTML = "";
    ta.value = "";
    add("user", esc(text));
    const wait = add("bot", '<span class="typing"><i>●</i> <i>●</i> <i>●</i></span>');
    try {
      const r = await fetch(API + "/api/chat", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ message: text, history }),
      });
      const data = await r.json();
      const reply = r.ok ? (data.reply || "(leere Antwort)") : (data.detail || "Fehler " + r.status);
      wait.innerHTML = render(reply);
      if (r.ok) {
        history.push({ role: "user", content: text }, { role: "assistant", content: reply });
        if (history.length > 12) history.splice(0, history.length - 12);
      }
    } catch (e) {
      wait.innerHTML = "Verbindung fehlgeschlagen — läuft der Bot-Server? (" + esc(String(e)) + ")";
    }
    busy = false;
    // Zum ANFANG der neuen Antwort scrollen, nicht ans Ende
    msgs.scrollTop = Math.max(0, wait.offsetTop - 10);
  }

  btn.onclick = () => {
    panel.classList.toggle("open");
    if (panel.classList.contains("open") && !msgs.childElementCount) {
      add("bot", "Schön, dass Sie da sind! Ich bin der digitale Ausbildungsberater des DHI " +
        "und helfe Ihnen gern bei Ausbildungswahl, Terminen, Preisen und Buchung. " +
        "Was möchten Sie wissen?");
      renderChips();
    }
    if (panel.classList.contains("open")) ta.focus();
  };
  send.onclick = submit;
  ta.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); submit(); }
  });
})();
