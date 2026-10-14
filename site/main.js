// Landing page: direct download links from the latest GitHub release, the
// visitor's OS highlighted, and a few small animations.
const REPO = "gabuldev/auto-edit-video";
const ASSETS = {
  dmg: /_aarch64\.dmg$/,
  exe: /_x64-setup\.exe$/,
  msi: /\.msi$/,
  deb: /_amd64\.deb$/,
  rpm: /\.rpm$/,
};
const OS_ASSET = { mac: "dmg", win: "exe", linux: "deb" };
const OS_LABEL = { mac: "Baixar para macOS", win: "Baixar para Windows", linux: "Baixar para Linux" };

function detectOS() {
  const p = (navigator.userAgentData?.platform || navigator.platform || navigator.userAgent).toLowerCase();
  const ua = navigator.userAgent.toLowerCase();
  if (/iphone|ipad|android/.test(ua)) return null; // phones: no installer, show all
  if (p.includes("mac")) return "mac";
  if (p.includes("win")) return "win";
  if (p.includes("linux")) return "linux";
  return null;
}

function mb(bytes) {
  return `${Math.round(bytes / 1024 / 1024)} MB`;
}

async function wireDownloads() {
  const os = detectOS();
  const main = document.getElementById("dl-main");
  if (os) {
    document.getElementById("dl-main-label").textContent = OS_LABEL[os];
    document.querySelector(`.dl[data-os="${os}"]`)?.classList.add("mine");
  }

  let release;
  try {
    const res = await fetch(`https://api.github.com/repos/${REPO}/releases/latest`, { headers: { Accept: "application/vnd.github+json" } });
    if (!res.ok) return; // links keep pointing at the releases page
    release = await res.json();
  } catch {
    return;
  }

  const found = {};
  for (const [key, re] of Object.entries(ASSETS)) {
    const a = release.assets.find((x) => re.test(x.name));
    if (a) found[key] = a;
  }
  document.querySelectorAll("[data-asset]").forEach((el) => {
    const a = found[el.dataset.asset];
    if (!a) return;
    el.href = a.browser_download_url;
    if (el.classList.contains("btn")) {
      const s = document.createElement("span");
      s.className = "size";
      s.textContent = mb(a.size);
      el.append(s);
    }
  });
  if (os && found[OS_ASSET[os]]) {
    main.href = found[OS_ASSET[os]].browser_download_url;
    document.getElementById("dl-meta").textContent = `${release.tag_name} · ${mb(found[OS_ASSET[os]].size)} · também para outros sistemas`;
  }
  const date = new Date(release.published_at).toLocaleDateString("pt-BR");
  document.getElementById("version").textContent = `versão ${release.tag_name} · ${date}`;
}

// Hero timeline: a fake waveform where the "AI" marks bars to keep or cut.
function timeline() {
  const track = document.getElementById("track");
  const N = window.innerWidth < 600 ? 42 : 64;
  const bars = [];
  for (let i = 0; i < N; i++) {
    const b = document.createElement("b");
    const h = 18 + Math.abs(Math.sin(i * 0.55) * 55 + Math.sin(i * 1.7) * 20) + Math.random() * 10;
    b.style.height = `${Math.min(h, 96)}%`;
    track.append(b);
    bars.push(b);
  }
  // Contiguous cut ranges, like silences and false starts.
  const cuts = new Set();
  [[0.08, 0.13], [0.27, 0.31], [0.45, 0.54], [0.69, 0.72], [0.86, 0.92]].forEach(([a, z]) => {
    for (let i = Math.floor(a * N); i < Math.ceil(z * N); i++) cuts.add(i);
  });

  const stages = [...document.querySelectorAll(".stages span")];
  const reduced = matchMedia("(prefers-reduced-motion: reduce)").matches;
  if (reduced) {
    bars.forEach((b, i) => b.classList.add(cuts.has(i) ? "cut" : "keep"));
    stages.forEach((s) => s.classList.add("done"));
    return;
  }

  let i = 0;
  let stage = 0;
  const step = () => {
    if (i < N) {
      bars[i].classList.add(cuts.has(i) ? "cut" : "keep");
      i++;
      const s = Math.min(stages.length - 1, Math.floor((i / N) * stages.length));
      if (s !== stage || i === 1) {
        stages.forEach((el, k) => {
          el.classList.toggle("done", k < s);
          el.classList.toggle("cur", k === s);
        });
        stage = s;
      }
      setTimeout(step, 55);
    } else {
      stages.forEach((el) => { el.classList.remove("cur"); el.classList.add("done"); });
      setTimeout(() => {
        bars.forEach((b) => b.classList.remove("cut", "keep"));
        stages.forEach((el) => el.classList.remove("done", "cur"));
        i = 0;
        step();
      }, 3200);
    }
  };
  step();
}

// Word-by-word caption, like the shorts.
function captions() {
  const lines = [
    ["e", "é", "assim", "que", "a", "gente"],
    ["corta", "o", "silêncio", "sozinho"],
    ["legenda", "palavra", "por", "palavra"],
    ["pronto", "pra", "postar"],
  ];
  const box = document.querySelector(".caption-demo span");
  if (matchMedia("(prefers-reduced-motion: reduce)").matches) return;
  let l = 0, w = 0;
  setInterval(() => {
    const words = lines[l];
    box.innerHTML = words.map((x, k) => (k === w ? `<mark>${x}</mark>` : x)).join(" ");
    w++;
    if (w >= words.length) { w = 0; l = (l + 1) % lines.length; }
  }, 420);
}

function tabs() {
  const img = document.getElementById("tab-img");
  const buttons = document.querySelectorAll(".tabs button");
  buttons.forEach((btn) => btn.addEventListener("click", () => {
    buttons.forEach((b) => b.setAttribute("aria-selected", String(b === btn)));
    img.style.opacity = 0;
    setTimeout(() => {
      img.src = btn.dataset.img;
      img.alt = btn.dataset.alt;
      img.onload = () => (img.style.opacity = 1);
    }, 150);
  }));
}

function reveal() {
  const io = new IntersectionObserver((entries) => {
    entries.forEach((e) => {
      if (e.isIntersecting) { e.target.classList.add("in"); io.unobserve(e.target); }
    });
  }, { threshold: 0.15 });
  document.querySelectorAll(".reveal").forEach((el) => io.observe(el));

  const shot = document.querySelector(".hero-shot");
  new IntersectionObserver(([e]) => shot.classList.toggle("flat", e.intersectionRatio > 0.35), { threshold: [0, 0.35, 1] }).observe(shot);
}

wireDownloads();
timeline();
captions();
tabs();
reveal();
