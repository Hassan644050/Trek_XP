// The saved bag page (/bag/<code>): add everything to this browser's bag,
// or pass the link on. The share links carry ?ref=bag-… so the visitor
// analytics can tell which app brought people.
(() => {
  "use strict";

  const add = document.querySelector("[data-bag-import]");
  if (add) {
    add.addEventListener("click", () => {
      if (!window.TrekBag) return;
      let items = [];
      try { items = JSON.parse(add.dataset.bagImport); } catch { return; }
      // Anything already in the bag keeps its own choices; new ones come in.
      for (const item of items) TrekBag.add(item);
      add.textContent = `Added ${items.length} to your bag ✓`;
      TrekBag.open();
    });
  }

  const bar = document.querySelector("[data-share-bag]");
  if (!bar) return;

  const isPhone = /android|iphone|ipad|ipod/i.test(navigator.userAgent);
  bar.querySelector('[data-share="native"]').hidden = !navigator.share;
  // Messenger's share link needs the app; on a desktop it would need a
  // Facebook app ID.
  bar.querySelector('[data-share="ms"]').hidden = !isPhone;

  const link = (ref) => `${location.origin}/bag/${bar.dataset.code}?ref=${ref}`;
  const names = [...document.querySelectorAll(".sb-item a.sb-name")].map((a) => a.textContent.trim());
  const text = () => `${bar.dataset.title}: ${names.slice(0, 5).join(", ")}${names.length > 5 ? ` and ${names.length - 5} more` : ""}`;

  bar.addEventListener("click", async (e) => {
    const btn = e.target.closest("[data-share]");
    if (!btn) return;
    const open = (url) => window.open(url, "_blank", "noopener");
    switch (btn.dataset.share) {
      case "native":
        navigator.share({ title: bar.dataset.title, text: text(), url: link("bag-native") }).catch(() => {});
        break;
      case "wa":
        open(`https://wa.me/?text=${encodeURIComponent(`${text()}\n${link("bag-wa")}`)}`);
        break;
      case "fb":
        open(`https://www.facebook.com/sharer/sharer.php?u=${encodeURIComponent(link("bag-fb"))}`);
        break;
      case "ms":
        location.href = `fb-messenger://share/?link=${encodeURIComponent(link("bag-ms"))}`;
        break;
      case "copy":
        try { await navigator.clipboard.writeText(link("bag-link")); } catch { /* shown below */ }
        btn.textContent = "Link copied ✓";
        setTimeout(() => { btn.textContent = "Copy link"; }, 2000);
        break;
    }
  });
})();
