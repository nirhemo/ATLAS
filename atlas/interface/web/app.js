/* ATLAS HUD — frontend logic (voice-first).
 *
 * INTEGRATION POINT: talks to the FastAPI core (atlas/server/app.py) if running;
 * falls back to mock data so the dashboard always renders. Endpoints:
 *   GET  /api/status | /api/metrics | /api/memory/recent | /api/upgrade
 *   GET  /api/scheduler | /api/logs?limit=N | /api/settings
 *   PUT  /api/settings            -> persist + reload
 *   POST /api/chat {text}         -> { reply, backend }
 *   POST /api/scheduler/run/{id}  -> run a job now
 *   POST /api/backend/test        -> { ok, backend, detail }
 *   WS   /ws                      -> { type:"state", value } live voice state
 *
 * Voice uses the browser's built-in Web Speech API (Chrome/Edge): mic -> STT ->
 * /api/chat -> SpeechSynthesis reply. The native wake-word/Whisper/Kokoro
 * pipeline can replace it later without touching this contract.
 */
const API = location.origin.startsWith("http") ? "" : "http://localhost:8765";
const $ = (s, r = document) => r.querySelector(s);
const setText = (root, k, v) => { const el = root.querySelector(`[data-k="${k}"]`); if (el) el.textContent = v; };

/* Friendly short model name for the System panel: drops provider prefixes and
   ":free" suffixes, prettifies Claude ids. e.g.
   "claude-sonnet-4-6" -> "Sonnet 4.6", "openai/gpt-oss-120b:free" -> "gpt-oss-120b",
   "lmstudio-community/gemma-4-26B-A4B-it-QAT-MLX-4bit" -> "gemma-4-26B-A4B". */
function shortModel(id) {
  if (!id || id === "offline") return id || "—";
  let s = String(id).split("/").pop().replace(/:.*$/, "");          // drop provider/ and :free
  const m = s.match(/^claude-(opus|sonnet|haiku|fable|mythos)-(\d+)(?:-(\d+))?/i);
  if (m) {
    const name = m[1][0].toUpperCase() + m[1].slice(1);
    return `${name} ${m[3] ? `${m[2]}.${m[3]}` : m[2]}`;
  }
  return s.replace(/-(it|instruct|chat)\b.*$/i, "");                // trim capability/quant tail
}

/* LIVE DATA ONLY — no mock fallbacks. If the core is unreachable, getJSON
   returns null and each renderer shows an honest "offline / —" state. */
async function getJSON(path, fallback = null) {
  try {
    const r = await fetch(API + path, { signal: AbortSignal.timeout(1500) });
    if (!r.ok) throw 0;
    return await r.json();
  } catch { return fallback; }
}

/* ---------- toasts ---------- */
function toast(msg, kind = "") {
  const el = document.createElement("div");
  el.className = `toast ${kind}`.trim();
  el.textContent = msg;
  $("#toasts").appendChild(el);
  setTimeout(() => el.remove(), 3200);
}

/* ---------- dashboard renderers ---------- */
async function renderStatus() {
  const s = await getJSON("/api/status");
  const root = $("#systemStatus");
  if (!s) {
    ["version", "uptime", "ram"].forEach(k => setText(root, k, "—"));
    setText(root, "backend", "core offline"); $("#ramBar").style.width = "0%";
    return;
  }
  setText(root, "version", s.version);
  setText(root, "backend", shortModel(s.backend));
  const bEl = root.querySelector('[data-k="backend"]'); if (bEl) bEl.title = s.backend;  // full id on hover
  setText(root, "uptime", s.uptime);
  setText(root, "ram", `${s.ram_used_gb.toFixed(1)} / ${s.ram_total_gb} GB`);
  $("#ramBar").style.width = `${Math.round((s.ram_used_gb / s.ram_total_gb) * 100)}%`;
}
async function renderUpdate() {
  const box = $("#updBox"); if (!box) return;
  const d = await getJSON("/api/update/check");
  if (!d || !d.ok) { box.innerHTML = `<span class="muted small">${(d && d.detail) || "update check unavailable"}</span>`; return; }
  if (!d.update_available) {
    box.innerHTML = `<span class="status-pill ok">up to date</span> <span class="muted small">v${d.current_version} · ${d.current_commit}</span>`;
    return;
  }
  const supervised = !!d.supervised;
  box.innerHTML = `<span class="status-pill warn">update available</span> <span class="muted small">${d.behind} new commit(s)</span> <button class="navbtn small" id="updBtn">⬆ Update</button>`;
  $("#updBtn").addEventListener("click", async () => {
    const btn = $("#updBtn"); btn.disabled = true; btn.textContent = "updating…";
    toast("Updating — backing up your data & health-checking…");
    try {
      const r = await fetch(API + "/api/update/apply?confirm=true", { method: "POST", signal: AbortSignal.timeout(600000) });
      const res = await r.json();
      if (res.applied) {
        toast(`Updated to v${res.to_version}`, "ok");
        if (supervised) {
          box.innerHTML = `<span class="status-pill ok">updated</span> <button class="navbtn small" id="restartBtn">↻ Restart now</button>`;
          $("#restartBtn").addEventListener("click", async () => {
            const rb = $("#restartBtn"); rb.disabled = true; rb.textContent = "restarting…";
            toast("Restarting ATLAS to load the update…");
            try { await fetch(API + "/api/restart", { method: "POST" }); } catch {}
            setTimeout(() => location.reload(), 4000);   // launchd respawns; reconnect
          });
        } else {
          box.innerHTML = `<span class="status-pill ok">updated</span> <span class="muted small">restart ATLAS to load v${res.to_version}</span>`;
        }
      } else if (res.rolled_back) {
        toast("Update failed health check — rolled back, nothing lost", "err");
        btn.disabled = false; btn.textContent = "⬆ Update";
      } else {
        toast(res.detail || "update did not apply", "err");
        btn.disabled = false; btn.textContent = "⬆ Update";
      }
    } catch { toast("Update error — see logs", "err"); btn.disabled = false; btn.textContent = "⬆ Update"; }
  });
}
async function renderCredits() {
  const el = $('#systemStatus [data-k="credits"]'); if (!el) return;
  const c = await getJSON("/api/credits");
  if (!c || !c.available) { el.textContent = "—"; el.title = "no OpenRouter key"; return; }
  el.textContent = `$${c.remaining}`;
  el.title = `OpenRouter — used $${c.usage} of $${c.total}`;
}
function trend(el, v, goodIsDown = false) {
  if (el == null) return;
  const up = v >= 0;
  el.textContent = `${up ? "▲" : "▼"} ${Math.abs(v)}%`;
  el.className = (goodIsDown ? !up : up) ? "up" : "down";
}
async function renderMetrics() {
  const m = await getJSON("/api/metrics");
  const root = $("#metrics");
  if (!m) { ["latency", "accuracy", "interactions", "memhit"].forEach(k => setText(root, k, "—")); return; }
  setText(root, "latency", `${m.latency_ms} ms`);
  setText(root, "accuracy", `${Math.round(m.accuracy * 100)}%`);
  setText(root, "interactions", m.interactions);
  setText(root, "memhit", `${Math.round(m.memory_hit * 100)}%`);
  trend(root.querySelector('[data-k="latency_trend"]'), m.latency_trend, true);
  trend(root.querySelector('[data-k="accuracy_trend"]'), m.accuracy_trend);
  trend(root.querySelector('[data-k="interactions_trend"]'), m.interactions_trend);
  trend(root.querySelector('[data-k="memhit_trend"]'), m.memhit_trend);
}
async function renderMemory() {
  const items = await getJSON("/api/memory/recent");
  if (!items || !items.length) { $("#memoryFeed").innerHTML = `<li class="muted small">no recent memory activity</li>`; return; }
  $("#memoryFeed").innerHTML = items.map(i => `
    <li><span class="tag ${i.kind === "updated" ? "upd" : ""}">${i.kind}</span>
        <span>${i.title}</span><time>${i.ago}</time></li>`).join("");
}
function shortTime(iso) {
  if (!iso) return "—";
  const d = new Date(iso);
  return isNaN(d) ? iso : d.toLocaleString([], { month: "short", day: "numeric", hour: "2-digit", minute: "2-digit" });
}
/* mm-dd-yyyy hh:mm (24-hour) — UTC components so a stored "…T03:00:00Z" nightly
   cycle still reads 03:00 (the nominal scheduled time) rather than shifting by
   timezone. Non-date strings (e.g. "nightly 03:00") pass through unchanged. */
function humanDate(v) {
  if (!v) return "—";
  const d = new Date(v);
  if (isNaN(d)) return v;
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getUTCMonth() + 1)}-${p(d.getUTCDate())}-${d.getUTCFullYear()} ${p(d.getUTCHours())}:${p(d.getUTCMinutes())}`;
}
async function renderScheduler() {
  const jobs = await getJSON("/api/scheduler");
  if (!jobs || !jobs.length) { $("#schedulerJobs").innerHTML = `<li class="muted small">scheduler offline</li>`; return; }
  $("#schedulerJobs").innerHTML = jobs.map(j => `
    <li><span class="risk ${j.risk}">${j.risk[0]}</span>
      <b>${j.id}</b>
      <em class="status ${j.last_status || ""}">${j.last_status || "scheduled"}</em>
      <time>${shortTime(j.next_run)}</time>
      <button class="run" data-job="${j.id}" title="Run now">▶</button></li>`).join("");
  $("#schedulerJobs").querySelectorAll("button.run").forEach(btn => {
    btn.addEventListener("click", async () => {
      btn.disabled = true; btn.textContent = "…";
      try { await fetch(API + "/api/scheduler/run/" + btn.dataset.job, { method: "POST" }); } catch {}
      toast(`Ran ${btn.dataset.job}`, "ok");
      renderScheduler(); refreshLogs();
    });
  });
}
async function renderUpgrade() {
  const u = await getJSON("/api/upgrade");
  const root = $("#upgrade");
  if (!u) { ["last_cycle", "last_change", "next_cycle", "approval"].forEach(k => setText(root, k, "—")); return; }
  renderUpdate();
  setText(root, "last_cycle", u.last_cycle);
  setText(root, "last_change", u.last_change);
  setText(root, "next_cycle", humanDate(u.next_cycle));
  setText(root, "approval", u.approval);
}

/* ---------- state + orb + waveform ---------- */
let orbState = "idle";
function setState(value) {
  orbState = value;
  const ind = $("#stateIndicator");
  ind.dataset.state = value;
  ind.querySelector(".state-label").textContent = value.replace("_", " ");
  const orb = $("#orb");
  orb.classList.toggle("active", ["transcribing", "speaking", "thinking", "listening"].includes(value));
  orb.classList.toggle("listening", value === "listening");
  orb.classList.toggle("speaking", value === "speaking");
  const hints = {
    listening: "Listening… speak now",
    transcribing: "Hearing you…", thinking: "Thinking…", speaking: "Speaking…"
  };
  $("#orbHint").textContent = value === "idle"
    ? (wakeEnabled ? "Listening for “Hey Atlas”…" : "Click the orb, or enable 🎙 Wake")
    : (hints[value] || value);
}
function setTranscript(html) { $("#transcript").innerHTML = html; }

function waveform() {
  const c = $("#waveform"), ctx = c.getContext("2d");
  function resize() { c.width = c.clientWidth * devicePixelRatio; ctx.setTransform(1,0,0,1,0,0); ctx.scale(devicePixelRatio, devicePixelRatio); }
  resize(); addEventListener("resize", resize);
  let t = 0;
  (function draw() {
    const w = c.clientWidth, h = c.height / devicePixelRatio;
    ctx.clearRect(0, 0, w, h);
    const active = $("#orb").classList.contains("active");
    const color = orbState === "listening" ? "255,176,32" : orbState === "speaking" ? "39,224,160" : "0,224,255";
    ctx.beginPath();
    for (let x = 0; x <= w; x += 4) {
      const amp = active ? 20 : 5;
      const y = h / 2 + Math.sin(x * 0.05 + t) * amp * Math.sin(x * 0.01 + t * 0.5);
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = `rgba(${color},.7)`; ctx.lineWidth = 2;
    ctx.shadowColor = `rgba(${color},.8)`; ctx.shadowBlur = 8; ctx.stroke();
    t += active ? 0.16 : 0.03;
    requestAnimationFrame(draw);
  })();
}

/* ---------- conversation core (shared by voice + chat) ---------- */
function addMsg(role, text, cls = "") {
  const el = document.createElement("div");
  el.className = `msg ${role} ${cls}`.trim();
  el.textContent = text;
  const chat = $("#chat"); chat.appendChild(el); chat.scrollTop = chat.scrollHeight;
  return el;
}
async function ask(text, { speak = false } = {}) {
  if (!text) return;
  voiceTurn = speak;   // voice turns auto-listen for a follow-up reply
  addMsg("owner", text);
  setState("thinking");
  setTranscript(`<span class="you">You:</span> ${text}`);
  const thinking = addMsg("atlas", "…", "thinking");
  try {
    const r = await fetch(API + "/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }), signal: AbortSignal.timeout(60000)
    });
    const data = await r.json();
    thinking.remove();
    const reply = data.reply || "(no reply)";
    addMsg("atlas", reply);
    setTranscript(`<span class="atlas">ATLAS:</span> ${reply}`);
    if (speak) speakReply(reply); else setState("idle");
  } catch {
    thinking.remove();
    const msg = "Core isn’t running — start it with `python -m atlas.server` to chat for real.";
    addMsg("atlas", msg);
    setState("idle");
  } finally { refreshLogs(); resumeWake(); }
}

/* ---------- chat popover ---------- */
function openChat() { $("#chatPop").hidden = false; $("#chatFab").classList.add("open"); $("#msg").focus(); }
function closeChat() { $("#chatPop").hidden = true; $("#chatFab").classList.remove("open"); }
$("#chatFab").addEventListener("click", () => ($("#chatPop").hidden ? openChat() : closeChat()));
$("#chatClose").addEventListener("click", closeChat);
$("#composer").addEventListener("submit", (e) => {
  e.preventDefault();
  const input = $("#msg"), text = input.value.trim();
  if (!text) return;
  input.value = "";
  ask(text);
});

/* ---------- voice: Web Speech API (STT + TTS) ---------- */
const SR = window.SpeechRecognition || window.webkitSpeechRecognition;
let recog = null, listening = false, voiceTurn = false, followTimer = null;
function initVoice() {
  if (!SR) { $("#orbHint").textContent = "Voice needs Chrome/Edge — use chat 💬"; return; }
  recog = new SR();
  recog.lang = "en-US"; recog.interimResults = true; recog.maxAlternatives = 1;
  recog.onresult = (e) => {
    clearTimeout(followTimer);   // user is speaking — don't time out the follow-up window
    let txt = "";
    for (const res of e.results) txt += res[0].transcript;
    setTranscript(`<span class="you">You:</span> ${txt}`);
    if (e.results[e.results.length - 1].isFinal) { stopListening(); ask(txt.trim(), { speak: true }); }
  };
  recog.onerror = (e) => { stopListening(); if (e.error !== "no-speech" && e.error !== "aborted") toast("Mic: " + e.error, "err"); };
  recog.onend = () => { if (listening) { listening = false; if (orbState === "listening") setState("idle"); } resumeWake(); };
}
function startListening() {
  if (!recog) { openChat(); return; }
  if (wakeRunning) { try { wakeSR.stop(); } catch {} wakeRunning = false; }  // free the mic for command capture
  stopSpeaking();
  try { recog.start(); listening = true; setState("listening"); } catch {}
}
function stopListening() { if (recog && listening) { listening = false; try { recog.stop(); } catch {} } }
/* Pick a calm British-male native voice (Jarvis-like) from the OS's installed
   voices. macOS ships "Daniel" (en-GB); "Daniel (Enhanced)" / "Arthur" / "Oliver"
   are higher-quality downloads (System Settings → Accessibility → Spoken Content
   → System Voice → Manage Voices). Falls back gracefully to any en-GB voice. */
let _voices = [];
function loadVoices() { try { _voices = window.speechSynthesis ? (speechSynthesis.getVoices() || []) : []; } catch { _voices = []; } }
loadVoices();
if (window.speechSynthesis) speechSynthesis.addEventListener("voiceschanged", loadVoices);
function jarvisVoice() {
  if (!_voices.length) loadVoices();
  const prefs = ["Daniel (Enhanced)", "Arthur", "Oliver", "Jamie", "Daniel", "Google UK English Male"];
  for (const name of prefs) { const v = _voices.find(x => x.name === name); if (v) return v; }
  const gbMale = _voices.find(v => /en[-_]GB/i.test(v.lang) && /(male|daniel|arthur|oliver|jamie)/i.test(v.name));
  return gbMale || _voices.find(v => /en[-_]GB/i.test(v.lang)) || null;
}
let currentAudio = null;
function stopSpeaking() {
  try { speechSynthesis.cancel(); } catch {}
  if (currentAudio) { try { currentAudio.pause(); } catch {} currentAudio = null; }
}
/* After ATLAS finishes speaking: on a voice turn, open the mic for a few seconds
   so the Owner can reply without re-saying the wake word — a fluent back-and-forth.
   If they stay silent, we drop back to wake-word listening ("wait till I call"). */
function afterSpeak() {
  setState("idle");
  if (voiceTurn) listenFollowUp(); else resumeWake();
}
function listenFollowUp() {
  if (!recog) { resumeWake(); return; }
  startListening();                                   // hint shows "Listening…"
  clearTimeout(followTimer);
  followTimer = setTimeout(() => { if (listening) stopListening(); }, 7000);  // silence → onend → resumeWake
}
/* Fallback voice: the browser's OS Web Speech voice (used only if local Kokoro
   TTS is unavailable). */
function browserSpeak(text) {
  if (!window.speechSynthesis) { setState("idle"); resumeWake(); return; }
  speechSynthesis.cancel();
  const u = new SpeechSynthesisUtterance(text);
  const v = jarvisVoice(); if (v) u.voice = v;
  u.rate = 0.97; u.pitch = 0.9;
  u.onstart = () => setState("speaking");
  u.onend = () => afterSpeak();
  u.onerror = () => afterSpeak();
  setState("speaking"); speechSynthesis.speak(u);
}
/* Turn a written reply (which may contain markdown, citation markers, URLs) into
   clean prose for the voice — so ATLAS never reads "asterisk asterisk" or
   "bracket 1 dagger" aloud. The chat bubble still shows the original text. */
function speechClean(s) {
  if (!s) return "";
  return String(s)
    .replace(/```[\s\S]*?```/g, " — code shown on screen — ")  // fenced code
    .replace(/【[^】]*】/g, "")                                   // 【1†L1-L4】 markers
    .replace(/\[\^?\d+\]/g, "")                                   // [1] [^2] refs
    .replace(/!?\[([^\]]+)\]\([^)]+\)/g, "$1")                    // [text](url) -> text
    .replace(/\bhttps?:\/\/\S+/g, "")                             // bare URLs
    .replace(/^\s{0,3}#{1,6}\s+/gm, "")                           // # headings
    .replace(/^\s*[-*•]\s+/gm, "")                                // bullets
    .replace(/^\s*\d+\.\s+/gm, "")                                // numbered lists
    .replace(/(\*\*|__)(.*?)\1/g, "$2")                           // **bold** / __bold__
    .replace(/(\*|_)(?=\S)(.*?)(?<=\S)\1/g, "$2")                 // *italic* / _italic_
    .replace(/`([^`]+)`/g, "$1")                                  // `code`
    .replace(/[*_#`>~|]/g, " ")                                   // stray markup
    .replace(/\s*&\s*/g, " and ")
    .replace(/\n{2,}/g, ". ").replace(/\n/g, ", ")                // line breaks -> speech pauses
    .replace(/\s+([.,!?;:])/g, "$1").replace(/\s{2,}/g, " ").trim();
}

/* Primary voice: clean on-device neural TTS (Kokoro) served by /api/tts.
   Falls back to the OS voice if the local model isn't installed. */
async function speakReply(text) {
  const spoken = speechClean(text);
  if (!spoken) { setState("idle"); resumeWake(); return; }
  stopSpeaking();
  setState("speaking");
  try {
    const r = await fetch(API + "/api/tts", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text: spoken }), signal: AbortSignal.timeout(20000),
    });
    if (!r.ok) throw 0;                                  // 503 → no local voice
    const url = URL.createObjectURL(await r.blob());
    const audio = new Audio(url); currentAudio = audio;
    audio.onended = () => { URL.revokeObjectURL(url); if (currentAudio === audio) currentAudio = null; afterSpeak(); };
    audio.onerror = () => { URL.revokeObjectURL(url); currentAudio = null; browserSpeak(spoken); };
    await audio.play();
  } catch {
    browserSpeak(spoken);
  }
}
$("#orb").addEventListener("click", () => {
  if (orbState === "speaking") { stopSpeaking(); setState("idle"); resumeWake(); return; }
  listening ? stopListening() : startListening();
});

/* ---------- wake word: passive "Hey Atlas" listener (Web Speech) ---------- */
const wakeSR = SR ? new SR() : null;
let wakeEnabled = false, wakeRunning = false;
const WAKE_RE = /\b(?:hey|hi|ok|okay)?\s*atlas\b/i;
function initWake() {
  if (!wakeSR) return;
  wakeSR.continuous = true; wakeSR.interimResults = true; wakeSR.lang = "en-US";
  wakeSR.onresult = (e) => {
    const last = e.results[e.results.length - 1];
    const txt = Array.from(e.results).map(r => r[0].transcript).join(" ");
    if (!WAKE_RE.test(txt)) return;
    try { wakeSR.stop(); } catch {}
    wakeRunning = false;
    const tail = txt.replace(/^[\s\S]*?\batlas\b[\s,.!?-]*/i, "").trim();  // words after "Atlas"
    if (last.isFinal && tail.split(/\s+/).filter(Boolean).length >= 2) {
      setTranscript(`<span class="you">You:</span> ${tail}`);
      setState("thinking"); ask(tail, { speak: true });                   // one-breath: "Hey Atlas, what's the time"
    } else {
      setTimeout(() => startListening(), 200);                            // bare wake → capture the command next
    }
  };
  wakeSR.onend = () => {
    wakeRunning = false;
    if (wakeEnabled && !listening && orbState !== "speaking" && orbState !== "thinking") setTimeout(startWake, 300);
  };
  wakeSR.onerror = (e) => {
    wakeRunning = false;
    if (e.error === "not-allowed" || e.error === "service-not-allowed") {
      wakeEnabled = false; localStorage.setItem("atlas_wake", "off"); updateWakeUI();
      toast("Allow microphone access to use the wake word", "err");
    }
  };
}
function startWake() {
  if (!wakeSR || wakeRunning || listening || orbState === "speaking" || orbState === "thinking") return;
  try { wakeSR.start(); wakeRunning = true; } catch {}
}
function resumeWake() { if (wakeEnabled) startWake(); }
function setWake(on) {
  wakeEnabled = on;
  try { localStorage.setItem("atlas_wake", on ? "on" : "off"); } catch {}
  if (on) { startWake(); toast("Wake word on — say “Hey Atlas”", "ok"); }
  else { try { wakeSR && wakeSR.stop(); } catch {} wakeRunning = false; }
  updateWakeUI();
}
function updateWakeUI() {
  const b = $("#navWake");
  if (b) { b.classList.toggle("active", wakeEnabled); b.textContent = wakeEnabled ? "🎙 Wake: on" : "🎙 Wake: off"; }
  if (orbState === "idle") $("#orbHint").textContent = wakeEnabled ? "Listening for “Hey Atlas”…" : "Click the orb, or enable 🎙 Wake";
}
{ const _w = $("#navWake"); if (_w) _w.addEventListener("click", () => { if (!wakeSR) return toast("Voice needs Chrome/Edge", "err"); setWake(!wakeEnabled); }); }

/* ---------- logs drawer ---------- */
let logsPaused = false, logFilter = "all", lastLogs = [];
const knownTypes = new Set(["all"]);
function toggleLogs(force) {
  const d = $("#logsDrawer");
  const open = force != null ? force : d.dataset.open !== "true";
  d.dataset.open = String(open);
  $("#logsToggle").textContent = (open ? "▾ Logs" : "▴ Logs");
  $("#navLogs").classList.toggle("active", open);
  if (open) refreshLogs();
}
$("#logsToggle").addEventListener("click", () => toggleLogs());
$("#navLogs").addEventListener("click", () => toggleLogs());
$("#logsPause").addEventListener("click", () => {
  logsPaused = !logsPaused;
  $("#logsPause").textContent = logsPaused ? "▶ Resume" : "⏸ Pause";
  $("#logsPause").classList.toggle("active", logsPaused);
});
function rebuildFilters() {
  const wrap = $("#logFilters");
  if (wrap.childElementCount === knownTypes.size) return;
  wrap.innerHTML = [...knownTypes].map(t =>
    `<button class="chip ${t === logFilter ? "active" : ""}" data-type="${t}">${t}</button>`).join("");
  wrap.querySelectorAll(".chip").forEach(c => c.addEventListener("click", () => {
    logFilter = c.dataset.type;
    wrap.querySelectorAll(".chip").forEach(x => x.classList.toggle("active", x.dataset.type === logFilter));
    renderLogs();
  }));
}
function isError(e) { return e.type === "error" || (e.data && e.data.status === "error"); }
function _logRows() {
  return lastLogs.filter(e => {
    if (logFilter === "all") return true;
    if (logFilter === "error") return isError(e);
    return e.type === logFilter;
  });
}
function renderLogs() {
  const list = $("#logList");
  const rows = _logRows();
  list.innerHTML = rows.map(e => {
    const cls = isError(e) ? "error" : e.type;
    const time = (e.ts || "").replace("T", " ").replace("Z", "");
    const d = e.data ? JSON.stringify(e.data) : "";
    return `<div class="log-row ${cls}"><time>${time}</time><span class="lt">${e.type}</span><span class="ld">${escapeHTML(d)}</span></div>`;
  }).join("");
  $("#logsCount").textContent = `${rows.length} events`;
  if (!logsPaused) list.scrollTop = list.scrollHeight;
}
function escapeHTML(s) { return s.replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c])); }
async function refreshLogs() {
  if (logsPaused) return;
  const events = await getJSON("/api/logs?limit=300", null);
  if (!events) return;
  lastLogs = events;
  let added = false;
  events.forEach(e => { if (!knownTypes.has(e.type)) { knownTypes.add(e.type); added = true; } });
  if (!knownTypes.has("error")) knownTypes.add("error");
  if (added) rebuildFilters();
  if ($("#logsDrawer").dataset.open === "true") renderLogs();
  else $("#logsCount").textContent = `${_logRows().length} events`;  // keep count live while collapsed
}

/* ---------- settings (full editor over settings.json) ---------- */
let settingsData = null;
function openSettings() { $("#settingsModal").hidden = false; loadSettings(); refreshBackendLabel(); }
function closeSettings() { $("#settingsModal").hidden = true; }
$("#navSettings").addEventListener("click", openSettings);
$("#settingsClose").addEventListener("click", closeSettings);
$("#settingsCancel").addEventListener("click", closeSettings);
$("#settingsModal").addEventListener("click", (e) => { if (e.target === $("#settingsModal")) closeSettings(); });

async function loadSettings() {
  const data = await getJSON("/api/settings", null);
  const form = $("#settingsForm");
  form.innerHTML = "";
  if (!data) { form.innerHTML = `<p class="muted">Core not running — start ATLAS to edit settings.</p>`; return; }
  settingsData = data;
  const modelsData = await getJSON("/api/models", null);  // for the interactive model picker

  const isSection = ([, v]) => v && typeof v === "object" && !Array.isArray(v);
  const sections = Object.entries(data).filter(isSection);
  const scalars = Object.entries(data).filter(([k, v]) => k !== "_comment" && !isSection([k, v]));

  const layout = document.createElement("div"); layout.className = "settings-layout";
  const nav = document.createElement("div"); nav.className = "settings-nav";
  const panes = document.createElement("div"); panes.className = "settings-panes";

  // top-level comment + scalar fields (e.g. version) stay visible above panes
  if (data._comment || scalars.length) {
    const top = document.createElement("div"); top.className = "spane-top";
    if (data._comment) { const c = document.createElement("p"); c.className = "scomment"; c.textContent = data._comment; top.appendChild(c); }
    scalars.forEach(([k, v]) => top.appendChild(buildField(k, v, [k])));
    panes.appendChild(top);
  }

  const show = (key) => {
    nav.querySelectorAll(".snav").forEach(b => b.classList.toggle("active", b.dataset.target === key));
    panes.querySelectorAll(".spane").forEach(p => { p.hidden = p.dataset.pane !== key; });
  };
  sections.forEach(([key, val], i) => {
    const btn = document.createElement("button");
    btn.type = "button"; btn.className = "snav"; btn.dataset.target = key; btn.textContent = key;
    btn.addEventListener("click", () => show(key));
    nav.appendChild(btn);

    const pane = document.createElement("div");
    pane.className = "spane"; pane.dataset.pane = key;
    if (key === "model") pane.appendChild(buildModelPane(val, modelsData));
    else pane.appendChild(buildSection(val, [key]));
    panes.appendChild(pane);
  });

  layout.appendChild(nav); layout.appendChild(panes);
  form.appendChild(layout);
  if (sections.length) show(sections[0][0]);  // open the first category
}
function buildSection(obj, path) {
  const frag = document.createDocumentFragment();
  for (const [key, val] of Object.entries(obj)) {
    if (key === "_comment") {
      const p = document.createElement("p"); p.className = "scomment"; p.textContent = val;
      frag.appendChild(p); continue;
    }
    const here = [...path, key];
    if (val && typeof val === "object" && !Array.isArray(val)) {
      const fs = document.createElement("fieldset"); fs.className = "sset";
      const lg = document.createElement("legend"); lg.textContent = key; fs.appendChild(lg);
      const inner = document.createElement("div"); inner.className = path.length ? "snest" : "";
      inner.appendChild(buildSection(val, here)); fs.appendChild(inner);
      frag.appendChild(fs);
    } else {
      frag.appendChild(buildField(key, val, here));
    }
  }
  return frag;
}
function buildField(key, val, path) {
  const row = document.createElement("div"); row.className = "sfield";
  const label = document.createElement("label"); label.textContent = key;
  row.appendChild(label);
  let input;
  const pathStr = path.join(".");
  if (typeof val === "boolean") {
    input = document.createElement("input"); input.type = "checkbox"; input.checked = val;
    input.dataset.type = "boolean";
  } else if (typeof val === "number") {
    input = document.createElement("input"); input.type = "number"; input.value = val;
    input.step = Number.isInteger(val) ? "1" : "0.1"; input.dataset.type = "number";
  } else if (Array.isArray(val)) {
    input = document.createElement("input"); input.type = "text"; input.value = val.join(", ");
    input.dataset.type = "array";
  } else {
    input = document.createElement("input"); input.type = "text"; input.value = val == null ? "" : String(val);
    input.dataset.type = "string";
  }
  input.dataset.path = pathStr;
  row.appendChild(input);
  return row;
}
/* ---- small field builders (used by the interactive model pane) ---- */
function mfield(labelText) {
  const r = document.createElement("div"); r.className = "sfield";
  const l = document.createElement("label"); l.textContent = labelText; r.appendChild(l);
  return r;
}
function selectField(labelText, path, pairs, value) {
  const r = mfield(labelText);
  const s = document.createElement("select"); s.dataset.path = path; s.dataset.type = "string";
  s.innerHTML = pairs.map(([id, lab]) => `<option value="${id}"${id === value ? " selected" : ""}>${lab}</option>`).join("");
  if (value && !pairs.some(([id]) => id === value)) {
    const o = document.createElement("option"); o.value = value; o.textContent = value; o.selected = true; s.appendChild(o);
  }
  r.appendChild(s); return r;
}
function textField(labelText, path, value) {
  const r = mfield(labelText);
  const i = document.createElement("input"); i.type = "text"; i.dataset.path = path; i.dataset.type = "string";
  i.value = value == null ? "" : value; r.appendChild(i); return r;
}
function numberField(labelText, path, value) {
  const r = mfield(labelText);
  const i = document.createElement("input"); i.type = "number"; i.dataset.path = path; i.dataset.type = "number";
  i.step = Number.isInteger(value) ? "1" : "0.1"; i.value = value; r.appendChild(i); return r;
}

/* reusable API-key helper bound to POST /api/secret/{provider}: a password
   field + Save-to-Keychain button + status. The key is NEVER a settings field
   (no data-path) — it goes to the Keychain, not settings.json. */
function keyHelper(provider, present, envName) {
  const frag = document.createDocumentFragment();
  const row = mfield("API key");
  const input = document.createElement("input"); input.type = "password"; input.className = "keyinput";
  input.placeholder = present ? "•••••••• (detected)" : "paste key…";
  const save = document.createElement("button"); save.type = "button"; save.className = "navbtn small"; save.textContent = "Save to Keychain";
  row.append(input, save); frag.appendChild(row);
  const status = document.createElement("p"); status.className = "mhint";
  const setStatus = (ok, extra) => {
    status.innerHTML = ok
      ? `<span class="status-pill ok">key detected</span> ${extra || "stored in Keychain — never in settings.json or git"}`
      : `<span class="status-pill warn">no key</span> paste your key and save — it goes to macOS Keychain (env <code>${envName}</code>)`;
  };
  setStatus(present); frag.appendChild(status);
  save.addEventListener("click", async () => {
    const k = input.value.trim();
    if (!k) { toast("Enter a key first", "err"); return; }
    save.disabled = true; save.textContent = "…";
    try {
      const r = await fetch(API + `/api/secret/${provider}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key: k }) });
      if (!r.ok) throw 0;
      const d = await r.json();
      toast(d.stored_in_keychain ? `Key saved to Keychain · backend: ${d.backend}` : `Key set for session · backend: ${d.backend}`, "ok");
      input.value = ""; setStatus(true, `backend now: <b>${d.backend}</b>`); refreshBackendLabel();
    } catch { toast("Save failed", "err"); }
    finally { save.disabled = false; save.textContent = "Save to Keychain"; }
  });
  return frag;
}

/* interactive model picker: API / OpenRouter / Local toggle with per-mode
   config, model dropdowns, key helpers, and live model fetching. Bound controls
   carry data-path so the shared collectSettings()/Save path persists them;
   omitted fields keep their values via the structuredClone in collectSettings. */
function buildModelPane(model, md) {
  md = md || {};
  const apiMd = md.api || { models: [], key_present: false, key_env: "ANTHROPIC_API_KEY" };
  const orMd = md.openrouter || { models: [], key_present: false, key_env: "OPENROUTER_API_KEY", endpoint: "https://openrouter.ai/api/v1" };
  const apiModels = (apiMd.models || []).map(x => [x.id, x.label]);
  const sec = () => { const d = document.createElement("div"); d.className = "msec"; return d; };
  const wrap = document.createElement("div"); wrap.className = "model-pane";

  // mode toggle (3-way)
  const modeRow = mfield("Backend mode");
  const toggle = document.createElement("div"); toggle.className = "mode-toggle";
  const mk = (t) => { const b = document.createElement("button"); b.type = "button"; b.className = "mtbtn"; b.textContent = t; return b; };
  const apiBtn = mk("☁ API · Claude"), orBtn = mk("🌐 OpenRouter"), locBtn = mk("🖥 Local · MLX");
  toggle.append(apiBtn, orBtn, locBtn);
  const modeInput = document.createElement("input"); modeInput.type = "hidden"; modeInput.dataset.path = "model.mode"; modeInput.dataset.type = "string"; modeInput.value = model.mode || "api";
  modeRow.append(toggle, modeInput);
  wrap.appendChild(modeRow);

  // ── Task routing (auto-pick a model per turn by intent; overrides mode) ──
  const r = model.routing || {}; const rt = r.tiers || {};
  const routeSec = sec();
  const rTitle = document.createElement("div"); rTitle.className = "sset-title"; rTitle.textContent = "Task routing";
  routeSec.appendChild(rTitle);
  const rRow = mfield("Route by task type");
  const rToggle = document.createElement("input"); rToggle.type = "checkbox"; rToggle.checked = !!r.enabled;
  rToggle.dataset.path = "model.routing.enabled"; rToggle.dataset.type = "boolean";
  rRow.appendChild(rToggle); routeSec.appendChild(rRow);
  const rHint = document.createElement("p"); rHint.className = "mhint";
  rHint.innerHTML = `When on, each turn is auto-routed by intent — <b>overrides the single backend</b> below. Daily = cheap/free; Complex & Code cost per use.`;
  routeSec.appendChild(rHint);
  [["code", "🛠 Code"], ["complex", "🧠 Complex"], ["daily", "💬 Daily"]].forEach(([k, label]) => {
    routeSec.appendChild(textField(`${label} model`, `model.routing.tiers.${k}.model`, (rt[k] || {}).model || ""));
  });
  wrap.appendChild(routeSec);

  // ── API · Claude ──
  const apiSec = sec();
  apiSec.appendChild(selectField("API model", "model.backend", apiModels, model.backend));
  apiSec.appendChild(selectField("Escalation model", "model.escalation_model", apiModels, model.escalation_model));
  apiSec.appendChild(keyHelper("anthropic", apiMd.key_present, apiMd.key_env || "ANTHROPIC_API_KEY"));
  wrap.appendChild(apiSec);

  // ── OpenRouter ──
  const orSec = sec();
  orSec.appendChild(textField("Endpoint", "model.openrouter.endpoint", (model.openrouter && model.openrouter.endpoint) || "https://openrouter.ai/api/v1"));
  const orRow = mfield("Model");
  const dlId = "or-model-list";
  const orInput = document.createElement("input"); orInput.type = "text"; orInput.setAttribute("list", dlId);
  orInput.dataset.path = "model.openrouter.model"; orInput.dataset.type = "string";
  orInput.value = (model.openrouter && model.openrouter.model) || "";
  orInput.placeholder = "provider/model · e.g. openai/gpt-5-mini";
  const dl = document.createElement("datalist"); dl.id = dlId;
  const fillDL = (ids) => { dl.innerHTML = (ids || []).map(i => `<option value="${i}"></option>`).join(""); };
  fillDL(orMd.models);
  const orFetch = document.createElement("button"); orFetch.type = "button"; orFetch.className = "navbtn small"; orFetch.title = "Fetch live model list"; orFetch.textContent = "↻";
  orRow.append(orInput, orFetch); orSec.append(orRow, dl);
  const orStatus = document.createElement("p"); orStatus.className = "mhint";
  orStatus.innerHTML = `Any model from <code>openrouter.ai/models</code>. ↻ loads the live list to search.`;
  orSec.appendChild(orStatus);
  orFetch.addEventListener("click", async () => {
    orFetch.disabled = true; orFetch.textContent = "…";
    const d = await getJSON("/api/openrouter/models", null);
    if (d && d.ok) { fillDL(d.models); orStatus.innerHTML = `<span class="status-pill ok">loaded</span> ${d.count} models — start typing to search`; toast(`${d.count} OpenRouter models loaded`, "ok"); }
    else { toast("Couldn't fetch OpenRouter models", "err"); }
    orFetch.disabled = false; orFetch.textContent = "↻";
  });
  orSec.appendChild(keyHelper("openrouter", orMd.key_present, orMd.key_env || "OPENROUTER_API_KEY"));
  wrap.appendChild(orSec);

  // ── Local · MLX ──
  const locSec = sec();
  locSec.appendChild(textField("Server endpoint", "model.local.endpoint", (model.local && model.local.endpoint) || "http://localhost:8080/v1"));
  const lmRow = mfield("Local model");
  const lmSel = document.createElement("select"); lmSel.dataset.path = "model.local.model"; lmSel.dataset.type = "string";
  const refreshBtn = document.createElement("button"); refreshBtn.type = "button"; refreshBtn.className = "navbtn small"; refreshBtn.title = "Fetch running models"; refreshBtn.textContent = "↻";
  lmRow.append(lmSel, refreshBtn); locSec.appendChild(lmRow);
  const locStatus = document.createElement("p"); locStatus.className = "mhint"; locSec.appendChild(locStatus);
  const startHint = document.createElement("p"); startHint.className = "mhint code-hint"; locSec.appendChild(startHint);
  const fillLocal = (data) => {
    const active = (model.local && model.local.model) || "";
    const L = (data && data.local) || {};
    const models = L.models || [];
    const opts = models.length ? models : (active ? [active] : []);
    lmSel.innerHTML = opts.map(id => `<option value="${id}"${id === active ? " selected" : ""}>${id}</option>`).join("") || `<option value="">(none)</option>`;
    locStatus.innerHTML = L.running
      ? `<span class="status-pill ok">server up</span> ${models.length} model(s) at <code>${L.endpoint || ""}</code>`
      : `<span class="status-pill warn">server down</span> no local server reachable`;
    startHint.innerHTML = L.running ? "" : `Start it: <code>mlx_lm.server --model ${active || "&lt;model&gt;"} --port 8080</code>`;
  };
  fillLocal(md);
  refreshBtn.addEventListener("click", async () => {
    refreshBtn.disabled = true; refreshBtn.textContent = "…";
    const data = await getJSON("/api/models", null);
    fillLocal(data);
    const up = data && data.local && data.local.running;
    toast(up ? "Local models refreshed" : "Local server not reachable", up ? "ok" : "err");
    refreshBtn.disabled = false; refreshBtn.textContent = "↻";
  });
  wrap.appendChild(locSec);

  // ── shared params ──
  const shared = sec();
  shared.appendChild(numberField("Max tokens", "model.max_tokens", model.max_tokens));
  shared.appendChild(numberField("Temperature", "model.temperature", model.temperature));
  wrap.appendChild(shared);

  // ── mode switching ──
  const setMode = (mode) => {
    modeInput.value = mode;
    apiBtn.classList.toggle("active", mode === "api");
    orBtn.classList.toggle("active", mode === "openrouter");
    locBtn.classList.toggle("active", mode === "local");
    apiSec.hidden = mode !== "api";
    orSec.hidden = mode !== "openrouter";
    locSec.hidden = mode !== "local";
  };
  apiBtn.addEventListener("click", () => setMode("api"));
  orBtn.addEventListener("click", () => setMode("openrouter"));
  locBtn.addEventListener("click", () => setMode("local"));
  setMode(model.mode || "api");
  return wrap;
}

function collectSettings() {
  const out = structuredClone(settingsData);
  $("#settingsForm").querySelectorAll("[data-path]").forEach(inp => {
    const path = inp.dataset.path.split(".");
    let v;
    switch (inp.dataset.type) {
      case "boolean": v = inp.checked; break;
      case "number": v = inp.value === "" ? null : Number(inp.value); break;
      case "array": v = inp.value.split(",").map(s => s.trim()).filter(Boolean); break;
      default: v = inp.value;
    }
    let node = out;
    for (let i = 0; i < path.length - 1; i++) node = node[path[i]];
    node[path[path.length - 1]] = v;
  });
  return out;
}
$("#settingsSave").addEventListener("click", async () => {
  if (!settingsData) { closeSettings(); return; }
  const payload = collectSettings();
  try {
    const r = await fetch(API + "/api/settings", {
      method: "PUT", headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload), signal: AbortSignal.timeout(8000)
    });
    if (!r.ok) throw new Error((await r.json()).detail || r.statusText);
    const data = await r.json();
    toast(`Settings saved · backend: ${data.backend}`, "ok");
    closeSettings();
    renderStatus(); refreshBackendLabel();
  } catch (e) { toast("Save failed: " + e.message, "err"); }
});

/* backend test / label */
async function refreshBackendLabel() {
  const s = await getJSON("/api/status", null);
  $("#backendLabel").textContent = s ? `backend: ${s.backend}` : "core offline";
}
$("#backendTest").addEventListener("click", async () => {
  const btn = $("#backendTest"); btn.disabled = true; btn.textContent = "…";
  try {
    const r = await fetch(API + "/api/backend/test", { method: "POST", signal: AbortSignal.timeout(15000) });
    const d = await r.json();
    toast(d.detail, d.ok ? "ok" : "err");
    $("#backendLabel").textContent = `backend: ${d.backend}`;
  } catch { toast("Test failed — core not reachable", "err"); }
  finally { btn.disabled = false; btn.textContent = "Test"; }
});

/* ---------- live state via WebSocket (optional) ---------- */
function connectWS() {
  try {
    const ws = new WebSocket((API || location.origin).replace(/^http/, "ws") + "/ws");
    ws.onmessage = (ev) => { try { const m = JSON.parse(ev.data); if (m.type === "state" && !listening) setState(m.value); } catch {} };
  } catch {}
}

/* ---------- keyboard shortcuts ---------- */
const typing = () => ["INPUT", "TEXTAREA"].includes(document.activeElement?.tagName);
addEventListener("keydown", (e) => {
  if (e.key === "Escape") {
    if (!$("#settingsModal").hidden) return closeSettings();
    if (!$("#chatPop").hidden) return closeChat();
    if ($("#logsDrawer").dataset.open === "true") return toggleLogs(false);
  }
  if (typing()) return;
  if (e.code === "Space") { e.preventDefault(); listening ? stopListening() : startListening(); }
  else if (e.key.toLowerCase() === "l") { toggleLogs(); }
  else if (e.key.toLowerCase() === "c") { $("#chatPop").hidden ? openChat() : closeChat(); }
});

/* clock (kept for parity; footer hidden by default) */
setInterval(() => { const c = $("#clock"); if (c) c.textContent = new Date().toLocaleTimeString(); }, 1000);

/* ---------- boot ---------- */
setState("idle");
waveform();
initVoice();
initWake();
if (localStorage.getItem("atlas_wake") === "on") setWake(true); else updateWakeUI();
renderStatus(); renderMetrics(); renderMemory(); renderUpgrade(); renderScheduler(); renderCredits();
connectWS();
setInterval(() => { renderStatus(); renderMetrics(); renderScheduler(); }, 5000);
setInterval(renderCredits, 60000);   // OpenRouter balance changes slowly
setInterval(refreshLogs, 3000);
/* persistent chat history — replay saved conversation turns from episodic memory */
async function loadHistory() {
  const turns = await getJSON("/api/conversation?limit=30");
  if (turns && turns.length) {
    turns.forEach(t => { if (t.user) addMsg("owner", t.user); if (t.assistant) addMsg("atlas", t.assistant); });
  } else {
    addMsg("atlas", "ATLAS online — click the orb to talk, or type below.");
  }
}
loadHistory();
