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
        '<strong>Finish setup to unlock tailoring.</strong> Add a résumé and a few job samples on ' +
        '<a href="/onboarding">setup</a> so we can tailor without inventing experience.';
      const shell = document.querySelector(".shell");
      (shell || document.body).insertBefore(bar, shell && shell.firstChild);
    })
    .catch(() => {});
})();
