// The traveller's bag, shared by every public page.
//
// Saved in this browser (localStorage), so it survives moving between the
// home page and gadget pages, reloads, and other tabs. Nothing is sent to
// the server. If storage is unavailable (private mode, blocked), the bag
// still works for the current page.
//
// - window.TrekBag: has / add / remove / toggle / clear / items / onChange / open
// - a "Bag" button in the site header, on every page, that opens the panel
// - any <button data-bag-add='{"name": ...}'> becomes an add/remove toggle
(() => {
  "use strict";

  const KEY = "trekxp.bag.v1";
  const PRIORITIES = [
    { key: "essential", name: "Essential", colour: "oklch(0.42 0.1 155)" },
    { key: "recommended", name: "Recommended", colour: "oklch(0.52 0.12 60)" },
    { key: "optional", name: "Optional", colour: "oklch(0.48 0.1 240)" },
    { key: null, name: "Other gadgets", colour: "oklch(0.55 0.03 155)" },
  ];

  const keyOf = (name) => String(name || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));

  let items = load();
  const listeners = new Set();

  function load() {
    try {
      const parsed = JSON.parse(localStorage.getItem(KEY) || "[]");
      return Array.isArray(parsed) ? parsed.filter((i) => i && i.name) : [];
    } catch {
      return [];
    }
  }

  function save() {
    try { localStorage.setItem(KEY, JSON.stringify(items)); } catch { /* memory only */ }
  }

  function changed() {
    save();
    for (const fn of listeners) fn(items);
  }

  // Only the fields the panel shows, so a page cannot store arbitrary data.
  function clean(item) {
    const text = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "") || null;
    const url = (v) => (typeof v === "string" && /^\/[^/]/.test(v) ? v.slice(0, 300) : null);
    const priority = ["essential", "recommended", "optional"].includes(item.priority) ? item.priority : null;
    return {
      name: text(item.name, 120),
      why: text(item.why, 300),
      category: text(item.category, 60),
      priority,
      page_url: url(item.page_url),
      image_url: url(item.image_url),
      destination: text(item.destination, 120),
    };
  }

  const TrekBag = {
    items: () => items.slice(),
    count: () => items.length,
    has: (name) => items.some((i) => keyOf(i.name) === keyOf(name)),
    add(item) {
      const next = clean(item);
      if (!next.name) return;
      const at = items.findIndex((i) => keyOf(i.name) === keyOf(next.name));
      if (at >= 0) {
        // Keep the richer details: a trip's reason and priority beat none.
        const old = items[at];
        items[at] = Object.fromEntries(Object.keys(next).map((k) => [k, next[k] ?? old[k]]));
      } else {
        items.push(next);
      }
      changed();
    },
    remove(name) {
      items = items.filter((i) => keyOf(i.name) !== keyOf(name));
      changed();
    },
    toggle(item) {
      TrekBag.has(item.name) ? TrekBag.remove(item.name) : TrekBag.add(item);
    },
    clear() {
      items = [];
      changed();
    },
    onChange(fn) {
      listeners.add(fn);
      return () => listeners.delete(fn);
    },
    open: () => openPanel(),
  };
  window.TrekBag = TrekBag;

  // Another tab changed the bag.
  window.addEventListener("storage", (e) => {
    if (e.key !== KEY) return;
    items = load();
    for (const fn of listeners) fn(items);
  });

  // ---------- the panel ----------

  let dialog;

  function buildDialog() {
    dialog = document.createElement("dialog");
    dialog.className = "bag-dialog";
    dialog.setAttribute("aria-labelledby", "bagTitle");
    dialog.innerHTML = `
      <header>
        <div>
          <h2 id="bagTitle">Your bag</h2>
          <p class="bag-summary"></p>
        </div>
        <button type="button" class="bag-close" aria-label="Close">✕</button>
      </header>
      <div class="bag-body"></div>
      <footer>
        <button type="button" class="bag-secondary bag-clear">Empty bag</button>
        <span class="bag-spacer"></span>
        <button type="button" class="bag-secondary bag-copy">Copy list</button>
        <button type="button" class="bag-primary bag-done">Done</button>
      </footer>`;
    document.body.append(dialog);

    dialog.querySelector(".bag-close").addEventListener("click", () => dialog.close());
    dialog.querySelector(".bag-done").addEventListener("click", () => dialog.close());
    // Clicking the dimmed backdrop closes it too.
    dialog.addEventListener("click", (e) => { if (e.target === dialog) dialog.close(); });
    dialog.querySelector(".bag-clear").addEventListener("click", () => {
      if (confirm("Take everything out of your bag?")) TrekBag.clear();
    });
    dialog.querySelector(".bag-copy").addEventListener("click", copyList);
  }

  function renderPanel() {
    if (!dialog) return;
    const n = items.length;
    dialog.querySelector(".bag-summary").textContent = n
      ? `${n} item${n === 1 ? "" : "s"} packed`
      : "Nothing packed yet";
    dialog.querySelector(".bag-copy").disabled = !n;
    dialog.querySelector(".bag-clear").disabled = !n;

    const body = dialog.querySelector(".bag-body");
    if (!n) {
      body.innerHTML = `<p class="bag-empty">Your bag is empty. Tap “Add to bag” on a packing list or on any gadget page.</p>`;
      return;
    }

    body.replaceChildren(...PRIORITIES.flatMap((p) => {
      const group = items.filter((i) => (i.priority || null) === p.key);
      if (!group.length) return [];

      const section = document.createElement("section");
      section.className = "bag-group";
      section.innerHTML = `<h3><span class="bag-dot" style="background:${p.colour}"></span>${esc(p.name)} <span class="bag-n">${group.length}</span></h3>`;

      for (const item of group) {
        const row = document.createElement("div");
        row.className = "bag-item";
        const why = item.why || (item.destination ? `For ${item.destination}` : item.category) || "";
        row.innerHTML = `
          <span class="bag-thumb">${item.image_url ? `<img src="${esc(item.image_url)}" alt="" loading="lazy" />` : "🎒"}</span>
          <div>
            ${item.page_url ? `<a class="bag-name" href="${esc(item.page_url)}">${esc(item.name)}</a>` : `<span class="bag-name">${esc(item.name)}</span>`}
            ${why ? `<div class="bag-why">${esc(why)}</div>` : ""}
          </div>
          <button type="button" class="bag-remove" aria-label="Remove ${esc(item.name)} from your bag">Remove</button>`;
        row.querySelector(".bag-remove").addEventListener("click", () => TrekBag.remove(item.name));
        section.append(row);
      }
      return [section];
    }));
  }

  async function copyList() {
    const lines = PRIORITIES.flatMap((p) => {
      const group = items.filter((i) => (i.priority || null) === p.key);
      return group.length ? [`${p.name}:`, ...group.map((i) => `  - ${i.name}`), ""] : [];
    });
    const button = dialog.querySelector(".bag-copy");
    try {
      await navigator.clipboard.writeText(["My Trek XP bag", "", ...lines].join("\n").trim());
      button.textContent = "Copied ✓";
    } catch {
      button.textContent = "Couldn't copy";
    }
    setTimeout(() => { button.textContent = "Copy list"; }, 2000);
  }

  function openPanel() {
    if (!dialog) buildDialog();
    renderPanel();
    dialog.showModal();
  }

  // ---------- the header button and add buttons ----------

  function renderHeaderButton() {
    const button = document.querySelector(".site-header .bag-open");
    if (!button) return;
    const n = items.length;
    button.querySelector(".bag-n").textContent = n;
    button.querySelector(".bag-n").hidden = !n;
    button.setAttribute("aria-label", n ? `Your bag, ${n} item${n === 1 ? "" : "s"}` : "Your bag, empty");
  }

  function addHeaderButton() {
    const nav = document.querySelector(".site-header nav");
    if (!nav || nav.querySelector(".bag-open")) return;
    const button = document.createElement("button");
    button.type = "button";
    button.className = "hbtn bag-open";
    button.setAttribute("aria-haspopup", "dialog");
    button.innerHTML = `<span aria-hidden="true">🎒</span><span class="bag-label">Bag</span><span class="bag-n" hidden>0</span>`;
    button.addEventListener("click", openPanel);
    nav.prepend(button);
    renderHeaderButton();
  }

  function wireAddButtons() {
    for (const button of document.querySelectorAll("[data-bag-add]")) {
      let item;
      try { item = JSON.parse(button.dataset.bagAdd); } catch { continue; }
      const paint = () => {
        const inBag = TrekBag.has(item.name);
        button.classList.toggle("on", inBag);
        button.setAttribute("aria-pressed", String(inBag));
        button.textContent = inBag ? "✓ In your bag" : "Add to bag";
      };
      button.addEventListener("click", () => TrekBag.toggle(item));
      TrekBag.onChange(paint);
      paint();
    }
  }

  TrekBag.onChange(() => {
    renderHeaderButton();
    if (dialog?.open) renderPanel();
  });

  const start = () => { addHeaderButton(); wireAddButtons(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
