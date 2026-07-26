(function () {
  const statusLine = document.getElementById("status-line");
  const banner = document.getElementById("banner");
  const resumeForm = document.getElementById("resume-form");
  const jdForm = document.getElementById("jd-form");
  const resumeList = document.getElementById("resume-list");
  const jdCount = document.getElementById("jd-count");
  const finishBtn = document.getElementById("finish-btn");
  const finishMsg = document.getElementById("finish-msg");
  const finishDisabledReason = document.getElementById("finish-disabled-reason");
  const finishHelp = document.getElementById("finish-help");
  const progressList = document.getElementById("onboarding-progress");
  const extractReview = document.getElementById("extract-review");
  const extractPreview = document.getElementById("extract-preview");
  const extractConfirmBtn = document.getElementById("extract-confirm-btn");
  const reviewPanel = document.getElementById("review-panel");
  const conflictsBox = document.getElementById("conflicts-box");
  const rolesEditor = document.getElementById("roles-editor");
  const saveReviewBtn = document.getElementById("save-review-btn");
  const confirmBtn = document.getElementById("confirm-btn");
  const reviewMsg = document.getElementById("review-msg");
  const revName = document.getElementById("rev-name");
  const revHeadline = document.getElementById("rev-headline");
  const revYears = document.getElementById("rev-years");

  let currentProfile = null;
  /** True only after an upload in this session until the user confirms extraction. */
  let pendingExtractReview = false;

  function showBanner(text, kind) {
    if (!text) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    banner.className = "status " + (kind || "info");
    banner.textContent = text;
  }

  function showReviewMsg(text, kind) {
    if (!text) {
      reviewMsg.hidden = true;
      return;
    }
    reviewMsg.hidden = false;
    reviewMsg.className = "status " + (kind || "info");
    reviewMsg.textContent = text;
  }

  function renderConflicts(conflicts) {
    if (!conflicts || !conflicts.length) {
      conflictsBox.hidden = true;
      conflictsBox.textContent = "";
      return;
    }
    conflictsBox.hidden = false;
    conflictsBox.innerHTML =
      "<strong>Conflicts to resolve:</strong><ul>" +
      conflicts
        .map(function (c) {
          return "<li>" + escapeHtml(c.message || c.type || "conflict") + "</li>";
        })
        .join("") +
      "</ul>";
  }

  function escapeHtml(s) {
    return String(s)
      .replace(/&/g, "&amp;")
      .replace(/</g, "&lt;")
      .replace(/>/g, "&gt;")
      .replace(/"/g, "&quot;");
  }

  function renderRoles(roles) {
    rolesEditor.innerHTML = "";
    (roles || []).forEach(function (role, ri) {
      const wrap = document.createElement("div");
      wrap.className = "panel";
      wrap.style.marginTop = "0.75rem";
      wrap.dataset.roleIndex = String(ri);

      const achText = (role.achievements || [])
        .map(function (a) {
          return a.text || "";
        })
        .filter(Boolean)
        .join("\n");

      wrap.innerHTML =
        "<h3 class=\"panel-heading\">" +
        escapeHtml(role.company || "Role") +
        "</h3>" +
        '<label><span>Company</span><input data-field="company" type="text" value="' +
        escapeHtml(role.company || "") +
        '" /></label>' +
        '<label><span>Title</span><input data-field="title" type="text" value="' +
        escapeHtml(role.title || "") +
        '" /></label>' +
        '<label><span>Start</span><input data-field="start" type="text" value="' +
        escapeHtml(role.start || "") +
        '" /></label>' +
        '<label><span>End</span><input data-field="end" type="text" value="' +
        escapeHtml(role.end || "") +
        '" placeholder="blank if current" /></label>' +
        '<label><span>Achievements (one per line)</span><textarea data-field="achievements" rows="6">' +
        escapeHtml(achText) +
        "</textarea></label>";
      rolesEditor.appendChild(wrap);
    });
  }

  function showProfile(profile) {
    currentProfile = profile;
    reviewPanel.hidden = false;
    revName.value = (profile.candidate && profile.candidate.preferred_name) || "";
    revHeadline.value = (profile.candidate && profile.candidate.headline) || "";
    revYears.value = (profile.candidate && profile.candidate.years_experience) || 0;
    renderConflicts(profile.conflicts || []);
    renderRoles(profile.roles || []);
  }

  function collectProfilePayload() {
    const roles = [];
    rolesEditor.querySelectorAll("[data-role-index]").forEach(function (wrap, ri) {
      const prior = (currentProfile && currentProfile.roles && currentProfile.roles[ri]) || {};
      const get = function (field) {
        const el = wrap.querySelector('[data-field="' + field + '"]');
        return el ? el.value : "";
      };
      const lines = String(get("achievements") || "")
        .split("\n")
        .map(function (l) {
          return l.trim();
        })
        .filter(Boolean);
      const priorAchs = prior.achievements || [];
      const achievements = lines.map(function (text, i) {
        const prev = priorAchs[i] || {};
        return {
          id: prev.id || null,
          text: text,
          status: "user_confirmed",
          evidence_source: prev.evidence_source || "user_review",
          confidence: prev.confidence != null ? prev.confidence : 1,
          technologies: prev.technologies || [],
        };
      });
      roles.push({
        id: prior.id || null,
        company: get("company"),
        title: get("title"),
        location: prior.location || null,
        start: get("start") || null,
        end: get("end") || null,
        is_current: !get("end"),
        tech: prior.tech || [],
        themes: prior.themes || [],
        achievements: achievements,
        core_facts: lines,
      });
    });
    return {
      candidate: {
        preferred_name: revName.value.trim(),
        headline: revHeadline.value.trim(),
        years_experience: Number(revYears.value) || 0,
        skills: (currentProfile && currentProfile.candidate && currentProfile.candidate.skills) || {},
      },
      roles: roles,
      inferred_profile: (currentProfile && currentProfile.inferred_profile) || [],
    };
  }

  function renderProgress(s) {
    if (!progressList) return;
    const llmOk = !!(s.llm_configured || s.allow_finish_without_llm);
    const steps = [
      {
        done: s.resume_count >= s.min_resumes,
        label:
          "Upload résumé (" +
          s.resume_count +
          "/" +
          s.min_resumes +
          ")" +
          (s.resume_count > 0 && pendingExtractReview ? " — review extracted text" : ""),
      },
      {
        done: s.job_sample_count >= s.min_job_samples,
        label: "Add job samples (" + s.job_sample_count + "/" + s.min_job_samples + ")",
      },
      {
        done: llmOk,
        label: s.llm_configured
          ? "OpenAI API key configured"
          : s.allow_finish_without_llm
            ? "LLM optional (dev mode — finish without OpenAI key)"
            : "OpenAI API key required (set OPENAI_API_KEY)",
      },
      {
        done: !!s.awaiting_review,
        label: s.awaiting_review
          ? "Draft ready — review & confirm"
          : "Generate draft profile",
      },
    ];
    progressList.innerHTML = steps
      .map(function (step) {
        return (
          "<li class=\"" +
          (step.done ? "done" : "todo") +
          "\">" +
          (step.done ? "✓ " : "○ ") +
          escapeHtml(step.label) +
          "</li>"
        );
      })
      .join("");
  }

  function updateFinishGate(s) {
    const reasons = [];
    if (s.resume_count < s.min_resumes) {
      reasons.push(
        "Upload at least " +
          s.min_resumes +
          " résumé" +
          (s.min_resumes === 1 ? "" : "s") +
          " (have " +
          s.resume_count +
          ").",
      );
    } else if (pendingExtractReview) {
      reasons.push("Review the extracted résumé text and confirm it looks correct.");
    }
    if (s.job_sample_count < s.min_job_samples) {
      reasons.push(
        "Add at least " +
          s.min_job_samples +
          " job sample" +
          (s.min_job_samples === 1 ? "" : "s") +
          " (have " +
          s.job_sample_count +
          ").",
      );
    }
    if (!s.llm_configured && !s.allow_finish_without_llm) {
      reasons.push(
        "An OpenAI API key is required. Set OPENAI_API_KEY in the server environment, then refresh.",
      );
    }
    const canFinish =
      s.resume_count >= s.min_resumes &&
      s.job_sample_count >= s.min_job_samples &&
      (s.llm_configured || s.allow_finish_without_llm) &&
      !pendingExtractReview;
    finishBtn.disabled = !canFinish;
    if (finishDisabledReason) {
      finishDisabledReason.textContent = canFinish
        ? ""
        : reasons.length
          ? "Cannot generate yet: " + reasons.join(" ")
          : "";
    }
    if (finishHelp) {
      finishHelp.textContent = canFinish
        ? "Ready — generate a draft profile for review."
        : "When counts below meet the minimum, generate a draft profile for review.";
    }
  }

  async function refreshStatus() {
    const res = await fetch("/api/onboarding/status");
    if (!res.ok) {
      statusLine.textContent = "Could not load onboarding status.";
      return;
    }
    const s = await res.json();
    if (!s.needs_onboarding) {
      statusLine.textContent = "Onboarding complete — redirecting…";
      window.location.href = "/jobs/today";
      return;
    }
    if (s.resume_count === 0) {
      pendingExtractReview = false;
      if (extractReview) extractReview.hidden = true;
    }
    const llm = s.llm_configured
      ? "LLM: configured"
      : s.allow_finish_without_llm
        ? "LLM: off — will save raw text only (dev mode)"
        : "LLM: off — OpenAI API key required (set OPENAI_API_KEY)";
    statusLine.textContent = `${llm} · Résumés: ${s.resume_count}/${s.min_resumes} · Job samples: ${s.job_sample_count}/${s.min_job_samples}`;
    resumeList.textContent = `Résumé uploads recorded: ${s.resume_count}`;
    jdCount.textContent = `Job samples recorded: ${s.job_sample_count}`;
    renderProgress(s);
    updateFinishGate(s);
    if (s.awaiting_review) {
      const pref = await fetch("/api/onboarding/profile");
      if (pref.ok) {
        const data = await pref.json();
        if (data.profile) showProfile(data.profile);
      }
    }
  }

  function showExtractPreview(preview, chars) {
    if (!extractReview || !extractPreview) return;
    extractPreview.textContent = preview || "(empty)";
    extractReview.hidden = false;
    pendingExtractReview = true;
    showBanner(
      "Extracted " +
        (chars != null ? chars + " characters. " : "") +
        "Review the text below before continuing.",
      "info",
    );
  }

  if (extractConfirmBtn) {
    extractConfirmBtn.addEventListener("click", async () => {
      pendingExtractReview = false;
      if (extractReview) extractReview.hidden = true;
      showBanner("Extracted text confirmed.", "success");
      await refreshStatus();
    });
  }

  resumeForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    showBanner("");
    const fd = new FormData(resumeForm);
    const file = fd.get("file");
    if (!(file instanceof File) || !file.size) {
      showBanner("Choose a file.", "error");
      return;
    }
    const up = new FormData();
    up.append("file", file);
    const res = await fetch("/api/onboarding/resume", { method: "POST", body: up });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showBanner(
        typeof data.detail === "string" ? data.detail : String(res.status),
        "error",
      );
      return;
    }
    resumeForm.reset();
    if (data.extracted_preview || data.needs_review) {
      showExtractPreview(data.extracted_preview, data.extracted_chars);
    } else {
      showBanner("Résumé saved.", "success");
      pendingExtractReview = false;
    }
    await refreshStatus();
  });

  jdForm.addEventListener("submit", async (e) => {
    e.preventDefault();
    showBanner("");
    const fd = new FormData(jdForm);
    const text = String(fd.get("text") || "").trim();
    const res = await fetch("/api/onboarding/job-sample", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ text }),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showBanner(
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail),
        "error",
      );
      return;
    }
    showBanner("Job sample saved.", "success");
    jdForm.reset();
    await refreshStatus();
  });

  finishBtn.addEventListener("click", async () => {
    finishMsg.hidden = true;
    const res = await fetch("/api/onboarding/finish", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      finishMsg.hidden = false;
      finishMsg.className = "status error";
      finishMsg.textContent =
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail);
      return;
    }
    finishMsg.hidden = false;
    finishMsg.className = "status success";
    finishMsg.textContent = data.message || "Draft ready — review below.";
    if (data.profile) {
      showProfile(data.profile);
    } else {
      await refreshStatus();
    }
  });

  saveReviewBtn.addEventListener("click", async () => {
    showReviewMsg("");
    const payload = collectProfilePayload();
    const res = await fetch("/api/onboarding/profile", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showReviewMsg(
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail),
        "error",
      );
      return;
    }
    showReviewMsg("Corrections saved.", "success");
    if (data.profile) showProfile(data.profile);
  });

  confirmBtn.addEventListener("click", async () => {
    showReviewMsg("");
    // Persist latest edits before unlock.
    const payload = collectProfilePayload();
    if (currentProfile && (currentProfile.roles || []).length) {
      const save = await fetch("/api/onboarding/profile", {
        method: "PUT",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify(payload),
      });
      if (!save.ok) {
        const data = await save.json().catch(() => ({}));
        showReviewMsg(
          typeof data.detail === "string" ? data.detail : "Could not save before confirm.",
          "error",
        );
        return;
      }
    }
    const res = await fetch("/api/onboarding/confirm", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      showReviewMsg(
        typeof data.detail === "string" ? data.detail : JSON.stringify(data.detail),
        "error",
      );
      return;
    }
    showReviewMsg(data.message || "Confirmed.", "success");
    window.location.href = "/jobs/today";
  });

  refreshStatus();
})();
