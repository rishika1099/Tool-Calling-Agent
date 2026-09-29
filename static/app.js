// Layer Lab frontend: chat on the left, your day / layers / closet on the right, a live sky behind.
// Motion uses anime.js v4 (window.anime). Effects are plain-JS versions of ideas from
// reactbits.dev and originkit.dev: variable-proximity text, rotating text, blur-in text,
// spotlight + tilt cards, click sparks.

const $ = (sel) => document.querySelector(sel);
const messagesEl = $("#messages");
const inputEl = $("#user-input");
const sendEl = $("#send");
const fileEl = $("#file-input");
const attachmentsEl = $("#attachments");

const reduceMotion = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
const finePointer = window.matchMedia("(pointer: fine)").matches;
const A = !reduceMotion && window.anime?.animate ? window.anime : null;

let sessionId = null;
let pending = []; // uploaded photos not yet sent: {id, url}
let lastOutfit = null; // latest build_outfit result
let closetItems = [];
let shownPlan = null; // what the panels last animated, so a refresh doesn't replay
let shownOutfit = null;
let closetShown = false;

const LOADING = ["Checking the forecast", "Working out warmth", "Going through your closet", "Layering it up"];
const PHRASES = ["walk to class.", "bus stop at 6pm.", "three-hour lecture.", "first snow.", "subway platform.", "8am interview."];

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
    return String(text).replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" })[c]);
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

// Thermal color for a clo need: little clothing needed = warm amber, a lot = cold blue.
const cssVar = (name) => getComputedStyle(document.documentElement).getPropertyValue(name).trim();
function hexRgb(h) { return [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16)); }
function thermal(clo) {
    const stops = [[0, cssVar("--hot")], [0.9, cssVar("--warm")], [1.6, cssVar("--cool")], [2.6, cssVar("--cold")]];
    for (let i = 1; i < stops.length; i++) {
        if (clo <= stops[i][0] || i === stops.length - 1) {
            const [x0, c0] = stops[i - 1], [x1, c1] = stops[i];
            const k = Math.max(0, Math.min(1, (clo - x0) / (x1 - x0)));
            const a = hexRgb(c0), b = hexRgb(c1);
            return `rgb(${a.map((v, j) => Math.round(v + (b[j] - v) * k)).join(",")})`;
        }
    }
}
function textOn(hex) {
    if (!/^#[0-9a-f]{6}$/i.test(hex || "")) return "#fff";
    const [r, g, b] = hexRgb(hex).map((v) => v / 255);
    return 0.299 * r + 0.587 * g + 0.114 * b > 0.62 ? "#0e1a2b" : "#ffffff";
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
    const isSkirt = /skirt/.test(item.garment_type || "");
    const path = SHAPES[isSkirt ? "skirt" : item.slot] || SHAPES.base_top;
    return `<svg viewBox="0 0 40 40" aria-hidden="true"><path d="${path}" fill="${item.color || "#cccccc"}" stroke="currentColor" stroke-opacity="0.25" stroke-width="1"/></svg>`;
}

// ---------- Motion helpers ----------

function enter(targets, { delay = 60, y = 12, blur = 0, duration = 620 } = {}) {
    if (!A) return;
    const params = { opacity: { from: 0 }, translateY: { from: y }, duration, delay: A.stagger(delay), ease: "outExpo" };
    if (blur) params.filter = { from: `blur(${blur}px)`, to: "blur(0px)" };
    A.animate(targets, params);
}

function countUp(el) {
    const to = parseFloat(el.textContent);
    if (!A || Number.isNaN(to)) return;
    const state = { v: 0 };
    A.animate(state, { v: to, duration: 1100, ease: "outExpo", onUpdate: () => { el.textContent = state.v.toFixed(2); } });
}

function splitChars(el, text) {
    el.textContent = "";
    for (const ch of text) {
        const span = document.createElement("span");
        span.className = "ch";
        span.textContent = ch;
        el.appendChild(span);
    }
    return el.querySelectorAll(".ch");
}

// Wrap each word of an element's text in a span, keeping <strong>, lists and paragraphs.
function splitWords(root) {
    const walker = document.createTreeWalker(root, NodeFilter.SHOW_TEXT);
    const nodes = [];
    while (walker.nextNode()) nodes.push(walker.currentNode);
    for (const node of nodes) {
        const frag = document.createDocumentFragment();
        for (const part of node.textContent.split(/(\s+)/)) {
            if (!part) continue;
            if (/^\s+$/.test(part)) { frag.appendChild(document.createTextNode(part)); continue; }
            const span = document.createElement("span");
            span.className = "w";
            span.textContent = part;
            frag.appendChild(span);
        }
        node.replaceWith(frag);
    }
    return root.querySelectorAll(".w");
}

// Spotlight + tilt: CSS reads --mx/--my (spotlight) and --rx/--ry (tilt).
function attachSpotlight(el, tilt = 0) {
    if (!finePointer || reduceMotion) return;
    el.addEventListener("pointermove", (e) => {
        const r = el.getBoundingClientRect();
        const x = e.clientX - r.left, y = e.clientY - r.top;
        el.style.setProperty("--mx", `${x}px`);
        el.style.setProperty("--my", `${y}px`);
        if (tilt) {
            el.style.setProperty("--ry", `${((x / r.width) - 0.5) * tilt}deg`);
            el.style.setProperty("--rx", `${(0.5 - (y / r.height)) * tilt}deg`);
        }
    });
    el.addEventListener("pointerleave", () => {
        el.style.setProperty("--rx", "0deg");
        el.style.setProperty("--ry", "0deg");
    });
}

// Click spark (reactbits' Click Spark): a burst of short lines from the click point.
function spark(x, y) {
    if (!A) return;
    for (let i = 0; i < 10; i++) {
        const s = document.createElement("span");
        s.className = "spark";
        s.style.left = `${x}px`;
        s.style.top = `${y}px`;
        const angle = (i / 10) * 360;
        s.style.rotate = `${angle}deg`;
        document.body.appendChild(s);
        const rad = (angle - 90) * Math.PI / 180;
        A.animate(s, {
            translateX: Math.cos(rad) * 34, translateY: Math.sin(rad) * 34,
            scaleY: { from: 1, to: 0 }, opacity: { from: 1, to: 0 },
            duration: 520, ease: "outQuart", onComplete: () => s.remove(),
        });
    }
}

// ---------- Hero: variable-proximity heading + rotating phrase ----------

function setupHero() {
    const pressure = document.querySelector(".pressure");
    const rotator = $("#rotator");
    if (!pressure) return;
    const chars = [...splitChars(pressure, pressure.dataset.text)];
    let phrase = 0;
    splitChars(rotator, PHRASES[0]);

    if (A) {
        A.animate(chars, { opacity: { from: 0 }, translateY: { from: "0.4em" }, filter: { from: "blur(10px)", to: "blur(0px)" },
            duration: 900, delay: A.stagger(35), ease: "outExpo" });
        A.animate(rotator.querySelectorAll(".ch"), { opacity: { from: 0 }, translateY: { from: "0.5em" },
            duration: 800, delay: A.stagger(25, { start: 420 }), ease: "outExpo" });
        enter(".hero .lede, .hero .prompt", { delay: 70, y: 16, duration: 800 });
        enter(".mark i", { delay: 90, y: 0 });
        A.animate(".mark i", { scaleX: { from: 0 }, duration: 900, delay: A.stagger(90), ease: "outExpo" });
    }

    // Letters get heavier and softer as the pointer approaches (Fraunces variable axes).
    if (finePointer && !reduceMotion) {
        let px = -9999, py = -9999, queued = false;
        const update = () => {
            queued = false;
            for (const ch of chars) {
                const r = ch.getBoundingClientRect();
                const d = Math.hypot(px - (r.left + r.width / 2), py - (r.top + r.height / 2));
                const k = Math.max(0, 1 - d / 240);
                ch.style.fontVariationSettings = `"wght" ${Math.round(400 + 500 * k)}, "opsz" 144, "SOFT" ${Math.round(30 + 70 * k)}`;
            }
        };
        const hero = $("#intro");
        hero.addEventListener("pointermove", (e) => {
            px = e.clientX; py = e.clientY;
            if (!queued) { queued = true; requestAnimationFrame(update); }
        });
        hero.addEventListener("pointerleave", () => { px = py = -9999; requestAnimationFrame(update); });
    }

    // Rotating phrase: old letters lift out, new ones rise in.
    setInterval(() => {
        if (!document.body.contains(rotator)) return;
        phrase = (phrase + 1) % PHRASES.length;
        if (!A) { rotator.textContent = PHRASES[phrase]; return; }
        A.animate(rotator.querySelectorAll(".ch"), {
            opacity: { to: 0 }, translateY: { to: "-0.45em" }, filter: { to: "blur(6px)" },
            duration: 380, delay: A.stagger(14), ease: "inQuad",
            onComplete: () => {
                const next = splitChars(rotator, PHRASES[phrase]);
                A.animate(next, { opacity: { from: 0 }, translateY: { from: "0.5em" }, filter: { from: "blur(6px)", to: "blur(0px)" },
                    duration: 700, delay: A.stagger(20), ease: "outExpo" });
            },
        });
    }, 2800);

    document.querySelectorAll(".prompt").forEach((p) => {
        attachSpotlight(p);
        p.addEventListener("click", () => sendMessage(p.querySelector(".txt").textContent));
    });
}

// ---------- Live conditions -> sky ----------

async function loadConditions() {
    try {
        const res = await fetch("/conditions");
        if (!res.ok) throw new Error();
        const c = await res.json();
        $("#now").textContent = `${c.temp_f}°F in ${c.location} right now · feels ${c.feels_like_f}°F · wind ${c.wind_mph} mph`;
        window.Sky?.set({
            mode: c.snow ? "snow" : c.rain ? "rain" : "calm",
            warmth: (c.temp_f - 15) / 65,
            wind: c.wind_mph / 25,
        });
    } catch (e) {
        $("#now").textContent = "New York · live weather unavailable";
    }
}

function skyFromPlan(plan) {
    const s = plan.summary || {};
    window.Sky?.set({
        mode: s.snow_expected ? "snow" : s.rain_expected ? "rain" : "calm",
        warmth: s.outdoor_clo_ideal != null ? 1 - (s.outdoor_clo_ideal - 0.3) / 2.4 : undefined,
        wind: (s.max_wind_mph || 0) / 25,
    });
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

let thumbPlaced = false;
function renderSensitivity(level) {
    const buttons = [...document.querySelectorAll(".thermostat button")];
    buttons.forEach((b) => b.setAttribute("aria-checked", String(b.dataset.level === level)));
    const active = buttons.find((b) => b.dataset.level === level);
    const thumb = $(".thermostat .thumb");
    if (!active) return;
    const to = { translateX: active.offsetLeft, width: active.offsetWidth };
    if (A && thumbPlaced) {
        A.animate(thumb, { ...to, duration: 650, ease: "outElastic(1, .7)" });
    } else {
        thumb.style.transform = `translateX(${to.translateX}px)`;
        thumb.style.width = `${to.width}px`;
    }
    thumbPlaced = true;
}

function renderCloset(selectedIds) {
    const el = $("#closet");
    el.innerHTML = "";
    for (const item of closetItems) {
        const btn = document.createElement("button");
        btn.className = `item ${item.status}${selectedIds.includes(item.id) ? " selected" : ""}`;
        btn.dataset.id = item.id;
        btn.title = `${item.name}: ${item.status.replace("_", " ")}. Tap to toggle laundry.`;
        btn.innerHTML = `${garmentSvg(item)}<div>${escapeHtml(item.name)}</div><span class="clo">${item.clo} clo</span>`;
        btn.addEventListener("click", () => toggleLaundry(item, btn));
        attachSpotlight(btn, 14);
        el.appendChild(btn);
    }
    if (!closetShown && closetItems.length) {
        closetShown = true;
        if (A) A.animate("#closet .item", { opacity: { from: 0 }, scale: { from: 0.85 }, duration: 700,
            delay: A.stagger(22, { grid: [3, Math.ceil(closetItems.length / 3)], from: "first" }), ease: "outExpo" });
    }
}

async function toggleLaundry(item, btn) {
    const status = item.status === "in_laundry" ? "clean" : "in_laundry";
    if (A) await A.animate(btn, { scale: [1, 0.9, 1], duration: 380, ease: "outQuad" });
    await fetch("/wardrobe/status", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, item_ids: [item.id], status }),
    });
    await refresh();
}

// ---------- Your day: thermal ribbon ----------

const SETTING = { outdoors: "Outside", indoors: "Indoors", transit: "Subway / bus" };
const ACTIVITY = { sitting: "Sitting", standing: "Standing", walking: "Walking", biking: "Biking" };

function renderDay(plan) {
    const el = $("#day");
    if (!plan) {
        el.className = "empty";
        el.textContent = "Describe your day and it maps out here, coldest stretches in blue.";
        $("#day-meta").textContent = "";
        return;
    }
    el.className = "";
    $("#day-meta").textContent = `${plan.location} · ${plan.date}`;
    const alerts = (plan.active_alerts || []).map((a) =>
        `<div class="alert"><strong>${escapeHtml(a.event)}</strong><span>${escapeHtml(a.headline || "")}</span></div>`).join("");
    const bands = plan.segments.map((s) => `
        <div class="band ${s.setting === "outdoors" ? "" : "inside"}" style="flex:${Math.max(s.minutes, 15)} 1 0;background-color:${thermal(s.clo_ideal)}"
             title="${s.start} · ${SETTING[s.setting]} · needs ${s.clo_min} to ${s.clo_ideal} clo">
            <time>${s.start}</time><span>${s.clo_ideal}</span>
        </div>`).join("");
    const rows = plan.segments.map((s) => {
        const cond = s.setting === "outdoors"
            ? `${s.temp_f}°F, feels ${s.feels_like_f}°F · ${s.wind_mph} mph wind${s.rain ? " · rain" : ""}${s.snow ? " · snow" : ""}`
            : `${s.temp_f}°F · ${s.note || ""}`;
        return `<li><time>${s.start}</time>
            <div><div class="what">${ACTIVITY[s.activity] || s.activity} ${SETTING[s.setting].toLowerCase()} · ${s.minutes} min</div><div class="cond">${escapeHtml(cond)}</div></div>
            <span class="need">${s.clo_min} to ${s.clo_ideal} clo</span></li>`;
    }).join("");
    el.innerHTML = `${alerts}<div class="ribbon">${bands}</div>
        <div class="legend"><span>warm</span><span class="scale"></span><span>cold</span></div>
        <ul class="segs">${rows}</ul>`;

    const key = JSON.stringify(plan);
    if (key !== shownPlan) {
        shownPlan = key;
        skyFromPlan(plan);
        if (A) {
            A.animate("#day .ribbon .band", { scaleX: { from: 0 }, opacity: { from: 0 }, duration: 900, delay: A.stagger(110), ease: "outExpo" });
            enter("#day .alert, #day .segs li", { delay: 70, y: 10 });
        }
    }
}

// ---------- Your layers: stack + thermometers ----------

const STACK_ORDER = ["outer", "mid_top", "base_top", "one_piece", "bottom", "legwear", "socks", "shoes"];
const SLOT_LABEL = { outer: "outer", mid_top: "mid", base_top: "base", one_piece: "dress", bottom: "bottom", legwear: "legs", socks: "socks", shoes: "shoes" };

function verdictClass(text) {
    if (/too cold|cool/.test(text)) return "cold";
    if (/too warm/.test(text)) return "warm";
    return "good";
}

function gauge(label, value, target, verdict) {
    const scale = 3;
    const pct = (v) => `${Math.min(100, (v / scale) * 100)}%`;
    return `<div class="gauge">
        <div class="tube"><div class="fill" style="--p:${pct(value)}"></div>${target != null ? `<div class="target" style="--t:${pct(target)}"></div>` : ""}</div>
        <div class="value num">${value}</div>
        <div class="label">${label}${target != null ? `<br>target ${target}` : ""}</div>
        <div class="verdict ${verdictClass(verdict)}">${escapeHtml(verdict)}</div>
    </div>`;
}

// Flex carousel of outfit suggestions (after reactbits' FlexCarousel: preset "liquid",
// intro "rise", squeeze 0.2, gap 12, focusOnClick, captions). Each card's "image" is the
// option's fabric stack in the clothes' real colors. The focused card drives the detail view.
const CAROUSEL = { focusGrow: 2.6, squeeze: 0.2, rise: 36 };
let optionIndex = 0;

// Options usually share the coat, so lead with what differs: the dress, or top + bottom.
function optionTitle(option) {
    const find = (slot) => option.items.find((i) => i.slot === slot)?.name;
    return find("one_piece") || [find("base_top"), find("bottom")].filter(Boolean).join(" + ");
}
function optionSubtitle(option) {
    const outer = option.items.find((i) => i.slot === "outer")?.name;
    return `${outer ? `under the ${outer.toLowerCase()}` : "no coat"} · ${option.outdoor_clo} clo out`;
}

function carousel(options, byId) {
    return `<div class="flex-carousel" role="group" aria-label="Outfit suggestions">${options.map((o, i) => {
        const worn = o.items.filter((x) => STACK_ORDER.includes(x.slot))
            .sort((a, b) => STACK_ORDER.indexOf(a.slot) - STACK_ORDER.indexOf(b.slot));
        const stripes = worn.map((x) => `<i style="background:${byId[x.id]?.color || "#ccc"};flex:${(x.clo + 0.08).toFixed(2)}"></i>`).join("");
        return `<button class="fc-card${i === optionIndex ? " is-focus" : ""}" data-i="${i}" aria-pressed="${i === optionIndex}"
                    style="flex-grow:${i === optionIndex ? CAROUSEL.focusGrow : 1}">
            <span class="fc-swatch" aria-hidden="true">${stripes}</span>
            <span class="fc-index">${String(i + 1).padStart(2, "0")}</span>
            <span class="fc-caption"><b>${escapeHtml(optionTitle(o))}</b><small>${escapeHtml(optionSubtitle(o))}</small></span>
        </button>`;
    }).join("")}</div>`;
}

function focusCard(index) {
    if (index === optionIndex) return;
    optionIndex = index;
    const cards = [...document.querySelectorAll("#outfit .fc-card")];
    cards.forEach((c, i) => {
        const on = i === index;
        c.classList.toggle("is-focus", on);
        c.setAttribute("aria-pressed", String(on));
        if (!A) { c.style.flexGrow = on ? CAROUSEL.focusGrow : 1; return; }
        // "Liquid": a soft spring on the width, with a small squeeze on the others.
        const spring = A.createSpring ? A.createSpring({ stiffness: 140, damping: 13 }) : "outElastic(1, .75)";
        A.animate(c, { flexGrow: on ? CAROUSEL.focusGrow : 1, scaleY: on ? 1 : 1 - CAROUSEL.squeeze * 0.25, ease: spring, duration: 900 });
    });
    renderOptionDetail(true);
    highlightCloset();
}

function highlightCloset() {
    const ids = lastOutfit?.options?.[optionIndex]?.items.map((i) => i.id) || [];
    document.querySelectorAll("#closet .item").forEach((el) => el.classList.toggle("selected", ids.includes(el.dataset.id)));
}

function renderOptionDetail(animate) {
    const option = lastOutfit.options[optionIndex];
    const byId = Object.fromEntries(closetItems.map((i) => [i.id, i]));
    const t = lastOutfit.targets;
    const worn = option.items.filter((i) => STACK_ORDER.includes(i.slot))
        .sort((a, b) => STACK_ORDER.indexOf(a.slot) - STACK_ORDER.indexOf(b.slot));
    const extras = option.items.filter((i) => !STACK_ORDER.includes(i.slot));
    const layers = worn.map((i) => {
        const color = byId[i.id]?.color || "#cccccc";
        return `<div class="layer" style="--c:${color};--on:${textOn(color)};min-height:${Math.round(26 + i.clo * 46)}px">
            ${escapeHtml(i.name)}<span class="slot">${SLOT_LABEL[i.slot]}</span><small>${i.clo}</small></div>`;
    }).join("");

    $("#option-detail").innerHTML = `
        <div class="fit-grid">
            <div>
                <div class="stack">${layers}</div>
                ${extras.length ? `<div class="extras">${extras.map((i) => `<span>+ ${escapeHtml(i.name)}</span>`).join("")}</div>` : ""}
            </div>
            <div class="gauges">
                ${gauge("Outdoors", option.outdoor_clo, t.outdoor_clo_ideal, option.outdoors)}
                ${gauge("Indoors", option.indoor_clo, t.indoor_clo_ideal, option.indoors)}
            </div>
        </div>
        ${option.take_off_indoors.length ? `<p class="takeoff">Take off indoors: <b>${option.take_off_indoors.map(escapeHtml).join(", ")}</b></p>` : ""}
        ${option.notes.length ? `<ul class="notes">${option.notes.map((n) => `<li>${escapeHtml(n)}</li>`).join("")}</ul>` : ""}`;

    if (animate && A) {
        // Get dressed from the inside out: base layer first, coat last.
        A.animate("#option-detail .layer", { opacity: { from: 0 }, translateY: { from: -18 }, scaleX: { from: 0.92 },
            duration: 700, delay: A.stagger(90, { from: "last" }), ease: "outBack(1.4)" });
        A.animate("#option-detail .tube .fill", { scaleY: { from: 0 }, duration: 1200, delay: 200, ease: "outExpo" });
        document.querySelectorAll("#option-detail .num").forEach(countUp);
        enter("#option-detail .extras span, #option-detail .takeoff, #option-detail .notes li", { delay: 50, y: 8 });
    }
}

function renderOutfit() {
    const el = $("#outfit");
    if (!lastOutfit?.options?.length) {
        el.className = "empty";
        el.textContent = "Your outfit appears here as a stack of layers, next to how warm it keeps you.";
        $("#outfit-meta").textContent = "";
        return;
    }
    const fresh = lastOutfit !== shownOutfit;
    if (fresh) optionIndex = 0;
    el.className = "";
    const byId = Object.fromEntries(closetItems.map((i) => [i.id, i]));
    $("#outfit-meta").textContent = lastOutfit.skipped_in_laundry.length ? `Skipped: ${lastOutfit.skipped_in_laundry.join(", ")}` : "";
    el.innerHTML = `${lastOutfit.options.length > 1 ? carousel(lastOutfit.options, byId) : ""}<div id="option-detail"></div>`;
    el.querySelectorAll(".fc-card").forEach((card) => {
        card.addEventListener("click", () => focusCard(Number(card.dataset.i)));
        attachSpotlight(card);
    });
    renderOptionDetail(fresh);
    highlightCloset();

    if (fresh) {
        shownOutfit = lastOutfit;
        // "Rise" intro for the suggestions.
        if (A) A.animate("#outfit .fc-card", { opacity: { from: 0 }, translateY: { from: CAROUSEL.rise }, duration: 900,
            delay: A.stagger(90), ease: "outExpo" });
    }
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
    if (A) A.animate(div, { opacity: { from: 0 }, translateX: { from: 24 }, scale: { from: 0.96 }, duration: 600, ease: "outExpo" });
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
            details.innerHTML = `<summary><b>${escapeHtml(call.name)}</b></summary>
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

    if (A) {
        A.animate(div.querySelectorAll(".tools details"), { opacity: { from: 0 }, scale: { from: 0.7 }, duration: 500,
            delay: A.stagger(70), ease: "outBack(1.8)" });
        const words = [...splitWords(content)];
        const start = toolCalls.length * 70 + 150;
        A.animate(words, { opacity: { from: 0 }, filter: { from: "blur(8px)", to: "blur(0px)" }, translateY: { from: 6 },
            duration: 600, delay: A.stagger(Math.max(6, Math.min(18, 900 / words.length)), { start }), ease: "outQuad" });
    }
}

async function sendMessage(text) {
    text = text.trim();
    if (!text && !pending.length) return;
    const intro = $("#intro");
    if (intro) {
        if (A) await A.animate(intro, { opacity: 0, translateY: -20, filter: "blur(8px)", duration: 350, ease: "inQuad" });
        intro.remove();
    }
    const photos = pending;
    pending = [];
    renderAttachments();
    const message = photos.length ? `${text}\n\n[Attached photos: ${photos.map((p) => p.id).join(", ")}]` : text;

    addUserMessage(text, photos);
    inputEl.value = "";
    autosize();
    sendEl.disabled = true;

    const loading = document.createElement("div");
    loading.className = "shimmer";
    let tick = 0;
    loading.textContent = `${LOADING[0]}...`;
    const timer = setInterval(() => { loading.textContent = `${LOADING[++tick % LOADING.length]}...`; }, 1800);
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
            if (call.name !== "build_outfit") continue;
            try {
                const parsed = JSON.parse(call.result);
                if (parsed.options) lastOutfit = parsed;
            } catch (e) { /* ignore */ }
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
        messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: reduceMotion ? "auto" : "smooth" });
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
    enter("#attachments figure:last-child", { y: 6 });
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
sendEl.addEventListener("click", (e) => spark(e.clientX, e.clientY));
inputEl.addEventListener("input", autosize);
inputEl.addEventListener("keydown", (e) => {
    if (e.key === "Enter" && !e.shiftKey) {
        e.preventDefault();
        const r = sendEl.getBoundingClientRect();
        spark(r.left + r.width / 2, r.top + r.height / 2);
        sendMessage(inputEl.value);
    }
});
document.querySelectorAll(".thermostat button").forEach((btn) => {
    btn.addEventListener("click", async () => {
        renderSensitivity(btn.dataset.level);
        await fetch("/profile", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, cold_sensitivity: btn.dataset.level }),
        });
    });
});
$("#new-day").addEventListener("click", async () => {
    await fetch(`/clear?session_id=${encodeURIComponent(sessionId)}`, { method: "POST" });
    sessionId = null;
    store("layerlab-session", null);
    location.reload();
});
document.querySelectorAll(".spot").forEach((el) => attachSpotlight(el));
window.addEventListener("resize", () => {
    const active = document.querySelector('.thermostat button[aria-checked="true"]');
    if (active) { thumbPlaced = false; renderSensitivity(active.dataset.level); }
});

sessionId = load("layerlab-session");
setupHero();
loadConditions();
document.fonts.ready.then(refresh);
