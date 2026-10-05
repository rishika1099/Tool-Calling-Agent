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
let catalog = null; // garment types and fibers for the Add clothes form
let personPhotoId = null;
const photoUrl = (id) => `/image/${encodeURIComponent(sessionId)}/${encodeURIComponent(id)}`;

const LOADING = ["Checking the forecast", "Working out warmth", "Going through your closet", "Layering it up"];
const LOADING_TRYON = ["Getting your photo", "Dressing you in the outfit", "Painting the preview", "Almost there"];
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

// Wait for an animation, but never much longer than it should take. Browsers pause animations in
// a background tab; sending a message or leaving the intro must still go through there.
function finish(animation, ms) {
    return Promise.race([animation, new Promise((resolve) => setTimeout(resolve, ms))]);
}

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

let heroReady = false;
function setupHero() {
    if (heroReady) return;
    heroReady = true;
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

// The phone's browser bar takes the scene's color: the dark room at the intro, then day or night sky.
function setChromeColor() {
    const meta = document.querySelector('meta[name="theme-color"]');
    if (!meta) return;
    meta.content = document.body.classList.contains("at-portal") ? "#1c1814"
        : document.documentElement.dataset.theme === "dark" ? "#0b1424" : "#2f72d6";
}

async function loadConditions() {
    try {
        const res = await fetch("/conditions");
        if (!res.ok) throw new Error();
        const c = await res.json();
        $("#now").textContent = `${c.temp_f}°F in ${c.location} right now · feels ${c.feels_like_f}°F · wind ${c.wind_mph} mph`;
        const portalTemp = $("#portal-temp");
        if (portalTemp) portalTemp.textContent = `${c.temp_f}°F · ${c.location}`;
        const isNight = c.is_day === false;
        document.documentElement.dataset.theme = isNight ? "dark" : "light";
        setChromeColor();
        window.Sky?.set({
            night: isNight,
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
    personPhotoId = data.person_photo_id;
    renderMe();
    renderCoverage();
    return data;
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
    // Your own clothes first, then the demo closet.
    const ordered = [...closetItems].sort((a, b) => (b.user_added ? 1 : 0) - (a.user_added ? 1 : 0));
    for (const item of ordered) {
        const cell = document.createElement("div");
        cell.className = "item-cell";
        const btn = document.createElement("button");
        btn.className = `item ${item.status}${selectedIds.includes(item.id) ? " selected" : ""}${item.photo_url ? " has-photo" : ""}`;
        btn.dataset.id = item.id;
        const wearNote = item.wear_limit ? ` · worn ${item.wears}/${item.wear_limit}` : "";
        btn.title = `${item.name}: ${item.status.replace("_", " ")}${wearNote}. Tap to toggle laundry.`;
        const visual = item.photo_url ? `<img class="photo" src="${item.photo_url}" alt="" loading="lazy">` : garmentSvg(item);
        btn.innerHTML = `${visual}<div>${escapeHtml(item.name)}</div><span class="clo">${item.clo} clo</span>`;
        btn.addEventListener("click", () => toggleLaundry(item, btn));
        attachSpotlight(btn, 14);
        cell.appendChild(btn);
        if (item.user_added) {
            const rm = document.createElement("button");
            rm.className = "rm";
            rm.type = "button";
            rm.setAttribute("aria-label", `Remove ${item.name}`);
            rm.textContent = "×";
            rm.addEventListener("click", () => removeItem(item, cell));
            cell.appendChild(rm);
        }
        el.appendChild(cell);
    }
    if (!closetShown && closetItems.length) {
        closetShown = true;
        if (A) A.animate("#closet .item", { opacity: { from: 0 }, scale: { from: 0.85 }, duration: 700,
            delay: A.stagger(22, { grid: [3, Math.ceil(closetItems.length / 3)], from: "first" }), ease: "outExpo" });
    }
}

async function removeItem(item, cell) {
    if (A) await finish(A.animate(cell, { opacity: 0, scale: 0.8, duration: 300, ease: "inQuad" }), 500);
    await fetch(`/wardrobe/item?session_id=${encodeURIComponent(sessionId)}&item_id=${encodeURIComponent(item.id)}`, { method: "DELETE" });
    await refresh();
}

async function toggleLaundry(item, btn) {
    const status = item.status === "in_laundry" ? "clean" : "in_laundry";
    if (A) await finish(A.animate(btn, { scale: [1, 0.9, 1], duration: 380, ease: "outQuad" }), 600);
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
        const key = ["outer", "mid_top", "one_piece", "base_top", "bottom", "shoes"]
            .map((sl) => o.items.find((x) => x.slot === sl)).filter(Boolean).slice(0, 4);
        const collage = key.some((x) => byId[x.id]?.photo_url)
            ? `<span class="fc-collage n${key.length}" aria-hidden="true">${key.map((x) => byId[x.id]?.photo_url
                ? `<img src="${byId[x.id].photo_url}" alt="">`
                : `<span style="background:${byId[x.id]?.color || "#ccc"}">${garmentSvg({ ...byId[x.id], slot: x.slot })}</span>`).join("")}</span>`
            : "";
        return `<button class="fc-card${i === optionIndex ? " is-focus" : ""}" data-i="${i}" aria-pressed="${i === optionIndex}"
                    style="flex-grow:${i === optionIndex ? CAROUSEL.focusGrow : 1}">
            ${collage || `<span class="fc-swatch" aria-hidden="true">${stripes}</span>`}
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
        const thumb = byId[i.id]?.photo_url ? `<img class="lthumb" src="${byId[i.id].photo_url}" alt="">` : "";
        return `<div class="layer" style="--c:${color};--on:${textOn(color)};min-height:${Math.round(26 + i.clo * 46)}px">
            ${thumb}${escapeHtml(i.name)}<span class="slot">${SLOT_LABEL[i.slot]}</span><small>${i.clo}</small></div>`;
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
    renderMe();

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
    // A try-on preview, if the agent made one.
    for (const call of toolCalls) {
        if (call.name !== "try_on_outfit") continue;
        let result = {};
        try { result = JSON.parse(call.result); } catch (e) { /* not JSON */ }
        if (!result.image_url) continue;
        const fig = document.createElement("figure");
        fig.className = "tryon";
        fig.innerHTML = `<img src="${escapeHtml(result.image_url)}" alt="AI preview of you wearing ${escapeHtml((result.items || []).join(", "))}">
            <figcaption>AI preview · colors and fit are approximate</figcaption>`;
        fig.querySelector("img").addEventListener("load", () => messagesEl.scrollTo({ top: messagesEl.scrollHeight, behavior: "smooth" }));
        div.appendChild(fig);
        showPreview(result.image_url);
    }
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
        if (A) await finish(A.animate(intro, { opacity: 0, translateY: -20, filter: "blur(8px)", duration: 350, ease: "inQuad" }), 600);
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
    const steps = /\b(show me|on me|try (it|this|that)? ?on|wearing|look on)\b/i.test(text) ? LOADING_TRYON : LOADING;
    loading.textContent = `${steps[0]}...`;
    const timer = setInterval(() => { loading.textContent = `${steps[Math.min(++tick, steps.length - 1)]}...`; }, steps === LOADING_TRYON ? 3500 : 1800);
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
        try {
            const data = await uploadFile(file);
            pending.push({ id: data.image_id, url: data.url });
        } catch (err) {
            alert(err.message);
        }
    }
    fileEl.value = "";
    renderAttachments();
});

// ---------- Add clothes: upload, scan, review, save ----------

const SLOT_NAMES = { base_top: "Tops", mid_top: "Sweaters and mid layers", outer: "Coats and jackets", bottom: "Bottoms",
    one_piece: "Dresses", legwear: "Tights and leggings", socks: "Socks", shoes: "Shoes", head: "Hats", hands: "Gloves", neck: "Scarves" };
let drafts = [];

async function loadCatalog() {
    if (!catalog) catalog = await (await fetch("/catalog")).json();
    return catalog;
}

function typeSelect(selected) {
    const groups = Object.entries(SLOT_NAMES).map(([slot, label]) => {
        const opts = catalog.garments.filter((g) => g.slot === slot)
            .map((g) => `<option value="${g.type}"${g.type === selected ? " selected" : ""}>${escapeHtml(g.label)}</option>`).join("");
        return opts ? `<optgroup label="${label}">${opts}</optgroup>` : "";
    }).join("");
    return `<select class="d-type" aria-label="Garment type"><option value="">What is it?</option>${groups}</select>`;
}

function materialSelect(selected) {
    return `<select class="d-mat" aria-label="Main material">${catalog.materials
        .map((m) => `<option value="${m}"${m === selected ? " selected" : ""}>${m[0].toUpperCase() + m.slice(1)}</option>`).join("")}</select>`;
}

const mainFiber = (mix) => Object.entries(mix || {}).sort((a, b) => b[1] - a[1])[0]?.[0];

async function uploadFile(file) {
    const form = new FormData();
    form.append("session_id", sessionId);
    form.append("file", file);
    const res = await fetch("/upload", { method: "POST", body: form });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) throw new Error(data.detail || "Upload failed.");
    return data;
}

function setStatus(d, text, kind = "") {
    const el = d.el.querySelector(".d-status");
    el.className = `d-status ${kind}`;
    el.textContent = text;
}

function updateAddButton() {
    const ready = drafts.filter((d) => d.photoId && !d.busy);
    $("#add-all").disabled = !ready.length || drafts.some((d) => d.busy);
    $("#add-all").textContent = ready.length > 1 ? `Add ${ready.length} to closet` : "Add to closet";
}

async function addDraft(file) {
    await loadCatalog();
    const d = { photoId: null, labelId: null, scan: null, busy: true, el: document.createElement("div") };
    d.el.className = "draft";
    d.el.innerHTML = `<img class="d-thumb" alt="">
        <div class="d-fields">
            <input class="d-name" placeholder="Name, e.g. Green wool sweater" maxlength="40" />
            <div class="d-row">${typeSelect("")}${materialSelect("cotton")}</div>
            <div class="d-row d-meta">
                <label class="d-label">+ Care label photo<input type="file" accept="image/*" hidden /></label>
                <span class="d-status"></span>
            </div>
        </div>
        <button class="d-remove" type="button" aria-label="Remove">×</button>`;
    d.el.querySelector(".d-thumb").src = URL.createObjectURL(file);
    d.el.querySelector(".d-remove").addEventListener("click", () => {
        drafts = drafts.filter((x) => x !== d);
        d.el.remove();
        updateAddButton();
    });
    d.el.querySelector(".d-label input").addEventListener("change", async (e) => {
        const f = e.target.files[0];
        if (!f) return;
        d.busy = true;
        updateAddButton();
        try {
            d.labelId = (await uploadFile(f)).image_id;
            d.el.querySelector(".d-label").firstChild.textContent = "✓ Care label added ";
            await scanDraft(d);
        } catch (err) {
            setStatus(d, err.message, "bad");
        }
        d.busy = false;
        updateAddButton();
    });
    drafts.push(d);
    $("#drafts").appendChild(d.el);
    if (A) A.animate(d.el, { opacity: { from: 0 }, translateY: { from: 14 }, duration: 500, ease: "outExpo" });
    updateAddButton();

    setStatus(d, "Uploading...", "busy");
    try {
        d.photoId = (await uploadFile(file)).image_id;
        await scanDraft(d);
    } catch (err) {
        setStatus(d, err.message, "bad");
    }
    d.busy = false;
    updateAddButton();
}

async function scanDraft(d) {
    setStatus(d, "Scanning the photo...", "busy");
    const res = await fetch("/wardrobe/scan", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, photo_id: d.photoId, label_photo_id: d.labelId }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
        d.el.classList.add("manual");
        setStatus(d, `${data.detail || "Couldn't scan."} Fill in the details.`, "bad");
        return;
    }
    d.scan = data;
    d.el.classList.remove("manual");
    d.el.querySelector(".d-name").value = data.name;
    d.el.querySelector(".d-type").value = data.garment_type;
    d.el.querySelector(".d-mat").value = mainFiber(data.materials) || "cotton";
    const fibers = Object.entries(data.materials).map(([m, p]) => `${p}% ${m}`).join(", ");
    setStatus(d, data.materials_source === "label" ? `Read from label: ${fibers}` : `Guessed ${fibers}. A care label photo makes it exact.`, "ok");
    if (A) A.animate(d.el.querySelectorAll(".d-name, .d-type, .d-mat"), { backgroundColor: { from: "rgba(224,87,47,0.18)" }, duration: 900, ease: "outQuad" });
}

async function saveDrafts() {
    const ready = drafts.filter((d) => d.photoId);
    const missing = ready.filter((d) => !d.el.querySelector(".d-type").value);
    if (missing.length) {
        missing.forEach((d) => setStatus(d, "Pick what kind of item this is.", "bad"));
        return;
    }
    $("#add-all").disabled = true;
    const added = [];
    const saved = new Set();
    for (const d of ready) {
        const type = d.el.querySelector(".d-type").value;
        const mat = d.el.querySelector(".d-mat").value;
        const scan = d.scan || {};
        const item = {
            ...scan,
            name: d.el.querySelector(".d-name").value || undefined,
            garment_type: type,
            materials: mainFiber(scan.materials) === mat ? scan.materials : { [mat]: 100 },
            photo_id: d.photoId,
            label_photo_id: d.labelId,
        };
        const res = await fetch("/wardrobe/item", {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            body: JSON.stringify({ session_id: sessionId, item }),
        });
        if (res.ok) {
            added.push((await res.json()).id);
            saved.add(d);
        } else {
            setStatus(d, ((await res.json().catch(() => ({}))).detail) || "Couldn't save.", "bad");
        }
    }
    saved.forEach((d) => d.el.remove());
    drafts = drafts.filter((d) => !saved.has(d));
    drafts.length ? updateAddButton() : closeAdder();
    await refresh();
    if (A) A.animate(added.map((id) => document.querySelector(`#closet .item[data-id="${CSS.escape(id)}"]`)).filter(Boolean),
        { scale: { from: 0.6 }, opacity: { from: 0 }, duration: 800, delay: A.stagger(80), ease: "outBack(1.8)" });
}

function openAdder() {
    const el = $("#adder");
    el.hidden = false;
    $("#add-open").hidden = true;
    loadCatalog();
    if (A) A.animate(el, { opacity: { from: 0 }, translateY: { from: -10 }, duration: 450, ease: "outExpo" });
}
function closeAdder() {
    if (document.body.classList.contains("in-setup")) {  // Step 1 keeps the drop zone open
        $("#drafts").innerHTML = "";
        drafts = [];
        updateAddButton();
        return;
    }
    $("#adder").hidden = true;
    $("#add-open").hidden = false;
    $("#drafts").innerHTML = "";
    drafts = [];
    updateAddButton();
}

$("#add-open").addEventListener("click", openAdder);
$("#adder-close").addEventListener("click", closeAdder);
$("#add-all").addEventListener("click", saveDrafts);
$("#adder-input").addEventListener("change", (e) => { [...e.target.files].forEach(addDraft); e.target.value = ""; });
const dropzone = $("#dropzone");
["dragenter", "dragover"].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.add("over"); }));
["dragleave", "drop"].forEach((t) => dropzone.addEventListener(t, (e) => { e.preventDefault(); dropzone.classList.remove("over"); }));
dropzone.addEventListener("drop", (e) => [...e.dataTransfer.files].filter((f) => f.type.startsWith("image/")).forEach(addDraft));

// ---------- Your photo and try-on ----------

function renderMe() {
    const box = $("#me-photo");
    box.style.backgroundImage = personPhotoId ? `url("${photoUrl(personPhotoId)}")` : "";
    box.classList.toggle("filled", !!personPhotoId);
    $("#me-clear").hidden = !personPhotoId;
    $("#me-sample").hidden = !!personPhotoId;
    const hasOutfit = !!lastOutfit?.options?.length;
    $("#me-try").hidden = !(personPhotoId && hasOutfit);
    $("#me-note").textContent = !personPhotoId
        ? "Add a full-body photo, facing the camera, to see outfits on you. It is sent to Google's image model to make the preview and kept only for this session."
        : hasOutfit ? "Ready. See the outfit above on you; it takes about 15 seconds."
        : "Saved for this session. Ask for an outfit, then see it on you.";
}

function showPreview(url) {
    const el = $("#tryon-preview");
    el.hidden = false;
    el.innerHTML = `<img src="${escapeHtml(url)}" alt="AI preview of you in the outfit"><span>AI preview</span>`;
    if (A) A.animate(el, { opacity: { from: 0 }, scale: { from: 0.94 }, duration: 800, ease: "outExpo" });
}

$("#me-try").addEventListener("click", () => {
    const n = optionIndex + 1;
    sendMessage(lastOutfit.options.length > 1 ? `Show me wearing option ${n}.` : "Show me wearing this outfit.");
});

async function setMe(imageId) {
    const res = await fetch("/me/photo", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, image_id: imageId }),
    });
    if (res.ok) personPhotoId = (await res.json()).person_photo_id;
    renderMe();
    if (A && personPhotoId) A.animate("#me-photo", { scale: { from: 0.7 }, duration: 700, ease: "outBack(2)" });
}

$("#me-input").addEventListener("change", async (e) => {
    const f = e.target.files[0];
    e.target.value = "";
    if (!f) return;
    try {
        await setMe((await uploadFile(f)).image_id);
    } catch (err) {
        $("#me-note").textContent = err.message;
    }
});
$("#me-clear").addEventListener("click", () => setMe(null));
// For trying it without your own picture: a fictional, AI-generated person.
$("#me-sample").addEventListener("click", async () => {
    try {
        const blob = await (await fetch("/static/sample-person.jpg")).blob();
        await setMe((await uploadFile(new File([blob], "sample-person.jpg", { type: "image/jpeg" }))).image_id);
    } catch (err) {
        $("#me-note").textContent = err.message;
    }
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

// ---------- Step 1: build your digital closet ----------

const ESSENTIALS = { top: ["base_top", "one_piece"], bottom: ["bottom", "one_piece"], coat: ["outer"], shoes: ["shoes"] };

function renderCoverage() {
    document.querySelectorAll("#coverage li").forEach((li) => {
        const count = closetItems.filter((i) => ESSENTIALS[li.dataset.need].includes(i.slot)).length;
        const wasDone = li.classList.contains("done");
        li.classList.toggle("done", count > 0);
        li.querySelector("b")?.remove();
        if (count) li.insertAdjacentHTML("beforeend", `<b>${count}</b>`);
        if (A && count && !wasDone) A.animate(li, { scale: [1, 1.12, 1], duration: 500, ease: "outBack(2)" });
    });
    const missing = [...document.querySelectorAll("#coverage li:not(.done)")].length;
    const own = closetItems.filter((i) => i.user_added).length;
    $("#setup-note").textContent = !own
        ? "Missing a coat or shoes? We'll borrow basics from a demo closet so outfits still work."
        : missing ? `${own} piece${own > 1 ? "s" : ""} added. Anything still missing gets borrowed from a demo closet.`
        : `${own} pieces added. Your closet covers everything, nice.`;
}

function showSetup() {
    document.body.classList.add("in-setup");
    $("#setup").hidden = false;
    $("#intro").hidden = true;
    const adder = $("#adder");
    $("#setup-adder-slot").appendChild(adder);
    adder.hidden = false;
    $("#add-open").hidden = true;
    loadCatalog();
    renderCoverage();
    if (A) enter("#setup > *", { delay: 70, y: 18, duration: 800 });
}

function showChat(note) {
    document.body.classList.remove("in-setup");
    $("#setup").hidden = true;
    const adder = $("#adder");
    $("#closet").before(adder);
    adder.hidden = true;
    $("#add-open").hidden = false;
    const intro = $("#intro");
    if (intro) intro.hidden = false;
    setupHero();
    if (note) {
        const div = document.createElement("div");
        div.className = "chat-note";
        div.textContent = note;
        messagesEl.appendChild(div);
        enter(div, { y: 8 });
    }
}

async function startMode(mode) {
    await fetch("/wardrobe/start", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId, mode }),
    });
    closetShown = false;
    await refresh();
}

async function finishSetup() {
    if (drafts.some((d) => d.photoId)) await saveDrafts();  // don't lose pieces still in the list
    const res = await fetch("/wardrobe/finish", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ session_id: sessionId }),
    });
    const { borrowed } = await res.json();
    await refresh();
    const own = closetItems.filter((i) => i.user_added).length;
    if (A) await finish(A.animate("#setup", { opacity: 0, translateY: -16, duration: 350, ease: "inQuad" }), 600);
    showChat(`Closet ready: ${own} of your own piece${own === 1 ? "" : "s"}${borrowed.length ? ` + borrowed ${borrowed.join(", ").toLowerCase()}` : ""}`);
}

$("#setup-done").addEventListener("click", finishSetup);
$("#setup-demo").addEventListener("click", async () => {
    await startMode("demo");
    if (A) await finish(A.animate("#setup", { opacity: 0, translateY: -16, duration: 350, ease: "inQuad" }), 600);
    showChat("Using the demo closet (27 pieces)");
});

// ---------- Intro: a bedroom window onto today's sky ----------

function portalSeen() {
    try { return sessionStorage.getItem("layerlab-portal") === "1"; } catch (e) { return false; }
}
function markPortalSeen() {
    try { sessionStorage.setItem("layerlab-portal", "1"); } catch (e) { /* fine */ }
}

function enterApp(view) {
    setChromeColor();
    view === "setup" ? showSetup() : showChat();
    if (A) A.animate(".topbar, .chat, .panels .panel", { opacity: { from: 0 }, translateY: { from: 40 }, scale: { from: 0.98 },
        duration: 1000, delay: A.stagger(90), ease: "outExpo" });
}

function runPortal(setupDone) {
    const portal = $("#portal");
    if (portalSeen() || !portal) {
        portal?.remove();
        if (setupDone) return enterApp("chat");
        // Mid-setup reload: keep what they already added; otherwise start from an empty closet.
        const started = closetItems.some((i) => i.user_added) ? Promise.resolve() : startMode("own");
        started.then(() => enterApp("setup"));
        return;
    }
    document.body.classList.add("at-portal");
    const scene = $("#scene");
    const curtains = portal.querySelectorAll(".curtain");

    // Curtains draw back to show today's sky, and the copy settles in.
    if (A) {
        A.animate(curtains, { scaleX: { from: 1, to: 0.36 }, duration: 2000, delay: 500, ease: "inOutQuart" });
        A.animate(".portal-top, .portal-copy > *, .portal-foot", { opacity: { from: 0 }, translateY: { from: 22 },
            duration: 1000, delay: A.stagger(110, { start: 300 }), ease: "outExpo" });
    } else {
        curtains.forEach((c) => c.classList.add("open"));
    }

    const tilt = (e) => {
        const x = e.clientX / window.innerWidth - 0.5, y = e.clientY / window.innerHeight - 0.5;
        scene.style.transform = `perspective(1100px) rotateY(${x * 8}deg) rotateX(${-y * 6}deg)`;
    };
    if (finePointer && !reduceMotion) window.addEventListener("pointermove", tilt);

    let leaving = false;
    const onKey = (e) => { if (e.key === "Escape") go("demo"); };
    async function go(mode) {
        if (leaving) return;
        leaving = true;
        markPortalSeen();
        window.removeEventListener("pointermove", tilt);
        document.removeEventListener("keydown", onKey);
        const ready = startMode(mode);
        if (A) {
            scene.style.transform = "";
            // The text, frame, pane dividers, curtains and sill fade away first, so only a clean
            // opening onto the sky grows, not giant white bars.
            const fading = portal.querySelectorAll(".portal-top, .portal-copy, .portal-foot, .lamp-light, .frame, .muntin, .glare, .sill, .curtain, .rod");
            portal.classList.add("leaving");
            A.utils?.remove?.(fading);  // stop the intro's own animations on these
            A.animate(fading, { opacity: 0, duration: 300, ease: "outQuad",
                onComplete: () => fading.forEach((el) => { el.style.opacity = "0"; }) });
            await finish(A.animate(scene, { scale: 16, duration: 1200, delay: 300, ease: "inOutQuart" }), 2200);
        }
        await ready;
        portal.remove();
        document.body.classList.remove("at-portal");
        enterApp(mode === "own" ? "setup" : "chat");
    }
    $("#enter").addEventListener("click", () => go("own"));
    $("#enter-demo").addEventListener("click", () => go("demo"));
    document.addEventListener("keydown", onKey);
    $("#enter").focus({ preventScroll: true });
}

(async function init() {
    sessionId = load("layerlab-session");
    loadConditions();
    const data = await refresh();
    document.fonts.ready.then(() => {
        const active = document.querySelector('.thermostat button[aria-checked="true"]');
        if (active) { thumbPlaced = false; renderSensitivity(active.dataset.level); }
    });
    runPortal(data.setup_done);
})();
