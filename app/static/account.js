(function () {
  const meLine = document.getElementById("me-line");
  const logoutBtn = document.getElementById("logout-btn");
  const authStatus = document.getElementById("auth-status");
  const profilesPanel = document.getElementById("profiles-panel");
  const profileList = document.getElementById("profile-list");
  const profileStatus = document.getElementById("profile-status");

  function setAuthStatus(text, kind) {
    if (!text) {
      authStatus.hidden = true;
      return;
    }
    authStatus.hidden = false;
    authStatus.className = "status " + (kind || "info");
    authStatus.textContent = text;
  }

  async function refreshMe() {
    const res = await fetch("/api/auth/me");
    if (!res.ok) {
      meLine.textContent = "Could not load session.";
      return;
    }
    const u = await res.json();
    const isDefault = u.id === 1;
    meLine.textContent = isDefault
      ? "Default workspace (repository data/). Log in for your own isolated resume packs."
      : `${u.display_name || u.email} · ${u.email} · active profile #${u.active_profile_id || "—"}`;
    logoutBtn.hidden = isDefault;
    profilesPanel.hidden = false;
    await loadProfiles(u.active_profile_id);
  }

  async function loadProfiles(activeId) {
    profileList.innerHTML = "";
    const res = await fetch("/api/profiles");
    if (!res.ok) return;
    const data = await res.json();
    for (const p of data.profiles || []) {
      const li = document.createElement("li");
      li.className = "profile-row";
      const active = p.id === activeId;
      li.innerHTML =
        `<span class="profile-name">${escape(p.name)}${p.use_builtin ? " (built-in)" : ""}</span>` +
        `<code class="profile-slug">${escape(p.slug)}</code>` +
        (active
          ? `<span class="pill">active</span>`
          : `<button type="button" data-pid="${p.id}">Activate</button>`);
      profileList.appendChild(li);
    }
    profileList.querySelectorAll("button[data-pid]").forEach((btn) => {
      btn.addEventListener("click", () => activateProfile(btn.dataset.pid));
    });
  }

  function escape(s) {
    return String(s || "")
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  async function activateProfile(pid) {
    profileStatus.hidden = true;
    const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}/activate`, {
      method: "POST",
    });
    const body = await res.json().catch(() => ({}));
    if (!res.ok) {
      profileStatus.hidden = false;
      profileStatus.className = "status error";
      profileStatus.textContent = body.detail || res.statusText;
      return;
    }
    profileStatus.hidden = false;
    profileStatus.className = "status success";
    profileStatus.textContent = "Active profile updated. Reload other tabs if needed.";
    await refreshMe();
  }

  document.getElementById("register-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    setAuthStatus("");
    const fd = new FormData(e.target);
    const res = await fetch("/api/auth/register", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: fd.get("email"),
        display_name: fd.get("display_name") || "",
        password: fd.get("password"),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAuthStatus(data.detail || String(res.status), "error");
      return;
    }
    if (data.user && data.user.needs_onboarding) {
      window.location.href = "/onboarding";
      return;
    }
    setAuthStatus("Registered and signed in.", "success");
    await refreshMe();
  });

  document.getElementById("login-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    setAuthStatus("");
    const fd = new FormData(e.target);
    const res = await fetch("/api/auth/login", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({
        email: fd.get("email"),
        password: fd.get("password"),
      }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      setAuthStatus(data.detail || String(res.status), "error");
      return;
    }
    if (data.user && data.user.needs_onboarding) {
      window.location.href = "/onboarding";
      return;
    }
    setAuthStatus("Signed in.", "success");
    await refreshMe();
  });

  logoutBtn.addEventListener("click", async () => {
    await fetch("/api/auth/logout", { method: "POST" });
    setAuthStatus("Logged out.", "info");
    await refreshMe();
  });

  document.getElementById("new-profile-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    profileStatus.hidden = true;
    const fd = new FormData(e.target);
    const res = await fetch("/api/profiles", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ name: fd.get("name") }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      profileStatus.hidden = false;
      profileStatus.className = "status error";
      profileStatus.textContent = data.detail || res.statusText;
      return;
    }
    e.target.reset();
    const me = await fetch("/api/auth/me").then((r) => r.json());
    await loadProfiles(me.active_profile_id);
    profileStatus.hidden = false;
    profileStatus.className = "status success";
    profileStatus.textContent = "Profile created from template.";
  });

  refreshMe();
})();
