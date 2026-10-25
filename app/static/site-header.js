// Master header: when a coordinator is already signed in, "Register" becomes
// "Dashboard" and "Login" becomes "Log out". The session cookie is httponly,
// so ask the server rather than reading it.
(async () => {
  const nav = document.querySelector(".site-header nav");
  if (!nav) return;

  let res;
  try {
    res = await fetch("/api/auth/me", { credentials: "same-origin" });
  } catch {
    return;
  }
  if (!res.ok) return;

  const register = nav.querySelector(".register");
  const login = nav.querySelector(".login");

  register.textContent = "Dashboard";
  register.href = "/coordinator";

  login.textContent = "Log out";
  login.href = "/";
  login.addEventListener("click", async (e) => {
    e.preventDefault();
    // The server refuses writes without this header (CSRF protection), so
    // without it the session would stay open behind a "logged out" page.
    await fetch("/api/auth/logout", {
      method: "POST",
      credentials: "same-origin",
      headers: { "X-Requested-With": "trekxp" },
    });
    location.reload();
  });
})();
