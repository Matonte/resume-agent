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
    const signedIn = !!u.authenticated;
    const builtin = !!u.use_builtin_profile || u.id === 1;
    const authForms = document.getElementById("auth-forms");
    const registerWrap = document.getElementById("register-wrap");
    const loginWrap = document.getElementById("login-wrap");
    const loginNote = document.getElementById("login-required-note");
    const appLinks = document.querySelectorAll(".links a:not([href='/account'])");

    if (!signedIn) {
      meLine.textContent = "Not signed in. Log in or create an account to use Resume Agent.";
      if (authForms) authForms.hidden = false;
      if (registerWrap) registerWrap.hidden = false;
      if (loginWrap) loginWrap.hidden = false;
      if (loginNote) loginNote.hidden = false;
      appLinks.forEach((a) => {
        a.hidden = true;
      });
      logoutBtn.hidden = true;
      profilesPanel.hidden = true;
      resumeUploadPanel.hidden = true;
      return;
    }

    meLine.textContent = `${u.display_name || u.email} · ${u.email} · active profile #${u.active_profile_id || "—"}`;
    if (authForms) authForms.hidden = true;
    if (registerWrap) registerWrap.hidden = true;
    if (loginWrap) loginWrap.hidden = true;
    if (loginNote) loginNote.hidden = true;
    appLinks.forEach((a) => {
      a.hidden = false;
    });
    logoutBtn.hidden = false;
    profilesPanel.hidden = false;
    activeProfileId = u.active_profile_id || null;
    await loadProfiles(u.active_profile_id);
    await refreshResumePanel(builtin);
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

  const forgotForm = document.getElementById("forgot-form");
  const forgotLink = document.getElementById("forgot-link");
  const forgotCancel = document.getElementById("forgot-cancel");
  if (forgotLink && forgotForm) {
    forgotLink.addEventListener("click", (e) => {
      e.preventDefault();
      forgotForm.hidden = false;
      const loginEmail = document.querySelector('#login-form input[name="email"]');
      const forgotEmail = forgotForm.querySelector('input[name="email"]');
      if (loginEmail && forgotEmail && loginEmail.value) {
        forgotEmail.value = loginEmail.value;
      }
    });
  }
  if (forgotCancel && forgotForm) {
    forgotCancel.addEventListener("click", () => {
      forgotForm.hidden = true;
    });
  }
  if (forgotForm) {
    forgotForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      setAuthStatus("");
      const fd = new FormData(e.target);
      const res = await fetch("/api/auth/forgot-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ email: fd.get("email") }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setAuthStatus(data.detail || String(res.status), "error");
        return;
      }
      let msg = data.message || "Check your email for a reset link.";
      if (data.email_configured === false) {
        msg +=
          " Mail is not configured on this server (set GMAIL_ADDRESS / GMAIL_APP_PASSWORD), so no email was sent.";
      } else if (data.email_sent === false) {
        msg += " If you don't see mail soon, ask an admin to reset your password.";
      }
      if (data.dev_reset_token) {
        msg += " Dev token: open /account?reset=" + data.dev_reset_token;
        history.replaceState(null, "", "/account?reset=" + encodeURIComponent(data.dev_reset_token));
        showResetPanel(data.dev_reset_token);
      }
      setAuthStatus(msg, data.email_sent ? "success" : "warn");
    });
  }

  const resetPanel = document.getElementById("reset-panel");
  const resetForm = document.getElementById("reset-form");
  const resetStatus = document.getElementById("reset-status");
  const resetTokenInput = document.getElementById("reset-token");

  function setResetStatus(text, kind) {
    if (!resetStatus) return;
    if (!text) {
      resetStatus.hidden = true;
      return;
    }
    resetStatus.hidden = false;
    resetStatus.className = "status " + (kind || "info");
    resetStatus.textContent = text;
  }

  function showResetPanel(token) {
    if (!resetPanel || !resetTokenInput) return;
    resetPanel.hidden = false;
    resetTokenInput.value = token || "";
    resetPanel.scrollIntoView({ behavior: "smooth", block: "start" });
  }

  try {
    const params = new URLSearchParams(window.location.search);
    const resetTok = params.get("reset");
    if (resetTok) showResetPanel(resetTok);
  } catch (_) {}

  if (resetForm) {
    resetForm.addEventListener("submit", async (e) => {
      e.preventDefault();
      setResetStatus("");
      const fd = new FormData(e.target);
      const password = String(fd.get("password") || "");
      const password2 = String(fd.get("password2") || "");
      const token = String(fd.get("token") || "");
      if (password !== password2) {
        setResetStatus("Passwords do not match.", "error");
        return;
      }
      const res = await fetch("/api/auth/reset-password", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token: token, password: password }),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        setResetStatus(data.detail || String(res.status), "error");
        return;
      }
      setResetStatus("Password updated — you are signed in.", "success");
      history.replaceState(null, "", "/account");
      await refreshMe();
    });
  }

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

  const accountExtractReview = document.getElementById("account-extract-review");
  const accountExtractPreview = document.getElementById("account-extract-preview");
  const accountExtractConfirm = document.getElementById("account-extract-confirm");
  if (accountExtractConfirm) {
    accountExtractConfirm.addEventListener("click", () => {
      if (accountExtractReview) accountExtractReview.hidden = true;
      setResumeStatus("Extracted text confirmed. You can process résumés when ready.", "success");
    });
  }

  document.getElementById("resume-upload-form").addEventListener("submit", async (e) => {
    e.preventDefault();
    if (!activeProfileId) {
      setResumeStatus("No active profile.", "error");
      return;
    }
    setResumeStatus("");
    resumeProcessSummary.hidden = true;
    if (accountExtractReview) accountExtractReview.hidden = true;
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
    setResumeStatus(
      "Uploaded " +
        (data.saved_as || "file") +
        (data.extracted_chars != null ? " · extracted " + data.extracted_chars + " chars" : "") +
        ". Review the text below before processing.",
      "success",
    );
    if (accountExtractPreview && accountExtractReview && data.extracted_preview) {
      accountExtractPreview.textContent = data.extracted_preview;
      accountExtractReview.hidden = false;
    }
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
