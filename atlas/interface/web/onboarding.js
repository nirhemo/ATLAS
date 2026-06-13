/* ATLAS first-run onboarding wizard (L3).
 *
 * Shows a full-screen guided setup the first time ATLAS is opened (when
 * /api/onboarding/status reports completed:false). Reuses the global helpers
 * from app.js ($, toast) and talks to the same API. Re-runnable from Settings
 * via window.atlasRunOnboarding().
 */
(function () {
  const API = location.origin.startsWith("http") ? "" : "http://localhost:8765";
  const $id = (id) => document.getElementById(id);
  const t = (msg, kind) => (window.toast ? window.toast(msg, kind) : null);

  let step = 0, status = null;
  const state = {
    ownerName: "", provider: "openrouter", routing: true,
    voice: "bm_george", wake: true, identityApproved: false, privacyAck: false,
    approved: new Set(),
  };

  async function api(path, opts = {}) {
    const r = await fetch(API + path, opts);
    const body = await r.json().catch(() => ({}));
    if (!r.ok) throw new Error(body.detail || `${r.status}`);
    return body;
  }
  const esc = (s) => String(s).replace(/[&<>]/g, c => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;" }[c]));

  /* ---------------- steps ---------------- */
  const steps = [
    { label: "Welcome", html: () => `
      <h1>Welcome to <span class="ob-accent">ATLAS</span></h1>
      <p class="ob-lede">A persistent, voice-first assistant that runs on your machine. Let's get it set up — about a minute.</p>
      <ul class="ob-checks">
        <li>${status.python_ok ? "✅" : "⚠️"} Python ${esc(status.python)} ${status.python_ok ? "" : "— ATLAS needs 3.10+"}</li>
        <li>✅ Core server reachable</li>
        <li>${status.has_backend ? "✅ A model backend is already configured" : "○ No model connected yet — we'll fix that"}</li>
      </ul>
      <p class="ob-fine">Privacy: your API keys live in the macOS Keychain (never in files or git); conversations stay on this machine.</p>` },

    { label: "You", html: () => `
      <h2>Who am I assisting?</h2>
      <label class="ob-field"><span>Your name</span>
        <input id="obName" type="text" value="${esc(state.ownerName)}" placeholder="e.g. Alex" autofocus></label>
      <div class="ob-identity">
        <p><b>ATLAS's character</b> — calm, capable, concise. Leads with the answer, never fabricates, always grounds facts in a real source, and asks before anything destructive. Memory and identity carry forward; switching models never changes who ATLAS is.</p>
      </div>
      <label class="ob-check"><input id="obIdentity" type="checkbox" ${state.identityApproved ? "checked" : ""}> I've reviewed and approve ATLAS's identity.</label>`,
      enter() { $id("obName").focus(); },
      next() {
        const name = $id("obName").value.trim();
        if (!name) { t("Enter your name", "err"); return false; }
        if (!$id("obIdentity").checked) { t("Please approve the identity to continue", "err"); return false; }
        state.ownerName = name; state.identityApproved = true; return true;
      } },

    { label: "Brain", html: () => {
        const cards = [
          ["openrouter", "🌐 OpenRouter", "One key, many models (free + frontier). Recommended.", true],
          ["local", "🖥 Local (MLX)", "Free & private, runs on your Mac. Needs a local model server.", false],
          ["api", "☁ Claude API", "Anthropic key, pay-per-token.", false],
          ["offline", "○ Skip for now", "Offline mode — time, recall & 'remember' only.", false],
        ];
        return `<h2>Pick ATLAS's brain</h2>
          <div class="ob-cards">${cards.map(([id, title, desc, rec]) => `
            <button class="ob-pick ${state.provider === id ? "sel" : ""}" data-prov="${id}">
              <b>${title}${rec ? ' <span class="ob-rec">recommended</span>' : ""}</b><span>${desc}</span></button>`).join("")}</div>`;
      },
      enter(root) { root.querySelectorAll(".ob-pick").forEach(b => b.onclick = () => {
        state.provider = b.dataset.prov; root.querySelectorAll(".ob-pick").forEach(x => x.classList.toggle("sel", x === b));
      }); } },

    { label: "Connect", html: () => {
        if (state.provider === "offline") return `<h2>Offline mode</h2><p class="ob-lede">ATLAS will run with on-device basics only. You can connect a model later in Settings → Model.</p>`;
        if (state.provider === "local") return `<h2>Local model server</h2>
          <p class="ob-lede">Start a local OpenAI-compatible server (e.g. <code>mlx_lm.server --port 8080</code>), then check it.</p>
          <button class="ob-btn" id="obTest">Check local server</button><p class="ob-result" id="obRes"></p>`;
        const prov = state.provider === "api" ? "anthropic" : "openrouter";
        const ph = state.provider === "api" ? "sk-ant-…" : "sk-or-…";
        return `<h2>Connect ${state.provider === "api" ? "Claude" : "OpenRouter"}</h2>
          <p class="ob-lede">Paste your API key — it's stored in the macOS Keychain, never in files.</p>
          <label class="ob-field"><span>API key</span><input id="obKey" type="password" placeholder="${ph}"></label>
          <button class="ob-btn" id="obTest">Save &amp; test</button><p class="ob-result" id="obRes"></p>
          <p class="ob-fine" data-prov="${prov}">Get a key: ${state.provider === "api" ? "console.anthropic.com" : "openrouter.ai/keys"}</p>`;
      },
      enter(root) {
        const btn = $id("obTest"); if (!btn) return;
        btn.onclick = async () => {
          const res = $id("obRes"); btn.disabled = true; btn.textContent = "…";
          try {
            if (state.provider !== "local") {
              const key = ($id("obKey").value || "").trim();
              if (!key) { t("Enter a key", "err"); return; }
              const prov = state.provider === "api" ? "anthropic" : "openrouter";
              await api(`/api/secret/${prov}`, { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ key }) });
            }
            const d = await api(`/api/backend/test?provider=${state.provider}`, { method: "POST" });
            res.textContent = (d.ok ? "✅ " : "⚠️ ") + d.detail; res.className = "ob-result " + (d.ok ? "ok" : "warn");
          } catch (e) { res.textContent = "⚠️ " + e.message; res.className = "ob-result warn"; }
          finally { btn.disabled = false; btn.textContent = state.provider === "local" ? "Check local server" : "Save & test"; }
        };
      } },

    { label: "Model", html: () => {
        const canRoute = state.provider === "openrouter";
        return `<h2>Models</h2>
          <p class="ob-lede">${state.provider === "offline" ? "No model selected — offline basics only." :
            `ATLAS will use <b>${esc(state.provider)}</b>. Defaults are pre-filled; tune any model later in Settings.`}</p>
          ${canRoute ? `<label class="ob-check"><input id="obRoute" type="checkbox" ${state.routing ? "checked" : ""}>
            Smart task routing — <b>Code→Opus</b>, <b>Complex→Sonnet</b>, <b>Daily→free</b> (pay only when the costly tiers fire).</label>` : ""}`;
      },
      next() { const r = $id("obRoute"); state.routing = r ? r.checked : false; return true; } },

    { label: "Voice", html: () => `
      <h2>Voice</h2>
      <label class="ob-check"><input id="obWake" type="checkbox" ${state.wake ? "checked" : ""}> Enable hands-free wake word ("Hey Atlas") — needs mic permission.</label>
      <button class="ob-btn ghost" id="obMic">Grant microphone access</button>
      <label class="ob-field"><span>Voice</span><select id="obVoice"></select></label>
      <div class="ob-voicerow"><button class="ob-btn ghost" id="obTestVoice">▶ Test voice</button>
        <span class="ob-result" id="obVres"></span></div>
      <p class="ob-fine">Voice STT/wake needs Chrome or Edge. Text chat always works everywhere.</p>`,
      async enter() {
        const sel = $id("obVoice");
        let vs = { voices: [{ id: "bm_george", label: "George (British male)" }], models_present: true };
        try { vs = await api("/api/voice/status"); } catch {}
        sel.innerHTML = (vs.voices || []).map(v => `<option value="${v.id}" ${v.id === state.voice ? "selected" : ""}>${esc(v.label)}</option>`).join("");
        sel.onchange = () => { state.voice = sel.value; };
        if (!vs.models_present) {
          $id("obVres").textContent = "Local voice not downloaded — using browser voice (or download in Settings).";
        }
        $id("obMic").onclick = async () => {
          try { await navigator.mediaDevices.getUserMedia({ audio: true }); t("Microphone enabled", "ok"); }
          catch { t("Mic denied — voice off, but text chat works", "err"); $id("obWake").checked = false; }
        };
        $id("obTestVoice").onclick = async () => {
          const r = $id("obVres"); r.textContent = "…";
          try {
            const resp = await fetch(API + "/api/tts", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "Good evening. ATLAS online and ready.", voice: sel.value }) });
            if (!resp.ok) throw 0;
            new Audio(URL.createObjectURL(await resp.blob())).play(); r.textContent = "✅ playing";
          } catch { r.textContent = "browser voice will be used"; }
        };
      },
      next() { state.wake = $id("obWake").checked; state.voice = $id("obVoice").value; return true; } },

    { label: "Connectors", html: () => `
      <h2>Capabilities</h2>
      <p class="ob-lede">Web search is on. These can be approved now (they activate when the integration ships):</p>
      <div class="ob-conn" id="obConn"></div>`,
      async enter() {
        let c = { proposed: [] };
        try { c = await api("/api/connectors"); } catch {}
        const meta = { calendar: "list/create events", email: "triage, summarize, draft" };
        $id("obConn").innerHTML = `<div class="ob-conncard on"><b>🔎 Web search</b><span>installed</span></div>` +
          (c.proposed || []).map(id => `<div class="ob-conncard"><b>${esc(id)}</b>
            <span>${meta[id] || ""} · data kept 90 days then auto-purged</span>
            <button class="ob-btn ghost sm" data-conn="${esc(id)}">${state.approved.has(id) ? "✓ approved" : "Approve"}</button></div>`).join("");
        $id("obConn").querySelectorAll("[data-conn]").forEach(b => b.onclick = async () => {
          try { await api("/api/connectors/approve", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ id: b.dataset.conn }) });
            state.approved.add(b.dataset.conn); b.textContent = "✓ approved"; b.disabled = true; }
          catch (e) { t("Approve failed: " + e.message, "err"); }
        });
      } },

    { label: "Privacy", html: () => `
      <h2>Privacy &amp; data</h2>
      <ul class="ob-checks ob-priv">
        <li>🔑 API keys are stored in the macOS Keychain — never in files or git.</li>
        <li>💾 Your name &amp; preferences live in a local vault on this machine.</li>
        <li>🗒 Conversations are saved locally; a daily 4 AM job <b>auto-deletes transcripts older than 90 days</b>.</li>
        <li>📅 Connector data (calendar/email) is retained 90 days, then purged.</li>
        <li>⏰ Scheduled jobs run unattended: consolidation 03:00, purge 04:00, health 23:55.</li>
      </ul>
      <label class="ob-check"><input id="obPriv" type="checkbox" ${state.privacyAck ? "checked" : ""}> I understand how ATLAS handles my data.</label>`,
      next() { if (!$id("obPriv").checked) { t("Please acknowledge to continue", "err"); return false; } state.privacyAck = true; return true; } },

    { label: "Done", html: () => `
      <h1>You're all set, <span class="ob-accent">${esc(state.ownerName || "Owner")}</span> ✨</h1>
      <ul class="ob-checks">
        <li>🗣 Say <b>"Hey Atlas"</b> (toggle 🎙 Wake) or click the orb to talk.</li>
        <li>💬 Click the chat bubble to type.</li>
        <li>⚙ Change anything in Settings anytime.</li>
      </ul>
      <p class="ob-result" id="obFinal"></p>` },
  ];

  /* ---------------- persistence between steps ---------------- */
  async function persistModel() {
    if (state.provider === "offline") return;
    try {
      const s = await api("/api/settings");
      s.model.mode = state.provider;
      if (s.model.routing) s.model.routing.enabled = (state.provider === "openrouter") && state.routing;
      s.voice = s.voice || {}; s.voice.tts_voice = "kokoro:" + state.voice; s.voice.wake_word_enabled = state.wake;
      await api("/api/settings", { method: "PUT", headers: { "Content-Type": "application/json" }, body: JSON.stringify(s) });
    } catch {}
  }

  async function finish() {
    await persistModel();
    try {
      await api("/api/onboarding/complete", { method: "POST", headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ owner_name: state.ownerName, identity_approved: state.identityApproved, privacy_acknowledged: state.privacyAck }) });
    } catch (e) { t("Finalize failed: " + e.message, "err"); }
    // final confirmation: a real test turn
    const fin = $id("obFinal");
    if (fin) { fin.textContent = "Checking…"; try {
      const d = await api("/api/chat", { method: "POST", headers: { "Content-Type": "application/json" }, body: JSON.stringify({ text: "In one short sentence, confirm you're online." }) });
      fin.textContent = "ATLAS: " + (d.reply || "online"); fin.className = "ob-result ok";
    } catch { fin.textContent = ""; } }
    setTimeout(() => { $id("onboarding").hidden = true; window.location.reload(); }, 1400);
  }

  /* ---------------- render ---------------- */
  function render() {
    const s = steps[step];
    const root = $id("onboarding");
    const last = step === steps.length - 1;
    root.querySelector(".ob-rail").innerHTML = steps.map((x, i) =>
      `<span class="ob-dot ${i === step ? "cur" : i < step ? "done" : ""}" title="${x.label}"></span>`).join("");
    const body = root.querySelector(".ob-body");
    body.innerHTML = s.html();
    const foot = root.querySelector(".ob-foot");
    foot.innerHTML = `${step > 0 && !last ? '<button class="ob-btn ghost" id="obBack">Back</button>' : "<span></span>"}
      <span class="ob-step">${step + 1} / ${steps.length}</span>
      <button class="ob-btn" id="obNext">${last ? "Launch ATLAS" : "Next"}</button>`;
    if (s.enter) s.enter(body);
    const back = $id("obBack"); if (back) back.onclick = () => { step--; render(); };
    $id("obNext").onclick = async () => {
      if (s.next && !(await s.next())) return;
      if (step === 3 || step === 4) await persistModel();   // save backend/voice as we go
      if (last) return finish();
      step++; render();
    };
  }

  async function start(force) {
    try { status = await fetch(API + "/api/onboarding/status").then(r => r.json()); }
    catch { return; }
    if (!force && status.completed) return;               // not first run
    if (status.owner_name && status.owner_name !== "Owner") state.ownerName = status.owner_name;
    step = 0; $id("onboarding").hidden = false; render();
  }

  window.atlasRunOnboarding = () => start(true);           // re-run from Settings
  document.addEventListener("DOMContentLoaded", () => start(false));
  if (document.readyState !== "loading") start(false);
})();
