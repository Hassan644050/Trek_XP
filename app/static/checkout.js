// The checkout page (/checkout).
//
// The bag lives in this browser (bag.js); this page turns the gadgets with a
// chosen buying option into an order:
//   1. price them with POST /api/checkout/quote -- today's prices and stock,
//      never the ones saved in the bag;
//   2. take the delivery details and the payment method (cash on delivery);
//   3. place the order with POST /api/checkout, then show its code and take
//      the ordered gadgets out of the bag.
// Quantities and the half-filled form are kept for this tab (sessionStorage),
// so a reload does not lose them.
(() => {
  "use strict";

  const root = document.getElementById("checkout");
  const QTY_KEY = "trekxp.checkout.qty";
  const FORM_KEY = "trekxp.checkout.form";
  const SYMBOLS = { BDT: "৳", USD: "$", EUR: "€", GBP: "£", INR: "₹" };

  const esc = (s) => String(s ?? "").replace(/[&<>"']/g,
    (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
  const store = {
    get(key) { try { return JSON.parse(sessionStorage.getItem(key) || "{}"); } catch { return {}; } },
    set(key, value) { try { sessionStorage.setItem(key, JSON.stringify(value)); } catch { /* this page only */ } },
    drop(key) { try { sessionStorage.removeItem(key); } catch { /* nothing to drop */ } },
  };
  const compareUrl = (item, slug) =>
    slug ? `/compare/${encodeURIComponent(slug)}` : (item?.page_url || "/").replace(/^\/gadget\//, "/compare/");

  let quote = null;        // the server's answer for the current bag
  let zone = null;         // chosen delivery zone key
  let placing = false;
  let qty = store.get(QTY_KEY);   // variant id -> quantity
  let form = store.get(FORM_KEY);

  const money = (n) => `${SYMBOLS[quote?.currency] ?? ""}${Number(n || 0).toLocaleString("en-IN")}`;

  // Bag items that can be ordered (an option with an id), and the rest.
  function bagLines() {
    const items = window.TrekBag ? TrekBag.items() : [];
    const buyable = items.filter((i) => i.variant?.id);
    const unchosen = items.filter((i) => !i.variant?.id);
    return { buyable, unchosen };
  }

  async function load() {
    const { buyable, unchosen } = bagLines();
    if (!buyable.length) return renderEmpty(unchosen);

    try {
      const res = await fetch("/api/checkout/quote", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ items: buyable.map((i) => ({ variant_id: i.variant.id, quantity: qty[i.variant.id] || 1 })) }),
      });
      if (!res.ok) throw new Error();
      quote = await res.json();
    } catch {
      root.innerHTML = `<h1>Checkout</h1><p class="co-error">We could not load your order right now. Please refresh the page in a moment.</p>`;
      return;
    }
    // The server may have lowered a quantity to what is left.
    for (const line of quote.lines) if (line.quantity) qty[line.variant_id] = line.quantity;
    store.set(QTY_KEY, qty);
    zone = form.delivery_zone && quote.zones.some((z) => z.key === form.delivery_zone)
      ? form.delivery_zone : (quote.zones.length === 1 ? quote.zones[0].key : null);
    render(buyable, unchosen);
  }

  // ---------- empty ----------

  function renderEmpty(unchosen) {
    root.innerHTML = `
      <h1>Checkout</h1>
      <section class="co-card">
        ${unchosen.length ? `
          <h2>Choose what to buy</h2>
          <p class="co-note">Your bag has gadgets, but no buying option chosen yet. Pick a brand and price for each one you want:</p>
          ${chooseList(unchosen)}` : `
          <h2>Your bag is empty</h2>
          <p class="co-note">Build a packing list, add gadgets to your bag, and choose a buying option for each.</p>`}
        <div class="co-actions"><a class="co-btn primary" href="/">Back to my packing list</a></div>
      </section>`;
  }

  function chooseList(items) {
    return `<ul>${items.map((i) =>
      `<li><a href="${esc(compareUrl(i))}">${esc(i.name)}</a> — choose a buying option</li>`).join("")}</ul>`;
  }

  // ---------- the order form ----------

  function render(buyable, unchosen) {
    const byId = new Map(buyable.map((i) => [i.variant.id, i]));
    const ok = quote.lines.filter((l) => l.status === "ok" || l.status === "not_enough");

    root.innerHTML = `
      <h1>Checkout</h1>
      <div class="co-grid">
        <div class="co">
          <section class="co-card" aria-labelledby="coItems">
            <h2 id="coItems"><span class="co-step">1</span>Your order</h2>
            <ul class="co-lines">${quote.lines.map((l) => lineHtml(l, byId.get(l.variant_id))).join("")}</ul>
            ${unchosen.length ? `<div class="co-choose"><strong>Not in this order yet</strong>
              <span class="co-note">Choose a buying option to add these:</span>${chooseList(unchosen)}</div>` : ""}
          </section>

          <section class="co-card" aria-labelledby="coDelivery">
            <h2 id="coDelivery"><span class="co-step">2</span>Delivery details</h2>
            <form class="co-form" id="coForm" novalidate>
              ${field("name", "Full name", { autocomplete: "name", required: true })}
              ${field("phone", "Mobile number", { autocomplete: "tel", inputmode: "tel", required: true,
                placeholder: "01712345678", hint: "We call this number to confirm before sending." })}
              ${field("address", "Address", { textarea: true, wide: true, autocomplete: "street-address", required: true,
                placeholder: "House, road, area" })}
              ${field("area", "City / district", { autocomplete: "address-level2", required: true, placeholder: "Dhaka" })}
              ${field("email", "Email", { type: "email", autocomplete: "email", optional: true })}
              <fieldset class="co-choices co-field wide">
                <legend class="co-legend">Delivery</legend>
                ${quote.zones.map((z) => `
                  <label class="co-choice">
                    <input type="radio" name="delivery_zone" value="${esc(z.key)}" ${z.key === zone ? "checked" : ""} />
                    <span class="grow"><b>${esc(z.label)}</b>${z.days ? `<small>${esc(z.days)}</small>` : ""}</span>
                    <b>${money(z.fee)}</b>
                  </label>`).join("")}
              </fieldset>
              ${field("note", "Note for the courier", { textarea: true, wide: true, optional: true,
                placeholder: "Landmark, best time to call…" })}
              <div class="co-hp" aria-hidden="true"><label>Website <input name="website" tabindex="-1" autocomplete="off" /></label></div>
            </form>
          </section>

          <section class="co-card" aria-labelledby="coPay">
            <h2 id="coPay"><span class="co-step">3</span>Payment</h2>
            <div class="co-choices">
              ${quote.payment_methods.map((m, n) => `
                <label class="co-choice">
                  <input type="radio" name="payment_method" value="${esc(m.key)}" ${n === 0 ? "checked" : ""} />
                  <span class="grow"><b>${esc(m.label)}</b>${m.detail ? `<small>${esc(m.detail)}</small>` : ""}</span>
                </label>`).join("")}
            </div>
          </section>
        </div>

        <aside class="co-card co-summary" aria-labelledby="coSum">
          <h2 id="coSum">Order summary</h2>
          <dl class="co-sum" id="coTotals"></dl>
          <p class="co-error" id="coError" hidden></p>
          <button type="button" class="co-place" id="coPlace">Place order</button>
          <p class="co-note">You pay in cash when it arrives. We call you first to confirm.</p>
        </aside>
      </div>`;

    if (!ok.length) {
      showError("Nothing in your bag can be ordered right now — see the notes above.");
    }
    wire(byId);
    renderTotals();
  }

  function field(name, label, o = {}) {
    const value = esc(form[name] || "");
    const attrs = [
      `id="co_${name}"`, `name="${name}"`,
      o.autocomplete && `autocomplete="${o.autocomplete}"`, o.inputmode && `inputmode="${o.inputmode}"`,
      o.placeholder && `placeholder="${esc(o.placeholder)}"`, o.required && "required",
    ].filter(Boolean).join(" ");
    const control = o.textarea ? `<textarea ${attrs}>${value}</textarea>`
      : `<input type="${o.type || "text"}" ${attrs} value="${value}" />`;
    return `<div class="co-field${o.wide ? " wide" : ""}">
      <label for="co_${name}">${esc(label)}${o.optional ? ' <span class="opt">optional</span>' : ""}</label>
      ${control}${o.hint ? `<span class="co-hint">${esc(o.hint)}</span>` : ""}</div>`;
  }

  function lineHtml(line, bagItem) {
    const name = line.gadget || bagItem?.name || "This item";
    const pic = line.image_url
      ? `<img src="${esc(line.image_url)}" alt="" loading="lazy" />`
      : `<span>${esc(name.trim().charAt(0).toUpperCase())}</span>`;
    const warn = {
      out_of_stock: `Sold out. <a href="${esc(compareUrl(bagItem, line.gadget_slug))}">Choose another option</a>`,
      not_enough: `Only ${line.available} left — quantity lowered.`,
      unavailable: "No longer sold here.",
    }[line.status];
    const live = line.status === "ok" || line.status === "not_enough";
    const n = line.quantity;
    return `
      <li class="co-line" data-variant="${line.variant_id}">
        <div class="co-pic">${pic}</div>
        <div class="co-what">
          <a class="co-name" href="${esc(compareUrl(bagItem, line.gadget_slug))}">${esc(name)}</a>
          ${line.option ? `<span class="co-opt">${esc(line.option)}${line.vendor ? ` · from ${esc(line.vendor)}` : ""}</span>` : ""}
          ${warn ? `<span class="co-warn">${warn}</span>` : ""}
          <button type="button" class="co-remove" data-remove>Remove</button>
        </div>
        <div class="co-side">
          ${live ? `
            <span class="co-price">${money(line.line_total)}</span>
            ${n > 1 ? `<span class="co-each">${money(line.unit_price)} each</span>` : ""}
            <span class="co-qty" role="group" aria-label="Quantity of ${esc(name)}">
              <button type="button" data-step="-1" aria-label="One fewer" ${n <= 1 ? "disabled" : ""}>−</button>
              <output>${n}</output>
              <button type="button" data-step="1" aria-label="One more" ${n >= line.available ? "disabled" : ""}>+</button>
            </span>` : ""}
        </div>
      </li>`;
  }

  // ---------- behaviour ----------

  function wire(byId) {
    root.querySelector(".co-lines").addEventListener("click", (e) => {
      const row = e.target.closest(".co-line");
      if (!row) return;
      const id = Number(row.dataset.variant);
      const line = quote.lines.find((l) => l.variant_id === id);

      if (e.target.closest("[data-remove]")) {
        const item = byId.get(id);
        if (item) TrekBag.remove(item.name);  // the bag's change reloads the page
        return;
      }
      const step = Number(e.target.closest("[data-step]")?.dataset.step || 0);
      if (!step || !line) return;
      const next = Math.min(Math.max(line.quantity + step, 1), line.available);
      if (next === line.quantity) return;
      qty[id] = next;
      store.set(QTY_KEY, qty);
      load();  // re-priced by the server, never added up here alone
    });

    const formEl = root.querySelector("#coForm");
    formEl.addEventListener("input", () => {
      const data = Object.fromEntries(new FormData(formEl));
      delete data.website;
      form = data;
      zone = data.delivery_zone || zone;
      store.set(FORM_KEY, form);
      renderTotals();
    });
    root.querySelector("#coPlace").addEventListener("click", placeOrder);
  }

  function liveLines() {
    return quote.lines.filter((l) => (l.status === "ok" || l.status === "not_enough") && l.quantity > 0);
  }

  function renderTotals() {
    const lines = liveLines();
    const count = lines.reduce((n, l) => n + l.quantity, 0);
    const subtotal = lines.reduce((n, l) => n + l.line_total, 0);
    const chosen = quote.zones.find((z) => z.key === zone);
    root.querySelector("#coTotals").innerHTML = `
      <div><dt>Items (${count})</dt><dd>${money(subtotal)}</dd></div>
      <div><dt>Delivery${chosen ? ` · ${esc(chosen.label)}` : ""}</dt><dd>${chosen ? money(chosen.fee) : "Choose below"}</dd></div>
      <div class="total"><dt>Total</dt><dd>${money(subtotal + (chosen?.fee || 0))}</dd></div>`;
    root.querySelector("#coPlace").disabled = placing || !lines.length;
    root.querySelector("#coPlace").textContent = placing ? "Placing your order…"
      : `Place order · ${money(subtotal + (chosen?.fee || 0))}`;
  }

  function showError(message) {
    const box = root.querySelector("#coError");
    if (!box) return;
    box.textContent = message;
    box.hidden = !message;
    if (message) box.scrollIntoView({ block: "nearest", behavior: "smooth" });
  }

  // What the traveller must fix before we ask the server.
  function missing(data) {
    const need = [];
    if ((data.name || "").trim().length < 2) need.push("your name");
    if (!/^\+?[\d\s-]{10,16}$/.test((data.phone || "").trim())) need.push("a mobile number");
    if ((data.address || "").trim().length < 8) need.push("your address");
    if ((data.area || "").trim().length < 2) need.push("your city or district");
    if (!data.delivery_zone) need.push("where to deliver");
    return need;
  }

  function serverMessage(body, status) {
    if (typeof body?.detail === "string") return body.detail;
    if (Array.isArray(body?.detail)) {
      const first = body.detail[0];
      const where = (first?.loc || []).slice(-1)[0];
      return `Please check ${where ? `the ${String(where).replace(/_/g, " ")}` : "your details"}: ${first?.msg || "it is not valid"}.`;
    }
    return status === 429 ? "Too many orders from this connection — please try again later."
      : "Your order could not be placed. Please try again.";
  }

  async function placeOrder() {
    showError("");
    const formEl = root.querySelector("#coForm");
    const data = Object.fromEntries(new FormData(formEl));
    const need = missing(data);
    if (need.length) {
      showError(`Please add ${need.join(", ")}.`);
      formEl.querySelector(":invalid, [required]:placeholder-shown")?.focus();
      return;
    }

    placing = true;
    renderTotals();
    const lines = liveLines();
    try {
      const res = await fetch("/api/checkout", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json", "X-Requested-With": "trekxp" },
        body: JSON.stringify({
          items: lines.map((l) => ({ variant_id: l.variant_id, quantity: l.quantity })),
          customer: {
            name: data.name, phone: data.phone, email: data.email || null, address: data.address,
            area: data.area, delivery_zone: data.delivery_zone, note: data.note || null,
          },
          payment_method: root.querySelector('input[name="payment_method"]:checked')?.value || "cod",
          website: data.website || "",
        }),
      });
      const body = await res.json().catch(() => ({}));
      if (res.status === 409) {
        // Stock changed while they were filling in the form: re-price, keep the form.
        placing = false;
        await load();
        showError(serverMessage(body, res.status));
        return;
      }
      if (!res.ok) throw Object.assign(new Error(serverMessage(body, res.status)), { shown: true });
      done(body, lines);
    } catch (err) {
      placing = false;
      renderTotals();
      showError(err.shown ? err.message : "We could not reach the shop. Check your connection and try again.");
    }
  }

  // ---------- placed ----------

  function done(order, lines) {
    // The ordered gadgets leave the bag; anything else stays.
    const ordered = new Set(lines.map((l) => l.variant_id));
    for (const item of TrekBag.items()) if (ordered.has(item.variant?.id)) TrekBag.remove(item.name);
    store.drop(QTY_KEY);
    store.drop(FORM_KEY);

    const first = order.customer_name.split(" ")[0];
    root.innerHTML = `
      <section class="co-card co-done">
        <h1>Thank you, ${esc(first)}!</h1>
        <p class="co-note">Your order is placed. Keep this code — quote it if you call us:</p>
        <span class="co-code">${esc(order.code)}</span>
        <ol class="co-steps">
          <li>We call <b>${esc(order.phone)}</b> to confirm your order.</li>
          <li>It goes out by courier: ${esc(order.delivery_label)}.</li>
          <li>You pay <b>${money(order.total)}</b> in cash when it arrives.</li>
        </ol>
        <ul class="co-lines">${order.lines.map((l) => `
          <li class="co-line" style="grid-template-columns:minmax(0,1fr) auto">
            <div class="co-what"><span class="co-name">${esc(l.gadget_name)} × ${l.quantity}</span>
              <span class="co-opt">${esc(l.option)}</span></div>
            <div class="co-side"><span class="co-price">${money(l.line_total)}</span></div>
          </li>`).join("")}
        </ul>
        <dl class="co-sum" style="width:100%">
          <div><dt>Items</dt><dd>${money(order.subtotal)}</dd></div>
          <div><dt>Delivery</dt><dd>${money(order.delivery_fee)}</dd></div>
          <div class="total"><dt>Total, cash on delivery</dt><dd>${money(order.total)}</dd></div>
        </dl>
        <div class="co-actions"><a class="co-btn primary" href="/">Back to my packing list</a></div>
      </section>`;
    window.scrollTo({ top: 0, behavior: "smooth" });
  }

  // bag.js loads first (both are deferred, in order). A change to the bag --
  // here, in its panel, or in another tab -- re-prices the page.
  function start() {
    if (!window.TrekBag) {
      root.innerHTML = `<h1>Checkout</h1><p class="co-error">The bag could not be loaded. Please refresh the page.</p>`;
      return;
    }
    TrekBag.onChange(() => { if (!placing && !root.querySelector(".co-done")) load(); });
    load();
  }
  start();
})();
