/* Manual tailor page controller.
 *
 * Posts the form to /api/manual-tailor and renders the returned artifact
 * download links. Errors (network, validation, LLM crash) are shown in the
 * inline status banner so the user doesn't have to open DevTools to
 * figure out what went wrong.
 */

const form = document.getElementById("tailor-form");
const submitBtn = document.getElementById("submit-btn");
const statusEl = document.getElementById("status");
const resultPanel = document.getElementById("result-panel");

function escapeHtml(s) {
  const d = document.createElement("div");
  d.textContent = s == null ? "" : String(s);
  return d.innerHTML;
}

function renderMeetingAdviceBlock(raw) {
  if (!raw || typeof raw !== "object") return "";
  const a = raw.advice && typeof raw.advice === "object" ? raw.advice : {};
  const chunks = [];
  if (a.opening_move) {
    chunks.push(`<p><strong>Opening move</strong><br>${escapeHtml(a.opening_move)}</p>`);
  }
  if (a.key_observations) {
    chunks.push(`<p><strong>Observations</strong><br>${escapeHtml(a.key_observations)}</p>`);
  }
  const doList = Array.isArray(a.do) ? a.do : [];
  if (doList.length) {
    chunks.push(
      `<p><strong>Do</strong></p><ul>${doList.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`,
    );
  }
  const dontList = Array.isArray(a.dont) ? a.dont : [];
  if (dontList.length) {
    chunks.push(
      `<p><strong>Don't</strong></p><ul>${dontList.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`,
    );
  }
  const watch = Array.isArray(a.watchpoints) ? a.watchpoints : [];
  if (watch.length) {
    chunks.push(
      `<p><strong>Watchpoints</strong></p><ul>${watch.map((x) => `<li>${escapeHtml(x)}</li>`).join("")}</ul>`,
    );
  }
  if (a.escalation_plan) {
    chunks.push(`<p><strong>If it goes sideways</strong><br>${escapeHtml(a.escalation_plan)}</p>`);
  }
  return chunks.length ? chunks.join("") : `<pre class="muted">${escapeHtml(JSON.stringify(raw, null, 2))}</pre>`;
}

async function loadMeetingAdvisorHint() {
  const hint = document.getElementById("advisor-hint");
  const cb = document.getElementById("meeting-advisor");
  if (!hint || !cb) return;
  try {
    const res = await fetch("/api/health");
    if (!res.ok) {
      hint.textContent = "(health check failed — you can still toggle Meeting advisor)";
      return;
    }
    const h = await res.json();
    const ok = !!h?.loaded_files?.meeting_advisor_configured;
    if (ok) {
      hint.textContent = "(ready)";
      cb.checked = true;
    } else {
      hint.textContent = "(not configured — resume package still works)";
    }
  } catch (_) {
    hint.textContent = "(status unavailable)";
  }
}

function setStatus(text, variant = "info") {
  if (!text) {
    statusEl.hidden = true;
    statusEl.textContent = "";
    return;
  }
  statusEl.hidden = false;
  statusEl.className = `status ${variant}`;
  statusEl.textContent = text;
}

function showResult(data) {
  resultPanel.hidden = false;
  document.getElementById("result-title").textContent = data.title || "Untitled";
  document.getElementById("result-company").textContent = data.company || "Unknown";
  document.getElementById("result-archetype").textContent = data.archetype_id || "-";
  document.getElementById("result-fit").textContent =
    data.fit_score != null ? Number(data.fit_score).toFixed(1) + " / 10" : "-";
  document.getElementById("result-location").textContent = data.location || "-";
  document.getElementById("result-summary").textContent = data.summary || "";

  const urls = data.artifact_urls || {};
  document.getElementById("dl-resume").href = urls.resume || "#";
  document.getElementById("dl-cover").href = urls.cover_letter || "#";
  document.getElementById("dl-screening").href = urls.screening || "#";
  document.getElementById("dl-metadata").href = urls.metadata || "#";
  document.getElementById("open-dashboard").href = data.dashboard_url || "/jobs/today";

  const wrap = document.getElementById("meeting-advice-wrap");
  const noteEl = document.getElementById("meeting-advisor-note");
  const bodyEl = document.getElementById("meeting-advice-body");
  if (wrap && noteEl && bodyEl) {
    const note = data.meeting_advisor_note;
    const adv = data.meeting_advice;
    const people = Array.isArray(data.meeting_advisor_people) ? data.meeting_advisor_people : [];
    if (note) {
      noteEl.textContent = note;
      noteEl.hidden = false;
    } else {
      noteEl.textContent = "";
      noteEl.hidden = true;
    }
    if (people.length) {
      wrap.hidden = false;
      bodyEl.innerHTML = people
        .map((p, i) => {
          const title = p.title || `Contact ${i + 1}`;
          const name = String(title).split("—")[0].trim() || `Contact ${i + 1}`;
          const raw =
            p.whoiswhat_raw && typeof p.whoiswhat_raw === "object"
              ? p.whoiswhat_raw.meeting_advisor
              : null;
          const block = renderMeetingAdviceBlock(raw || p);
          return `<article class="meeting-person-block"><h4 class="meeting-person-name">${escapeHtml(name)}</h4>${block}</article>`;
        })
        .join("");
    } else if (adv) {
      wrap.hidden = false;
      bodyEl.innerHTML = renderMeetingAdviceBlock(adv);
    } else {
      wrap.hidden = false;
      bodyEl.innerHTML = note
        ? ""
        : '<p class="muted">No interview talking points for this run. Turn on <strong>Interview talking points</strong> above when the prep service is available.</p>';
    }
  }

  const prepLink = document.getElementById("open-interview-prep");
  if (prepLink && data.job_id) {
    prepLink.href = `/meeting-advisor?job_id=${encodeURIComponent(data.job_id)}`;
  }
}

form.addEventListener("submit", async (evt) => {
  evt.preventDefault();

  const url = document.getElementById("url").value.trim();
  const description = document.getElementById("description").value.trim();
  if (!url && description.length < 100) {
    setStatus(
      "Provide a URL or paste at least 100 characters of job description.",
      "error",
    );
    return;
  }

  submitBtn.disabled = true;
  submitBtn.textContent = "Tailoring…";
  setStatus(
    "Working — matching the role, drafting resume bullets, cover letter, and application answers. Usually 15–60s.",
    "info",
  );

  const payload = {
    url: url || null,
    description: description || null,
    company: document.getElementById("company").value.trim() || null,
    title: document.getElementById("title").value.trim() || null,
    location: document.getElementById("location").value.trim() || null,
    use_llm: document.getElementById("use-llm").checked,
    meeting_advisor: document.getElementById("meeting-advisor").checked,
    advisor_subject_name: document.getElementById("advisor-subject").value.trim() || null,
  };

  try {
    const resp = await fetch("/api/manual-tailor", {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(payload),
    });
    const data = await resp.json().catch(() => ({}));
    if (!resp.ok) {
      const detail = data.detail || `HTTP ${resp.status}`;
      setStatus(`Tailor failed: ${detail}`, "error");
      return;
    }
    if (data.warning) {
      setStatus(`Tailored, with a caveat: ${data.warning}`, "warn");
    } else {
      setStatus("Tailored successfully.", "success");
    }
    showResult(data);
  } catch (err) {
    setStatus(`Network error: ${err}`, "error");
  } finally {
    submitBtn.disabled = false;
    submitBtn.textContent = "Generate apply package";
  }
});

loadMeetingAdvisorHint();
if (window.ResumeAgentJobContext) {
  ResumeAgentJobContext.prefillFromJobQuery({
    description: document.getElementById("description"),
    title: document.getElementById("title"),
    company: document.getElementById("company"),
    url: document.getElementById("url"),
  }).catch((err) => {
    setStatus(`Could not load job context: ${err.message}`, "error");
  });
}
