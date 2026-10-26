// Filtering and sorting on the compare page (/compare/<gadget>). The cards
// carry their facts as data attributes; without JavaScript the full list
// still shows, cheapest first, and the filter form is hidden.
(() => {
  "use strict";

  const form = document.getElementById("cmpFilters");
  const grid = document.getElementById("cmpGrid");
  if (!form || !grid) return;

  const cards = [...grid.querySelectorAll(".cmp-card")];
  const count = document.getElementById("cmpCount");
  const none = document.getElementById("cmpNone");
  const total = cards.length;
  const RANK = { premium: 0, standard: 1, budget: 2 };

  function apply() {
    const f = new FormData(form);
    const quality = f.get("quality") || "";
    const brand = f.get("brand") || "";
    const color = f.get("color") || "";
    const sort = f.get("sort") || "price-asc";

    const shown = cards.filter((card) => {
      const ok = (!quality || card.dataset.quality === quality)
        && (!brand || card.dataset.brand === brand)
        && (!color || card.dataset.color === color);
      card.hidden = !ok;
      return ok;
    });

    const price = (c) => Number(c.dataset.price);
    const order = {
      "price-asc": (a, b) => price(a) - price(b),
      "price-desc": (a, b) => price(b) - price(a),
      quality: (a, b) => (RANK[a.dataset.quality] - RANK[b.dataset.quality]) || price(a) - price(b),
    }[sort];
    grid.append(...[...cards].sort(order));

    none.hidden = shown.length > 0;
    if (shown.length) {
      const prices = shown.map(price);
      const low = Math.min(...prices), high = Math.max(...prices);
      const money = (p) => `৳${p.toLocaleString()}`;
      count.textContent = `${shown.length === total ? "" : `${shown.length} of `}${total} option${total === 1 ? "" : "s"}` +
        ` · ${low === high ? money(low) : `${money(low)} – ${money(high)}`}`;
    } else {
      count.textContent = `0 of ${total} options`;
    }
  }

  form.addEventListener("change", apply);
  form.addEventListener("submit", (e) => e.preventDefault());
})();
