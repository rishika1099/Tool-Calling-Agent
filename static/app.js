// Layer Lab frontend: chat on the left, day plan / outfit / closet on the right.

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const inputEl = $("#user-input");
const sendEl = $("#send");
const fileEl = $("#file-input");
const attachmentsEl = $("#attachments");

let sessionId = null;
let pending = []; // uploaded photos not yet sent: {id, url}
let lastOutfit = null; // latest build_outfit result, for the outfit panel
let closetItems = [];

const LOADING = ["Checking the forecast...", "Working out warmth...", "Looking through your closet..."];

// ---------- Small helpers ----------

function store(key, value) {
    try {
        value === null ? localStorage.removeItem(key) : localStorage.setItem(key, value);
    } catch (e) { /* storage can be blocked; the page still works */ }
}
function load(key) {
    try { return localStorage.getItem(key); } catch (e) { return null; }
}

function escapeHtml(text) {
    return text.replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
}

// Just enough markdown for the model's answers: paragraphs, bullet lists, **bold**.
function renderMarkdown(text) {
    const html = [];
    let list = null;
    for (const raw of (text || "").split("\n")) {
        const line = escapeHtml(raw.trim()).replace(/\*\*(.+?)\*\*/g, "<strong>$1</strong>");
        const bullet = line.match(/^[-*•]\s+(.*)/);
        if (bullet) {
            list = list || [];
            list.push(`<li>${bullet[1]}</li>`);
            continue;
        }
        if (list) { html.push(`<ul>${list.join("")}</ul>`); list = null; }
        if (line) html.push(`<p>${line}</p>`);
    }
    if (list) html.push(`<ul>${list.join("")}</ul>`);
    return html.join("");
}

// Simple garment silhouettes, filled with the item's color.
const SHAPES = {
    base_top: "M13 8 L6 13 L9 18 L13 16 L13 34 L27 34 L27 16 L31 18 L34 13 L27 8 Q20 12 13 8Z",
    mid_top: "M13 7 L5 14 L8 21 L13 18 L13 35 L27 35 L27 18 L32 21 L35 14 L27 7 Q20 11 13 7Z",
    outer: "M13 5 L5 12 L8 31 L13 29 L13 37 L27 37 L27 29 L32 31 L35 12 L27 5 L20 13Z",
    bottom: "M12 5 L28 5 L30 36 L22 36 L20 15 L18 36 L10 36Z",
    skirt: "M13 6 L27 6 L32 35 L8 35Z",
    one_piece: "M15 4 L25 4 L24 13 L31 36 L9 36 L16 13Z",
    legwear: "M14 5 L26 5 L25 36 L21 36 L20 14 L19 36 L15 36Z",
    socks: "M15 6 L23 6 L23 26 L31 28 L31 34 L15 34Z",
    shoes: "M6 25 L17 25 L19 19 L24 19 L25 25 Q34 26 34 31 L6 31Z",
    head: "M8 25 Q8 9 20 9 Q32 9 32 25Z M7 25 L33 25 L33 31 L7 31Z",
    hands: "M12 36 L12 18 L14 10 L17 10 L17 17 L18 8 L21 8 L21 17 L22 9 L25 9 L25 18 L27 12 L30 13 L28 26 L27 36Z",
    neck: "M8 10 Q20 18 32 10 L32 16 Q20 24 8 16Z M22 18 L27 36 L21 36 L18 20Z",
};
function garmentSvg(item) {
    const slot = item.slot || "base_top";
    const isSkirt = /skirt/.test(item.garment_type || "");
    const path = SHAPES[isSkirt ? "skirt" : slot] || SHAPES.base_top;
    const color = item.color || "#cccccc";
    return `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="${path}" fill="${color}" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/></svg>`;
}

// ---------- Session + closet ----------

async function refresh() {
    const qs = sessionId ? `?session_id=${encodeURIComponent(sessionId)}` : "";
    const res = await fetch(`/wardrobe${qs}`);
    const data = await res.json();
    sessionId = data.session_id;
    store("layerlab-session", sessionId);
    closetItems = data.items;
    renderSensitivity(data.cold_sensitivity);
    renderDay(data.last_plan);
    renderCloset(data.last_outfit || []);
    renderOutfit();
}

function renderSensitivity(level) {
    document.querySelectorAll(".segmented button").forEach((b) => {
        b.setAttribute("aria-checked", String(b.dataset.level === level));
    });
}

function renderCloset(selectedIds) {
    const el = $("#closet");
    el.innerHTML = "";
    for (const item of closetItems) {
        const btn = document.createElement("button");
        btn.className = `item ${item.status}${selectedIds.includes(item.id) ? " selected" : ""}`;
        btn.title = `${item.name}: ${item.status.replace("_", " ")}. Tap to toggle laundry.`;
        btn.innerHTML = `${garmentSvg(item)}<div>${escapeHtml(item.name)}</div>`;
        btn.addEventListener("click", () => toggleLaundry(item));
        el.appendChild(btn);
    }
}

async function toggleLaundry(item) {
    const status = item.status === "in_laundry" ? "clean" : "in_laundry";
    await fetch("/wardrobe/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, item_ids: [item.id], status }),
    });
    await refresh();
}

// ---------- Day plan ----------

const SETTING_LABEL = { outdoors: "Outside", indoors: "Indoors", transit: "Subway / bus" };

function renderDay(plan) {
    const el = $("#day");
    if (!plan) {
        el.className = "empty";
        el.textContent = "Your plan appears here once you describe your day.";
        $("#day-meta").textContent = "";
        return;
    }
    el.className = "timeline";
    $("#day-meta").textContent = `${plan.location} · ${plan.date}`;
    const max = 3;
    const pct = (v) => `${Math.min(100, (v / max) * 100)}%`;
    el.innerHTML = plan.segments.map((s) => {
        const cond = s.setting === "outdoors"
            ? `${s.temp_f}°F, feels ${s.feels_like_f}°F · wind ${s.wind_mph} mph · ${s.precip_chance_pct}% rain`
            : `${s.temp_f}°F inside`;
        const badges = `<span class="badge ${s.setting}">${SETTING_LABEL[s.setting]}</span>` +
            (s.rain ? `<span class="badge rain">rain</span>` : "") + (s.snow ? `<span class="badge rain">snow</span>` : "");
        return `<div class="seg">
            <time>${s.start}</time>
            <div>
                <div class="what">${escapeHtml(s.activity)} · ${s.minutes} min ${badges}</div>
                <div class="cond">${cond} · needs ${s.clo_min} to ${s.clo_ideal} clo</div>
                <div class="bar"><span class="range" style="left:${pct(s.clo_min)};width:calc(${pct(s.clo_ideal)} - ${pct(s.clo_min)} + 4px)"></span></div>
            </div>
        </div>`;
    }).join("") + `<div class="scale"><span>0 clo</span><span>1.5</span><span>3 clo</span></div>`;
}

// ---------- Outfit ----------

function verdictClass(text) {
    if (/too cold|cool/.test(text)) return "cold";
    if (/too warm/.test(text)) return "warm";
    return "good";
}

function renderOutfit() {
    const el = $("#outfit");
    const option = lastOutfit && lastOutfit.options && lastOutfit.options[0];
    if (!option) {
        el.className = "empty";
        el.textContent = "No outfit yet.";
        $("#outfit-meta").textContent = "";
        return;
    }
    el.className = "";
    const byId = Object.fromEntries(closetItems.map((i) => [i.id, i]));
    const t = lastOutfit.targets;
    $("#outfit-meta").textContent = lastOutfit.skipped_in_laundry.length
        ? `Skipped (laundry): ${lastOutfit.skipped_in_laundry.join(", ")}` : "";
    el.innerHTML = `
        <div class="outfit-items">${option.items.map((i) => `
            <span class="piece">${garmentSvg({ ...byId[i.id], slot: i.slot })}
                <span>${escapeHtml(i.name)}<br><small>${i.clo} clo</small></span></span>`).join("")}
        </div>
        <div class="fits">
            <div class="fit"><div class="label">Indoors</div>
                <div class="value">${option.indoor_clo} clo</div>
                <div class="verdict ${verdictClass(option.indoors)}">${option.indoors}${t.indoor_clo_ideal != null ? ` · target ${t.indoor_clo_ideal}` : ""}</div></div>
            <div class="fit"><div class="label">Outdoors</div>
                <div class="value">${option.outdoor_clo} clo</div>
                <div class="verdict ${verdictClass(option.outdoors)}">${option.outdoors}${t.outdoor_clo_ideal != null ? ` · target ${t.outdoor_clo_ideal}` : ""}</div></div>
        </div>
        ${option.take_off_indoors.length ? `<p class="notes" style="padding:0;margin-top:10px">Take off indoors: ${option.take_off_indoors.map(escapeHtml).join(", ")}</p>` : ""}
        ${option.notes.length ? `<ul class="notes">${option.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>` : ""}`;
}

// ---------- Chat ----------

function addUserMessage(text, photos) {
    const div = document.createElement("div");
    div.className = "msg user";
    div.textContent = text;
    for (const p of photos) {
        const img = document.createElement("img");
        img.className = "thumb";
        img.src = p.url;
        img.alt = `Attached photo ${p.id}`;
        div.appendChild(img);
    }
    messagesEl.appendChild(div);
}

function addAssistantMessage(response, toolCalls) {
    const div = document.createElement("div");
    div.className = "msg assistant";
    if (toolCalls.length) {
        const tools = document.createElement("div");
        tools.className = "tools";
        for (const call of toolCalls) {
            const details = document.createElement("details");
            let pretty = call.result;
            try { pretty = JSON.stringify(JSON.parse(call.result), null, 2); } catch (e) { /* not JSON */ }
            details.innerHTML = `<summary><b>${escapeHtml(call.name)}</b>(${escapeHtml(JSON.stringify(call.args)).slice(0, 90)})</summary>
                <pre>${escapeHtml(`args: ${JSON.stringify(call.args, null, 2)}\n\nresult: ${pretty}`)}</pre>`;
            tools.appendChild(details);
        }
        div.appendChild(tools);
    }
    const content = document.createElement("div");
    content.className = "content";
    content.innerHTML = renderMarkdown(response);
    div.appendChild(content);
    messagesEl.appendChild(div);
}

async function sendMessage(text) {
    text = text.trim();
    if (!text && !pending.length) return;
    $("#intro")?.remove();
    const photos = pending;
    pending = [];
    renderAttachments();
    const message = photos.length ? `${text}\n\n[Attached photos: ${photos.map((p) => p.id).join(", ")}]` : text;

    addUserMessage(text, photos);
    inputEl.value = "";
    autosize();
    sendEl.disabled = true;

    const loading = document.createElement("div");
    loading.className = "msg assistant loading";
    let tick = 0;
    loading.textContent = LOADING[0];
    const timer = setInterval(() => { loading.textContent = LOADING[++tick % LOADING.length]; }, 1800);
    messagesEl.appendChild(loading);
    messagesEl.scrollTop = messagesEl.scrollHeight;

    try {
        const res = await fetch("/chat", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ message, session_id: sessionId }),
        });
        const data = await res.json();
        sessionId = data.session_id;
        for (const call of data.tool_calls) {
            if (call.name === "build_outfit") {
                try {
                    const parsed = JSON.parse(call.result);
                    if (parsed.options) lastOutfit = parsed;
                } catch (e) { /* ignore */ }
            }
        }
        loading.remove();
        addAssistantMessage(data.response, data.tool_calls);
        await refresh();
    } catch (e) {
        loading.remove();
        addAssistantMessage(`Something went wrong: ${e.message}`, []);
    } finally {
        clearInterval(timer);
        sendEl.disabled = false;
        messagesEl.scrollTop = messagesEl.scrollHeight;
        inputEl.focus();
    }
}

// ---------- Photo uploads ----------

function renderAttachments() {
    attachmentsEl.hidden = !pending.length;
    attachmentsEl.innerHTML = "";
    pending.forEach((p, i) => {
        const fig = document.createElement("figure");
        fig.innerHTML = `<img src="${p.url}" alt="Photo ${p.id}"><figcaption>${p.id}</figcaption><button type="button" aria-label="Remove">×</button>`;
        fig.querySelector("button").addEventListener("click", () => { pending.splice(i, 1); renderAttachments(); });
        attachmentsEl.appendChild(fig);
    });
}

fileEl.addEventListener("change", async () => {
    for (const file of fileEl.files) {
        const form = new FormData();
        form.append("session_id", sessionId);
        form.append("file", file);
        const res = await fetch("/upload", { method: "POST", body: form });
        if (!res.ok) {
            const err = await res.json().catch(() => ({}));
            alert(err.detail || "Upload failed.");
            continue;
        }
        const data = await res.json();
        pending.push({ id: data.image_id, url: data.url });
    }
    fileEl.value = "";
    renderAttachments();
});

// ---------- Wiring ----------

function autosize() {
    inputEl.style.height = "auto";
    inputEl.style.height = `${Math.min(inputEl.scrollHeight, 140)}px`;
}

$("#composer").addEventListener("submit", (e) => { e.preventDefault(); sendMessage(inputEl.value); });
inputEl.addEventListener("input", autosize);
inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) { e.preventDefault(); sendMessage(inputEl.value); }
});
document.querySelectorAll(".examples .chip").forEach((chip) => {
    chip.addEventListener("click", () => sendMessage(chip.textContent));
});
document.querySelectorAll(".segmented button").forEach((btn) => {
    btn.addEventListener("click", async () => {
        await fetch("/profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, cold_sensitivity: btn.dataset.level }),
        });
        renderSensitivity(btn.dataset.level);
    });
});
$("#new-day").addEventListener("click", async () => {
    await fetch(`/clear?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" });
    sessionId = null;
    store("layerlab-session", null);
    location.reload();
});

sessionId = load("layerlab-session");
refresh();
