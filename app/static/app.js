"use strict";

const $ = (id) => document.getElementById(id);
const IG_LINK = /https?:\/\/(?:www\.)?instagram\.com\/\S+/i;

let config = { auth_required: false, ai_available: false };
let post = null; // last fetched post: { url, shortcode, author, caption, image_url, image }

// ---- helpers --------------------------------------------------------------

function getToken() {
  try { return localStorage.getItem("appToken") || ""; } catch { return ""; }
}
function setToken(value) {
  try { localStorage.setItem("appToken", value); } catch { /* private mode */ }
}

async function api(path, body) {
  const res = await fetch(path, {
    method: body ? "POST" : "GET",
    headers: { "Content-Type": "application/json", "X-App-Token": getToken() },
    body: body ? JSON.stringify(body) : undefined,
  });
  const data = await res.json().catch(() => ({}));
  if (res.status === 401) {
    $("auth").hidden = false;
  }
  if (!res.ok) {
    throw new Error(typeof data.detail === "string" ? data.detail : `Errore ${res.status}`);
  }
  return data;
}

function show(section) {
  for (const id of ["step-link", "loading", "error", "preview", "done"]) {
    $(id).hidden = !(id === section || (section === "error" && id === "step-link"));
  }
  window.scrollTo({ top: 0, behavior: "smooth" });
}

function loading(text) {
  $("loading-text").textContent = text;
  show("loading");
}

function fail(message) {
  $("error-text").textContent = message;
  show("error");
}

const lines = (text) => text.split("\n").map((l) => l.trim()).filter(Boolean);
const toInt = (v) => (v === "" || v == null ? null : Math.max(0, parseInt(v, 10)) || null);

function updateCounts() {
  const count = (id) => lines($(id).value).filter((l) => !l.endsWith(":")).length;
  $("c-ingredients").textContent = `(${count("f-ingredients")})`;
  $("c-instructions").textContent = `(${count("f-instructions")})`;
}

// ---- flow -----------------------------------------------------------------

function fillForm(recipe) {
  $("f-name").value = recipe.name || "";
  $("f-description").value = recipe.description || "";
  $("f-yield").value = recipe.recipe_yield || "";
  $("f-prep").value = recipe.prep_time ?? "";
  $("f-cook").value = recipe.cook_time ?? "";
  $("f-ingredients").value = (recipe.ingredients || []).join("\n");
  // Blank line between steps: long steps wrap, this keeps them visually separate.
  $("f-instructions").value = (recipe.instructions || []).join("\n\n");
  $("f-notes").value = (recipe.notes || []).join("\n");
  updateCounts();
}

function showPreview(recipe) {
  fillForm(recipe);
  $("cover").removeAttribute("src");
  if (post.image) $("cover").src = post.image;
  $("source-link").textContent = post.author ? `@${post.author}` : "Post Instagram";
  if (post.url) $("source-link").href = post.url;
  else $("source-link").removeAttribute("href");
  $("raw-caption").textContent = post.caption;
  $("import-ai").hidden = !config.ai_available;
  show("preview");
}

async function fetchPost(text) {
  if (!IG_LINK.test(text)) {
    fail("Non vedo un link Instagram. Incolla il link del post (es. https://www.instagram.com/p/…).");
    return;
  }
  loading("Leggo il post…");
  try {
    const data = await api("/api/fetch", { text });
    post = data;
    showPreview(data.recipe);
  } catch (e) {
    post = { url: (text.match(IG_LINK) || [""])[0], caption: "", author: "" };
    fail(e.message);
  }
}

async function parseManual() {
  const caption = $("manual-caption").value.trim();
  if (!caption) return;
  loading("Analizzo il testo…");
  try {
    const data = await api("/api/parse", { caption, author: post?.author || "" });
    post = { ...(post || {}), caption };
    showPreview(data.recipe);
  } catch (e) {
    fail(e.message);
  }
}

function collectRecipe() {
  return {
    name: $("f-name").value.trim(),
    description: $("f-description").value.trim(),
    recipe_yield: $("f-yield").value.trim(),
    prep_time: toInt($("f-prep").value),
    cook_time: toInt($("f-cook").value),
    ingredients: lines($("f-ingredients").value),
    instructions: lines($("f-instructions").value),
    notes: lines($("f-notes").value),
  };
}

async function importRecipe(useAi) {
  const recipe = collectRecipe();
  loading(useAi ? "L'AI di Mealie sta leggendo la ricetta…" : "Creo la ricetta su Mealie…");
  try {
    const data = await api("/api/import", {
      recipe,
      use_ai: useAi,
      caption: post.caption,
      source_url: post.url || "",
      shortcode: post.shortcode || "",
      author: post.author || "",
      image_url: post.image_url || "",
    });
    $("done-name").textContent = useAi ? "" : recipe.name;
    $("done-link").href = data.url;
    show("done");
  } catch (e) {
    // Back to the form so nothing typed is lost.
    show("preview");
    alert(e.message);
  }
}

function reset() {
  post = null;
  $("link").value = "";
  $("manual-caption").value = "";
  $("manual").open = false;
  show("step-link");
  $("link").focus();
}

// ---- wiring ---------------------------------------------------------------

$("fetch").addEventListener("click", () => fetchPost($("link").value.trim()));
$("link").addEventListener("keydown", (e) => {
  if (e.key === "Enter") fetchPost($("link").value.trim());
});
$("manual-parse").addEventListener("click", parseManual);
$("preview").addEventListener("submit", (e) => {
  e.preventDefault();
  importRecipe(false);
});
$("import-ai").addEventListener("click", () => importRecipe(true));
$("cancel").addEventListener("click", reset);
$("again").addEventListener("click", reset);
$("f-ingredients").addEventListener("input", updateCounts);
$("f-instructions").addEventListener("input", updateCounts);
$("reparse").addEventListener("click", async () => {
  const data = await api("/api/parse", { caption: post.caption, author: post.author || "" });
  fillForm(data.recipe);
});
$("auth-save").addEventListener("click", () => {
  setToken($("auth-token").value.trim());
  $("auth").hidden = true;
  const link = $("link").value.trim();
  if (link) fetchPost(link);
});

if (navigator.clipboard && navigator.clipboard.readText) {
  $("paste").hidden = false;
  $("paste").addEventListener("click", async () => {
    try {
      const text = await navigator.clipboard.readText();
      $("link").value = (text.match(IG_LINK) || [text])[0].trim();
      fetchPost($("link").value);
    } catch { /* permission denied: user can paste manually */ }
  });
}

async function init() {
  try {
    config = await api("/api/config");
  } catch { /* keep defaults */ }
  if (config.auth_required && !getToken()) $("auth").hidden = false;

  // Opened from the Android share sheet (PWA share_target) or with ?text=… / ?url=…
  const params = new URLSearchParams(location.search);
  const shared = [params.get("url"), params.get("text"), params.get("title")].filter(Boolean).join(" ");
  if (shared) {
    history.replaceState(null, "", "/");
    const link = (shared.match(IG_LINK) || [shared])[0];
    $("link").value = link;
    if (!config.auth_required || getToken()) fetchPost(shared);
  }
}

if ("serviceWorker" in navigator) {
  navigator.serviceWorker.register("/sw.js").catch(() => {});
}
init();
