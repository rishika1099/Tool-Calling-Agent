// The sky behind the page.
//
// Clouds: a plain-JS port of Originkit's "Cloud Sky" WebGL shader (originkit.dev, free
// component library), with its preset (soft clouds, full cirrus, strong pointer wind and
// parallax). Instead of fixed props, the colors, cloud cover and speed follow the weather.
// Precipitation: a 2D canvas on top draws rain streaks or snowflakes.
//
// Other scripts steer it with Sky.set({ mode: "calm" | "rain" | "snow", warmth: 0..1, wind: 0..1 }).
(function () {
    const reduce = window.matchMedia("(prefers-reduced-motion: reduce)").matches;
    let night = document.documentElement.dataset.theme === "dark";  // real day/night, set by app.js
    const RENDER_SCALE = 0.6; // clouds are soft, so render small and let CSS scale up

    // ---------- Weather -> sky look ----------

    const LOOKS = {
        warm: { zenith: "#0a6cf0", horizon: "#b4d2f0", cloud: "#ffffff", glow: "#ffffff" },
        cold: { zenith: "#4d7fb8", horizon: "#dce7f1", cloud: "#f7f9fb", glow: "#eef4ff" },
        rain: { zenith: "#5b6b7d", horizon: "#aab5c0", cloud: "#dde2e7", glow: "#c9d3dc" },
        snow: { zenith: "#8397ad", horizon: "#e2e8ee", cloud: "#f8f9fb", glow: "#ffffff" },
        nightWarm: { zenith: "#08142b", horizon: "#223a61", cloud: "#4a5f82", glow: "#b9c8ff" },
        nightCold: { zenith: "#070d1a", horizon: "#1b2a42", cloud: "#3c4d68", glow: "#c9d6f2" },
        nightRain: { zenith: "#0b1017", horizon: "#1f2833", cloud: "#39434f", glow: "#6b7684" },
        nightSnow: { zenith: "#101826", horizon: "#2b3a4f", cloud: "#56657a", glow: "#dfe7f5" },
    };
    const COVERAGE = { calm: 0.55, rain: 0.97, snow: 0.9 };

    const goal = { mode: "calm", warmth: 0.6, wind: 0.25 };
    const now = { colors: null, coverage: COVERAGE.calm, wind: 0.25 };

    const rgb = (h) => [1, 3, 5].map((i) => parseInt(h.slice(i, i + 2), 16) / 255);
    const lerp = (a, b, k) => a + (b - a) * k;
    const mixRgb = (a, b, k) => a.map((v, i) => lerp(v, b[i], k));

    function targetColors() {
        const L = (name) => LOOKS[night ? `night${name[0].toUpperCase()}${name.slice(1)}` : name];
        let look;
        if (goal.mode === "rain") look = L("rain");
        else if (goal.mode === "snow") look = L("snow");
        else {
            const warm = L("warm"), cold = L("cold");
            look = Object.fromEntries(Object.keys(warm).map((k) => [k, mixRgb(rgb(cold[k]), rgb(warm[k]), goal.warmth)]));
            return look;
        }
        return Object.fromEntries(Object.entries(look).map(([k, v]) => [k, rgb(v)]));
    }

    // ---------- WebGL clouds (Originkit Cloud Sky shader, unchanged) ----------

    const PUFF_UP = 0.34, PUFF_DOWN = 0.19, ERODE = 0.7, SHADOW_STEP = 0.085;
    const NEAR_CELL = 1.05, FAR_CELL = 2.15, FAR_MIX = 0.55;
    const NEAR_DRIFT = 0.055, FAR_DRIFT = 0.026, CIRRUS_DRIFT = 0.014;
    const PUFF_WMAX = 2.15, SHADE_BLEND = 12.0;

    const VERT = "attribute vec2 a_pos; void main(){ gl_Position = vec4(a_pos, 0.0, 1.0); }";
    const FRAG = `
#ifdef GL_FRAGMENT_PRECISION_HIGH
precision highp float;
#else
precision mediump float;
#endif
uniform vec2 uRes;
uniform float uNearX, uFarX, uCirrusX;
uniform float uCoverage, uSize, uSoftness, uShadow, uCirrus;
uniform vec3 uZenith, uHorizon, uCloud;
uniform vec4 uGlow;
uniform vec2 uSun;
uniform vec2 uParallax;
vec2 hash22(vec2 p){ vec3 q = fract(vec3(p.xyx) * vec3(0.1031, 0.1030, 0.0973)); q += dot(q, q.yzx + 33.33); return fract((q.xx + q.yz) * q.zy); }
float hash12(vec2 p){ vec3 q = fract(vec3(p.xyx) * 0.1031); q += dot(q, q.yzx + 33.33); return fract((q.x + q.y) * q.z); }
float vnoise(vec2 x){ vec2 i = floor(x), f = fract(x); f = f * f * (3.0 - 2.0 * f);
  return mix(mix(hash12(i), hash12(i + vec2(1.0, 0.0)), f.x), mix(hash12(i + vec2(0.0, 1.0)), hash12(i + vec2(1.0, 1.0)), f.x), f.y); }
float fbm(vec2 p){ float a = 0.5, s = 0.0; for (int i = 0; i < 4; i++){ s += a * vnoise(p); p *= 2.03; a *= 0.5; } return s; }
vec2 blobs(vec2 uv, float seed){
  vec2 id = floor(uv), f = fract(uv);
  float best = -1e4; float wsum = 0.0, ysum = 0.0;
  float wMax = min(${PUFF_WMAX.toFixed(3)}, 0.72 * uSize);
  float reach = min(2.0, ceil(wMax + 0.85) - 1.0);
  for (int j = -2; j <= 2; j++){ for (int i = -2; i <= 2; i++){
    vec2 o = vec2(float(i), float(j));
    if (max(abs(o.x), abs(o.y)) > reach) continue;
    vec2 h = hash22(id + o + seed);
    if (fract(h.x * 37.1) > uCoverage) continue;
    vec2 c = o + 0.15 + h * 0.7;
    float w = min(${PUFF_WMAX.toFixed(3)}, (0.30 + 0.42 * fract(h.y * 19.7)) * uSize);
    vec2 d = f - c;
    float ry = (d.y > 0.0 ? ${PUFF_UP.toFixed(3)} : ${PUFF_DOWN.toFixed(3)}) * uSize * (0.8 + 0.5 * fract(h.y * 7.3));
    float e = length(vec2(d.x / max(w, 1e-3), d.y / max(ry, 1e-3)));
    float val = 1.0 - e; float yN = d.y / max(ry, 1e-3);
    if (val > best){ float k = exp(${SHADE_BLEND.toFixed(1)} * (best - val)); wsum = wsum * k + 1.0; ysum = ysum * k + yN; best = val; }
    else { float g = exp(${SHADE_BLEND.toFixed(1)} * (val - best)); wsum += g; ysum += g * yN; }
  } }
  return vec2(best, ysum / max(wsum, 1e-4));
}
vec2 cloudField(vec2 uv, float seed, float detailScale){
  vec2 b = blobs(uv, seed);
  float n = fbm(uv * detailScale + seed * 3.1) * 0.72 + fbm(uv * detailScale * 3.3 + seed * 7.7) * 0.28;
  return vec2(b.x - (1.0 - n) * ${ERODE.toFixed(3)}, b.y);
}
vec3 shadeCloud(float dyNorm, vec3 sky){
  float t = smoothstep(-0.95, 0.25, dyNorm);
  vec3 base = mix(uCloud * 0.52, sky, 0.34);
  return mix(mix(uCloud, base, uShadow), uCloud, t);
}
void main(){
  vec2 frag = gl_FragCoord.xy / max(uRes.y, 1.0);
  float aspect = uRes.x / max(uRes.y, 1.0);
  vec2 p = vec2(frag.x, frag.y);
  vec3 sky = mix(uHorizon, uZenith, smoothstep(-0.15, 1.05, p.y));
  vec2 sunP = vec2(uSun.x * aspect, uSun.y);
  float sd = length(p - sunP);
  sky += uGlow.rgb * uGlow.a * exp(-sd * 3.4) * 0.30;
  vec3 col = sky;
  if (uCirrus > 0.0) {
    vec2 cuv = vec2(p.x * 1.4 + uCirrusX, p.y * 5.5);
    float veil = fbm(cuv) * fbm(cuv * 2.3 + 9.0);
    veil = smoothstep(0.24, 0.55, veil) * smoothstep(0.15, 0.7, p.y);
    col = mix(col, uCloud, veil * uCirrus * 0.5);
  }
  vec2 fuv = vec2(p.x + uFarX, p.y) * ${FAR_CELL.toFixed(3)} + uParallax * 0.4;
  vec2 fd = cloudField(fuv, 17.0, 11.0);
  float fa = clamp(fd.x * uSoftness, 0.0, 1.0);
  if (fa > 0.0) { vec3 lit = shadeCloud(fd.y, sky); col = mix(col, mix(lit, sky, ${FAR_MIX.toFixed(3)}), fa); }
  vec2 nuv = vec2(p.x + uNearX, p.y) * ${NEAR_CELL.toFixed(3)} + uParallax;
  vec2 nd = cloudField(nuv, 3.0, 8.5);
  float na = clamp(nd.x * uSoftness, 0.0, 1.0);
  if (na > 0.0) {
    vec3 lit = shadeCloud(nd.y, sky);
    float above = clamp(cloudField(nuv + vec2(0.0, ${SHADOW_STEP.toFixed(3)}), 3.0, 8.5).x * uSoftness, 0.0, 1.0);
    lit *= 1.0 - 0.18 * uShadow * above;
    lit += uGlow.rgb * uGlow.a * 0.22 * exp(-length(p - sunP) * 1.6);
    col = mix(col, lit, na);
  }
  gl_FragColor = vec4(col, 1.0);
}`;

    // Originkit preset: softness 200, shadow 70, cirrus 100, sun top-right, pointer wind 300,
    // damping 50, parallax 300, size 130.
    const PRESET = { size: 1.3, softness: 4.5 / 2.0, shadow: 0.7, cirrus: 1.0, sunX: 1.0, sunY: 1.0,
                     parallax: 3.0, pointerWind: 3.0, damping: 50 };

    const canvas = document.getElementById("sky");
    const gl = canvas.getContext("webgl", { alpha: false, antialias: false, depth: false });
    let program = null, uniforms = {};

    function compile(type, src) {
        const sh = gl.createShader(type);
        gl.shaderSource(sh, src);
        gl.compileShader(sh);
        if (!gl.getShaderParameter(sh, gl.COMPILE_STATUS)) {
            console.error("Sky shader:", gl.getShaderInfoLog(sh));
            return null;
        }
        return sh;
    }

    function setupGl() {
        if (!gl) return false;
        const vs = compile(gl.VERTEX_SHADER, VERT), fs = compile(gl.FRAGMENT_SHADER, FRAG);
        if (!vs || !fs) return false;
        program = gl.createProgram();
        gl.attachShader(program, vs);
        gl.attachShader(program, fs);
        gl.linkProgram(program);
        if (!gl.getProgramParameter(program, gl.LINK_STATUS)) return false;
        gl.useProgram(program);
        gl.bindBuffer(gl.ARRAY_BUFFER, gl.createBuffer());
        gl.bufferData(gl.ARRAY_BUFFER, new Float32Array([-1, -1, 3, -1, -1, 3]), gl.STATIC_DRAW);
        const aPos = gl.getAttribLocation(program, "a_pos");
        gl.enableVertexAttribArray(aPos);
        gl.vertexAttribPointer(aPos, 2, gl.FLOAT, false, 0, 0);
        for (const name of ["uRes", "uNearX", "uFarX", "uCirrusX", "uCoverage", "uSize", "uSoftness", "uShadow",
                            "uCirrus", "uZenith", "uHorizon", "uCloud", "uGlow", "uSun", "uParallax"]) {
            uniforms[name] = gl.getUniformLocation(program, name);
        }
        return true;
    }

    const hasGl = setupGl();
    if (!hasGl) document.documentElement.classList.add("no-webgl");

    // ---------- Precipitation overlay ----------

    const precip = document.getElementById("precip");
    const pctx = precip.getContext("2d");
    let particles = [];
    let w = 0, h = 0;

    function spawn(anywhere) {
        const z = 0.3 + Math.random() * 0.7;
        return { x: Math.random() * w, y: anywhere ? Math.random() * h : -12, z, phase: Math.random() * Math.PI * 2 };
    }
    function seedParticles() {
        const area = Math.min(1.4, (w * h) / (1440 * 900));
        const n = goal.mode === "rain" ? 220 : goal.mode === "snow" ? 160 : 0;
        particles = Array.from({ length: Math.round(n * area) }, () => spawn(true));
    }
    // Stars for clear nights: fixed positions, each twinkling at its own pace.
    const stars = Array.from({ length: 150 }, () => ({ x: Math.random(), y: Math.random() * 0.75, r: 0.4 + Math.random() * 1.1, phase: Math.random() * 6.28 }));
    function drawStars(t) {
        const clear = Math.max(0, 1 - now.coverage * 1.05);  // fewer stars under heavy cloud
        if (!night || clear <= 0) return;
        for (const s of stars) {
            const twinkle = 0.55 + 0.45 * Math.sin(t * 0.0015 + s.phase);
            pctx.fillStyle = `rgba(235,240,255,${(0.9 * twinkle * clear).toFixed(3)})`;
            pctx.beginPath();
            pctx.arc(s.x * w, s.y * h, s.r, 0, Math.PI * 2);
            pctx.fill();
        }
    }

    function drawPrecip(dt, t) {
        pctx.clearRect(0, 0, w, h);
        drawStars(t);
        const lean = now.wind * 7;
        const color = night ? "220,230,245" : "255,255,255";
        for (const p of particles) {
            if (goal.mode === "rain") {
                p.y += (11 + 11 * p.z) * dt;
                p.x += lean * dt;
                pctx.strokeStyle = `rgba(${color},${0.18 + 0.3 * p.z})`;
                pctx.lineWidth = 0.6 + 0.9 * p.z;
                pctx.beginPath();
                pctx.moveTo(p.x, p.y);
                pctx.lineTo(p.x - lean * 1.5, p.y - (9 + 13 * p.z));
                pctx.stroke();
            } else {
                p.y += (0.5 + 1.4 * p.z) * dt;
                p.x += (lean * 0.35 + Math.sin(t * 0.0012 + p.phase) * 0.5) * dt;
                pctx.fillStyle = `rgba(${color},${0.35 + 0.55 * p.z})`;
                pctx.beginPath();
                pctx.arc(p.x, p.y, 0.8 + 2.2 * p.z, 0, Math.PI * 2);
                pctx.fill();
            }
            if (p.y > h + 20 || p.x > w + 40 || p.x < -40) {
                Object.assign(p, spawn(false));
                if (p.x > w) p.x -= w;
            }
        }
    }

    // ---------- Loop ----------

    const pointer = { x: 0, y: 0, inside: false };
    let leanX = 0, leanY = 0, nearX = 0, farX = 0, cirrusX = 0;
    let raf = null, last = 0;

    function size() {
        w = window.innerWidth;
        h = window.innerHeight;
        canvas.width = Math.max(1, Math.round(w * RENDER_SCALE));
        canvas.height = Math.max(1, Math.round(h * RENDER_SCALE));
        const dpr = Math.min(window.devicePixelRatio || 1, 1.5);
        precip.width = w * dpr;
        precip.height = h * dpr;
        pctx.setTransform(dpr, 0, 0, dpr, 0, 0);
        seedParticles();
    }

    function render(t, dt) {
        const k = Math.min(1, 0.025 * dt * 60);
        const goalColors = targetColors();
        now.colors = now.colors
            ? Object.fromEntries(Object.keys(goalColors).map((c) => [c, mixRgb(now.colors[c], goalColors[c], k)]))
            : goalColors;
        now.coverage = lerp(now.coverage, COVERAGE[goal.mode], k);
        now.wind = lerp(now.wind, goal.wind, k);

        if (hasGl) {
            const damp = 1 - Math.exp(-PRESET.damping * 0.12 * dt);
            leanX += ((pointer.inside ? pointer.x : 0) - leanX) * damp;
            leanY += ((pointer.inside ? pointer.y : 0) - leanY) * damp;
            const speed = (0.5 + 1.6 * now.wind) * (1 + leanX * PRESET.pointerWind * 0.3);
            nearX = (nearX - NEAR_DRIFT * speed * dt) % 1000;
            farX = (farX - FAR_DRIFT * speed * dt) % 1000;
            cirrusX = (cirrusX - CIRRUS_DRIFT * speed * dt) % 1000;

            gl.viewport(0, 0, canvas.width, canvas.height);
            gl.uniform2f(uniforms.uRes, canvas.width, canvas.height);
            gl.uniform1f(uniforms.uNearX, nearX);
            gl.uniform1f(uniforms.uFarX, farX);
            gl.uniform1f(uniforms.uCirrusX, cirrusX);
            gl.uniform1f(uniforms.uCoverage, now.coverage);
            gl.uniform1f(uniforms.uSize, PRESET.size);
            gl.uniform1f(uniforms.uSoftness, PRESET.softness);
            gl.uniform1f(uniforms.uShadow, PRESET.shadow);
            gl.uniform1f(uniforms.uCirrus, PRESET.cirrus);
            gl.uniform2f(uniforms.uSun, PRESET.sunX, PRESET.sunY);
            gl.uniform2f(uniforms.uParallax, -leanX * PRESET.parallax * 0.07, -leanY * PRESET.parallax * 0.05);
            gl.uniform3f(uniforms.uZenith, ...now.colors.zenith);
            gl.uniform3f(uniforms.uHorizon, ...now.colors.horizon);
            gl.uniform3f(uniforms.uCloud, ...now.colors.cloud);
            gl.uniform4f(uniforms.uGlow, ...now.colors.glow, 0.9);
            gl.drawArrays(gl.TRIANGLES, 0, 3);
        } else {
            const c = (v) => `rgb(${v.map((x) => Math.round(x * 255)).join(",")})`;
            document.body.style.background = `linear-gradient(180deg, ${c(now.colors.zenith)}, ${c(now.colors.horizon)})`;
        }
        drawPrecip(dt * 60, t);
    }

    function frame(t) {
        const dt = Math.min(0.05, (t - (last || t)) / 1000);
        last = t;
        render(t, dt);
        raf = requestAnimationFrame(frame);
    }
    function start() {
        if (reduce || raf) return;
        last = 0;
        raf = requestAnimationFrame(frame);
    }
    function stop() {
        if (raf) cancelAnimationFrame(raf);
        raf = null;
    }
    const still = () => { now.colors = null; render(0, 1); };

    window.addEventListener("pointermove", (e) => {
        pointer.x = (e.clientX / window.innerWidth) * 2 - 1;
        pointer.y = 1 - (e.clientY / window.innerHeight) * 2;
        pointer.inside = true;
    });
    document.addEventListener("pointerleave", () => { pointer.inside = false; });
    window.addEventListener("resize", () => { size(); if (reduce) still(); });
    document.addEventListener("visibilitychange", () => (document.hidden ? stop() : start()));

    window.Sky = {
        set({ mode, warmth, wind, night: isNight } = {}) {
            if (isNight != null) night = !!isNight;
            if (warmth != null) goal.warmth = Math.max(0, Math.min(1, warmth));
            if (wind != null) goal.wind = Math.max(0, Math.min(1, wind));
            if (mode && mode !== goal.mode) {
                goal.mode = mode;
                seedParticles();
            }
            if (reduce) still();
        },
    };

    size();
    reduce ? still() : start();
})();
