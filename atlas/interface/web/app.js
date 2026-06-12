/* ATLAS HUD — frontend logic.
 *
 * INTEGRATION POINT: this talks to the FastAPI core if it is running
 * (atlas/server/app.py). If the API is unreachable it falls back to mock data
 * so the dashboard always renders. Endpoints used:
 *   GET  /api/status          -> system + version
 *   GET  /api/metrics         -> today vs 7-day
 *   GET  /api/memory/recent   -> vault activity feed
 *   GET  /api/upgrade         -> last/next cycle
 *   POST /api/chat {text}     -> { reply, state }
 *   WS   /ws                  -> {type:"state", value:"thinking"} live state
 */
const API = location.origin.startsWith("http") ? "" : "http://localhost:8765";
const $ = (s, r = document) => r.querySelector(s);
const setText = (root, k, v) => { const el = root.querySelector(`[data-k="${k}"]`); if (el) el.textContent = v; };

/* ---------- mock fallback (used only when the core isn't running) ---------- */
const MOCK = {
  status: { version: "0.1.0", backend: "claude-sonnet-4-6 (mock)", uptime: "00:14:32", ram_used_gb: 6.2, ram_total_gb: 24 },
  metrics: {
    latency_ms: 740, latency_trend: -8, accuracy: 0.96, accuracy_trend: 2,
    interactions: 23, interactions_trend: 12, memory_hit: 0.91, memhit_trend: 5
  },
  memory: [
    { kind: "created", title: "Project Atlas", ago: "2h" },
    { kind: "updated", title: "Owner", ago: "2h" },
    { kind: "created", title: "Voice stack choice", ago: "5h" }
  ],
  upgrade: { last_cycle: "Cycle 0", last_change: "Bootstrap complete — all 7 layers initialized.", next_cycle: "tonight 03:00", approval: "PATCH auto" }
};

async function getJSON(path, fallback) {
  try {
    const r = await fetch(API + path, { signal: AbortSignal.timeout(1500) });
    if (!r.ok) throw 0;
    return await r.json();
  } catch { return fallback; }
}

/* ---------- renderers ---------- */
async function renderStatus() {
  const s = await getJSON("/api/status", MOCK.status);
  const root = $("#systemStatus");
  setText(root, "version", s.version);
  setText(root, "backend", s.backend);
  setText(root, "uptime", s.uptime);
  setText(root, "ram", `${s.ram_used_gb.toFixed(1)} / ${s.ram_total_gb} GB`);
  $("#ramBar").style.width = `${Math.round((s.ram_used_gb / s.ram_total_gb) * 100)}%`;
}

function trend(el, v, goodIsDown = false) {
  if (el == null) return;
  const up = v >= 0;
  el.textContent = `${up ? "▲" : "▼"} ${Math.abs(v)}%`;
  const good = goodIsDown ? !up : up;
  el.className = good ? "up" : "down";
}

async function renderMetrics() {
  const m = await getJSON("/api/metrics", MOCK.metrics);
  const root = $("#metrics");
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
  const items = await getJSON("/api/memory/recent", MOCK.memory);
  $("#memoryFeed").innerHTML = items.map(i => `
    <li><span class="tag ${i.kind === "updated" ? "upd" : ""}">${i.kind}</span>
        <span>${i.title}</span><time>${i.ago}</time></li>`).join("");
}

async function renderUpgrade() {
  const u = await getJSON("/api/upgrade", MOCK.upgrade);
  const root = $("#upgrade");
  setText(root, "last_cycle", u.last_cycle);
  setText(root, "last_change", u.last_change);
  setText(root, "next_cycle", u.next_cycle);
  setText(root, "approval", u.approval);
}

/* ---------- state + orb ---------- */
function setState(value) {
  const ind = $("#stateIndicator");
  ind.dataset.state = value;
  ind.querySelector(".state-label").textContent = value.replace("_", " ");
  const orb = $("#orb");
  orb.classList.toggle("active", value === "transcribing" || value === "speaking" || value === "thinking");
  const hints = {
    idle: "Say “Hey Atlas” to wake", wake_detected: "Listening…",
    transcribing: "Hearing you…", thinking: "Thinking…", speaking: "Speaking…"
  };
  $("#orbHint").textContent = hints[value] || value;
}

/* simple animated waveform */
function waveform() {
  const c = $("#waveform"), ctx = c.getContext("2d");
  function resize() { c.width = c.clientWidth * devicePixelRatio; ctx.scale(devicePixelRatio, devicePixelRatio); }
  resize();
  let t = 0;
  (function draw() {
    const w = c.clientWidth, h = c.height / devicePixelRatio;
    ctx.clearRect(0, 0, w, h);
    const active = $("#orb").classList.contains("active");
    ctx.beginPath();
    for (let x = 0; x <= w; x += 4) {
      const amp = active ? 18 : 5;
      const y = h / 2 + Math.sin(x * 0.05 + t) * amp * Math.sin(x * 0.01 + t * 0.5);
      x === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y);
    }
    ctx.strokeStyle = "rgba(0,224,255,.7)"; ctx.lineWidth = 2;
    ctx.shadowColor = "rgba(0,224,255,.8)"; ctx.shadowBlur = 8; ctx.stroke();
    t += active ? 0.15 : 0.03;
    requestAnimationFrame(draw);
  })();
}

/* ---------- chat ---------- */
function addMsg(role, text, cls = "") {
  const el = document.createElement("div");
  el.className = `msg ${role} ${cls}`.trim();
  el.textContent = text;
  const chat = $("#chat"); chat.appendChild(el); chat.scrollTop = chat.scrollHeight;
  return el;
}

$("#composer").addEventListener("submit", async (e) => {
  e.preventDefault();
  const input = $("#msg"), text = input.value.trim();
  if (!text) return;
  input.value = "";
  addMsg("owner", text);
  setState("thinking");
  const thinking = addMsg("atlas", "…", "thinking");
  try {
    const r = await fetch(API + "/api/chat", {
      method: "POST", headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }), signal: AbortSignal.timeout(60000)
    });
    const data = await r.json();
    thinking.remove();
    addMsg("atlas", data.reply || "(no reply)");
  } catch {
    thinking.remove();
    addMsg("atlas", "Core isn’t running — start it with `python -m atlas.server` to chat for real. (This is the offline dashboard.)");
  } finally {
    setState("idle");
  }
});

/* ---------- live state via WebSocket (optional) ---------- */
function connectWS() {
  try {
    const ws = new WebSocket((API || location.origin).replace(/^http/, "ws") + "/ws");
    ws.onmessage = (ev) => { try { const m = JSON.parse(ev.data); if (m.type === "state") setState(m.value); } catch {} };
  } catch {}
}

/* clock */
setInterval(() => { $("#clock").textContent = new Date().toLocaleTimeString(); }, 1000);

/* boot */
setState("idle");
waveform();
renderStatus(); renderMetrics(); renderMemory(); renderUpgrade();
connectWS();
setInterval(() => { renderStatus(); renderMetrics(); }, 5000);
addMsg("atlas", "ATLAS online. Cycle 0 bootstrap complete — how can I help?");
