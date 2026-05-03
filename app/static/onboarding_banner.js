(function () {
  if (location.pathname.startsWith("/onboarding")) return;
  fetch("/api/auth/me")
    .then((r) => (r.ok ? r.json() : null))
    .then((u) => {
      if (!u || !u.needs_onboarding) return;
      const bar = document.createElement("div");
      bar.className = "status warn";
      bar.setAttribute("role", "status");
      bar.style.marginBottom = "1rem";
      bar.innerHTML =
        '<strong>Setup required.</strong> Finish <a href="/onboarding">account setup</a> ' +
        "(résumé + job samples) before tailoring and queue actions work end-to-end.";
      const shell = document.querySelector(".shell");
      (shell || document.body).insertBefore(bar, shell && shell.firstChild);
    })
    .catch(() => {});
})();
