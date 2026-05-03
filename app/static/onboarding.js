(function () {
  const statusLine = document.getElementById("status-line");
  const banner = document.getElementById("banner");
  const resumeForm = document.getElementById("resume-form");
  const jdForm = document.getElementById("jd-form");
  const resumeList = document.getElementById("resume-list");
  const jdCount = document.getElementById("jd-count");
  const finishBtn = document.getElementById("finish-btn");
  const finishMsg = document.getElementById("finish-msg");

  function showBanner(text, kind) {
    if (!text) {
      banner.hidden = true;
      return;
    }
    banner.hidden = false;
    banner.className = "status " + (kind || "info");
    banner.textContent = text;
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
    const llm = s.llm_configured
      ? "LLM: configured"
      : s.allow_finish_without_llm
        ? "LLM: off — will save raw text only (dev mode)"
        : "LLM: off — set OPENAI_API_KEY or ONBOARDING_ALLOW_FINISH_WITHOUT_LLM=1";
    statusLine.textContent = `${llm} · Résumés: ${s.resume_count}/${s.min_resumes} · Job samples: ${s.job_sample_count}/${s.min_job_samples}`;
    resumeList.textContent = `Résumé uploads recorded: ${s.resume_count}`;
    jdCount.textContent = `Job samples recorded: ${s.job_sample_count}`;
    finishBtn.disabled = !(
      s.resume_count >= s.min_resumes &&
      s.job_sample_count >= s.min_job_samples &&
      (s.llm_configured || s.allow_finish_without_llm)
    );
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
      showBanner(data.detail || String(res.status), "error");
      return;
    }
    showBanner("Résumé saved.", "success");
    resumeForm.reset();
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
    finishMsg.textContent = data.message || "Done.";
    window.location.href = "/jobs/today";
  });

  refreshStatus();
})();
