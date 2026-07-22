(function () {
  const meLine = document.getElementById("me-line");
  const logoutBtn = document.getElementById("logout-btn");
  const authStatus = document.getElementById("auth-status");
  const profilesPanel = document.getElementById("profiles-panel");
  const profileList = document.getElementById("profile-list");
  const profileStatus = document.getElementById("profile-status");
  const resumeUploadPanel = document.getElementById("resume-upload-panel");
  const resumeActiveLine = document.getElementById("resume-active-line");
  const resumeList = document.getElementById("resume-list");
  const resumeUploadStatus = document.getElementById("resume-upload-status");
  const resumeProcessSummary = document.getElementById("resume-process-summary");
  const processResumesBtn = document.getElementById("process-resumes-btn");
  const processReplaceMode = document.getElementById("process-replace-mode");

  let activeProfileId = null;
  let activeProfileBuiltin = false;

  function setAuthStatus(text, kind) {
    if (!text) {
      authStatus.hidden = true;
      return;
    }
    authStatus.hidden = false;
    authStatus.className = "status " + (kind || "info");
    authStatus.textContent = text;
  }

  function setResumeStatus(text, kind) {
    if (!text) {
      resumeUploadStatus.hidden = true;
      return;
    }
    resumeUploadStatus.hidden = false;
    resumeUploadStatus.className = "status " + (kind || "info");
    resumeUploadStatus.textContent = text;
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
    activeProfileId = u.active_profile_id || null;
    await loadProfiles(u.active_profile_id);
    await refreshResumePanel(isDefault);
  }

  async function refreshResumePanel(isDefault) {
    if (isDefault || !activeProfileId || activeProfileBuiltin) {
      resumeUploadPanel.hidden = true;
      return;
    }
    resumeUploadPanel.hidden = false;
    resumeActiveLine.textContent = `Active profile #${activeProfileId}`;
    await loadResumeAssets(activeProfileId);
  }

  async function loadResumeAssets(pid) {
    resumeList.textContent = "Loading uploads…";
    const res = await fetch(`/api/profiles/${encodeURIComponent(pid)}/resumes`);
    if (!res.ok) {
      resumeList.textContent = "Could not list résumé uploads.";
      return;
    }
    const data = await res.json();
    const items = data.resumes || [];
    if (!items.length) {
      resumeList.textContent = "No résumé files on this profile yet.";
      return;
    }
    resumeList.innerHTML =
      "<strong>Uploaded:</strong> " +
      items
        .map(function (r) {
          return escape(r.original_name || r.kind) + " (" + escape(r.kind) + ")";
        })
        .join(" · ");
  }

  async function loadProfiles(activeId) {
    profileList.innerHTML = "";
    const res = await fetch("/api/profiles");
    if (!res.ok) return;
    const data = await res.json();
    activeProfileBuiltin = false;
    for (const p of data.profiles || []) {
      const li = document.createElement("li");
      li.className = "profile-row";
      const active = p.id === activeId;
      if (active) {
        activeProfileBuiltin = !!p.use_builtin;
      }
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

  document.getElementById("resume-upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeProfileId) {
      setResumeStatus("No active profile.", "error");
      return;
    }
    setResumeStatus("");
    resumeProcessSummary.hidden = true;
    const fd = new FormData(e.target);
    const res = await fetch(`/api/profiles/${encodeURIComponent(activeProfileId)}/resumes`, {
      method: "POST",
      body: fd,
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : res.statusText;
      setResumeStatus(detail || "Upload failed", "error");
      return;
    }
    e.target.reset();
    setResumeStatus("Uploaded " + (data.saved_as || "file") + ".", "success");
    await loadResumeAssets(activeProfileId);
  });

  processResumesBtn.addEventListener("click", async () => {
    if (!activeProfileId) {
      setResumeStatus("No active profile.", "error");
      return;
    }
    setResumeStatus("Processing…", "info");
    resumeProcessSummary.hidden = true;
    const mode = processReplaceMode.checked ? "replace" : "merge";
    const res = await fetch(
      `/api/profiles/${encodeURIComponent(activeProfileId)}/resumes/process`,
      {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ mode: mode }),
      }
    );
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const detail = typeof data.detail === "string" ? data.detail : res.statusText;
      setResumeStatus(detail || "Process failed", "error");
      return;
    }
    setResumeStatus(data.message || "Profile updated.", "success");
    const profile = data.profile || {};
    const roles = profile.roles || [];
    const conflicts = profile.conflicts || [];
    resumeProcessSummary.hidden = false;
    resumeProcessSummary.innerHTML =
      "Roles: " +
      roles.length +
      (conflicts.length ? " · Conflicts: " + conflicts.length : "") +
      (typeof data.chunks_written === "number"
        ? " · RAG chunks: " + data.chunks_written
        : "");
  });

  refreshMe();
})();
