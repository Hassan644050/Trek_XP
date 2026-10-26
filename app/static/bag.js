// The traveller's bag, shared by every public page.
//
// Saved in this browser (localStorage), so it survives moving between the
// home page and gadget pages, reloads, and other tabs. Nothing is sent to
// the server. If storage is unavailable (private mode, blocked), the bag
// still works for the current page.
//
// - window.TrekBag: has / add / remove / toggle / clear / items / onChange /
//   open / chooseVariant / variantOf
// - a "Bag" button in the site header, on every page, opens the bag as a
//   sidebar that slides in from the right
// - clicking an item in the bag opens its gadget page at its buying options
// - <button data-bag-add='{"name": ...}'> becomes an add/remove toggle
// - <button data-bag-variant='{"gadget": {...}, "variant": {...}}'> chooses
//   that buying option for the bag (adding the gadget if needed)
(() => {
  "use strict";

  const KEY = "trekxp.bag.v1";
  const PRIORITIES = [
    { key: "essential", name: "Essential", colour: "oklch(0.42 0.1 155)" },
    { key: "recommended", name: "Recommended", colour: "oklch(0.52 0.12 60)" },
    { key: "optional", name: "Optional", colour: "oklch(0.48 0.1 240)" },
    { key: null, name: "Other gadgets", colour: "oklch(0.55 0.03 155)" },
  ];
  const SYMBOLS = { BDT: "৳", USD: "$", EUR: "€", GBP: "£", INR: "₹" };

  const keyOf = (name) => String(name || "").toLowerCase().split(/\s+/).filter(Boolean).join(" ");
  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const money = (price, currency) =>
    `${SYMBOLS[currency] ?? `${currency} `}${Number(price).toLocaleString()}`;

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
  const text = (v, n) => (typeof v === "string" ? v.trim().slice(0, n) : "") || null;
  const path = (v) => (typeof v === "string" && /^\/[^/]/.test(v) ? v.slice(0, 300) : null);

  function cleanVariant(v) {
    if (!v || typeof v !== "object") return null;
    const price = Number(v.price);
    const brand = text(v.brand, 80);
    if (!brand || !Number.isFinite(price) || price < 0) return null;
    return {
      brand,
      model_name: text(v.model_name, 80),
      color: text(v.color, 40),
      quality: ["budget", "standard", "premium"].includes(v.quality) ? v.quality : null,
      price: Math.round(price),
      currency: /^[A-Z]{3}$/.test(v.currency || "") ? v.currency : "BDT",
      vendor: text(v.vendor, 80),
    };
  }

  function clean(item) {
    return {
      name: text(item.name, 120),
      why: text(item.why, 300),
      category: text(item.category, 60),
      priority: ["essential", "recommended", "optional"].includes(item.priority) ? item.priority : null,
      page_url: path(item.page_url),
      image_url: path(item.image_url),
      destination: text(item.destination, 120),
      variant: cleanVariant(item.variant),
    };
  }

  const sameVariant = (a, b) => !!a && !!b &&
    ["brand", "model_name", "color", "vendor", "price"].every((k) => (a[k] ?? null) === (b[k] ?? null));

  const find = (name) => items.findIndex((i) => keyOf(i.name) === keyOf(name));

  const TrekBag = {
    items: () => items.slice(),
    count: () => items.length,
    has: (name) => find(name) >= 0,
    variantOf: (name) => items[find(name)]?.variant || null,
    add(item) {
      const next = clean(item);
      if (!next.name) return;
      const at = find(next.name);
      if (at >= 0) {
        // Keep the richer details: a trip's reason and priority beat none,
        // and a chosen buying option is kept unless a new one is given.
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
    // Choose a buying option for a gadget, adding the gadget if it is not in
    // the bag yet. Choosing the option already chosen un-chooses it.
    chooseVariant(gadget, variant) {
      const chosen = cleanVariant(variant);
      const at = find(gadget.name);
      if (at >= 0 && sameVariant(items[at].variant, chosen)) {
        items[at] = { ...items[at], variant: null };
        changed();
        return;
      }
      TrekBag.add({ ...gadget, variant: chosen });
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

  // ---------- the sidebar ----------

  let dialog;
  const reduceMotion = () => window.matchMedia("(prefers-reduced-motion: reduce)").matches;

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
        <p class="bag-total" hidden></p>
        <div class="bag-actions">
          <button type="button" class="bag-secondary bag-clear">Empty bag</button>
          <span class="bag-spacer"></span>
          <button type="button" class="bag-secondary bag-copy">Copy list</button>
          <button type="button" class="bag-primary bag-done">Done</button>
        </div>
      </footer>`;
    document.body.append(dialog);

    dialog.querySelector(".bag-close").addEventListener("click", closePanel);
    dialog.querySelector(".bag-done").addEventListener("click", closePanel);
    // Clicking the dimmed backdrop closes it too.
    dialog.addEventListener("click", (e) => { if (e.target === dialog) closePanel(); });
    // Esc: slide out rather than vanish.
    dialog.addEventListener("cancel", (e) => { e.preventDefault(); closePanel(); });
    dialog.querySelector(".bag-clear").addEventListener("click", () => {
      if (confirm("Take everything out of your bag?")) TrekBag.clear();
    });
    dialog.querySelector(".bag-copy").addEventListener("click", copyList);
  }

  function variantLine(v) {
    const what = [v.brand, v.model_name].filter(Boolean).join(" ");
    const extra = [v.quality && v.quality[0].toUpperCase() + v.quality.slice(1), v.color].filter(Boolean).join(" · ");
    return `${what}${extra ? ` · ${extra}` : ""} — ${money(v.price, v.currency)}${v.vendor ? ` at ${v.vendor}` : ""}`;
  }

  function renderPanel() {
    if (!dialog) return;
    const n = items.length;
    dialog.querySelector(".bag-summary").textContent = n
      ? `${n} item${n === 1 ? "" : "s"} packed`
      : "Nothing packed yet";
    dialog.querySelector(".bag-copy").disabled = !n;
    dialog.querySelector(".bag-clear").disabled = !n;

    // An estimate from the buying options chosen so far, per currency.
    const priced = items.filter((i) => i.variant);
    const totals = {};
    for (const i of priced) totals[i.variant.currency] = (totals[i.variant.currency] || 0) + i.variant.price;
    const total = dialog.querySelector(".bag-total");
    total.hidden = !priced.length;
    total.innerHTML = priced.length
      ? `<span>Estimated cost</span><strong>${Object.entries(totals).map(([c, p]) => esc(money(p, c))).join(" + ")}</strong>` +
        `<span class="bag-total-note">${priced.length} of ${n} item${n === 1 ? "" : "s"} with a buying option chosen</span>`
      : "";

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
        const detail = item.variant
          ? `<div class="bag-variant">${esc(variantLine(item.variant))}</div>`
          : (why ? `<div class="bag-why">${esc(why)}</div>` : "");
        const hint = item.page_url
          // Not every gadget has buying options yet, so promise only the page.
          ? `<div class="bag-hint">${item.variant ? "Change buying option" : "View gadget and buying options"} →</div>`
          : "";
        const inner = `
            <span class="bag-thumb">${item.image_url ? `<img src="${esc(item.image_url)}" alt="" loading="lazy" />` : "🎒"}</span>
            <span class="bag-text">
              <span class="bag-name">${esc(item.name)}</span>
              ${detail}${hint}
            </span>`;
        // The whole item opens the gadget's page, at its buying options.
        row.innerHTML = (item.page_url
          ? `<a class="bag-link" href="${esc(item.page_url)}#buying-options">${inner}</a>`
          : `<div class="bag-link">${inner}</div>`) +
          `<button type="button" class="bag-remove" aria-label="Remove ${esc(item.name)} from your bag">Remove</button>`;
        row.querySelector(".bag-remove").addEventListener("click", () => TrekBag.remove(item.name));
        section.append(row);
      }
      return [section];
    }));
  }

  async function copyList() {
    const lines = PRIORITIES.flatMap((p) => {
      const group = items.filter((i) => (i.priority || null) === p.key);
      return group.length
        ? [`${p.name}:`, ...group.map((i) => `  - ${i.name}${i.variant ? ` (${variantLine(i.variant)})` : ""}`), ""]
        : [];
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
    dialog.classList.remove("closing");
    dialog.showModal();
  }

  function closePanel() {
    if (!dialog?.open) return;
    if (reduceMotion()) return dialog.close();
    dialog.classList.add("closing");
    dialog.addEventListener("animationend", () => {
      dialog.classList.remove("closing");
      dialog.close();
    }, { once: true });
  }

  // ---------- the header button and page buttons ----------

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

  function parse(json) {
    try { return JSON.parse(json); } catch { return null; }
  }

  function wireAddButtons() {
    for (const button of document.querySelectorAll("[data-bag-add]")) {
      const item = parse(button.dataset.bagAdd);
      if (!item) continue;
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

  function wireVariantButtons() {
    for (const button of document.querySelectorAll("[data-bag-variant]")) {
      const data = parse(button.dataset.bagVariant);
      if (!data?.gadget?.name || !data.variant) continue;
      const card = button.closest("[data-variant-card]");
      const paint = () => {
        const chosen = sameVariant(TrekBag.variantOf(data.gadget.name), cleanVariant(data.variant));
        button.classList.toggle("on", chosen);
        button.setAttribute("aria-pressed", String(chosen));
        button.textContent = chosen ? "✓ Chosen for your bag" : "Choose for my bag";
        card?.classList.toggle("chosen", chosen);
      };
      button.addEventListener("click", () => TrekBag.chooseVariant(data.gadget, data.variant));
      TrekBag.onChange(paint);
      paint();
    }
  }

  TrekBag.onChange(() => {
    renderHeaderButton();
    if (dialog?.open) renderPanel();
  });

  const start = () => { addHeaderButton(); wireAddButtons(); wireVariantButtons(); };
  if (document.readyState === "loading") document.addEventListener("DOMContentLoaded", start);
  else start();
})();
