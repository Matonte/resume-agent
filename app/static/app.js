(function () {
  const form = document.getElementById("draft-form");
  const statusEl = document.getElementById("status");
  const resultsEl = document.getElementById("results");
  const archetypePill = document.getElementById("archetype-pill");
  const scoreFill = document.getElementById("score-fill");
  const scoreText = document.getElementById("score-text");
  const reasonsEl = document.getElementById("reasons");
  const summaryEl = document.getElementById("summary");
  const bulletsEl = document.getElementById("bullets");
  const notesEl = document.getElementById("notes");
  const answerCard = document.getElementById("answer-card");
  const answerEl = document.getElementById("answer");
  const storiesLabel = document.getElementById("stories-label");
  const archetypeSelect = document.getElementById("archetype-select");
  const goBtn = document.getElementById("go");
  const downloadBtn = document.getElementById("download-btn");
  const downloadAdvisorBtn = document.getElementById("download-advisor-btn");
  const useLlmEl = document.getElementById("use-llm");
  const llmStatusEl = document.getElementById("llm-status");
  const meetingAdvisorEl = document.getElementById("meeting-advisor");
  const advisorStatusEl = document.getElementById("advisor-status");
  const fitScoreEl = document.getElementById("fit-score");
  const fitBandEl = document.getElementById("fit-band");
  const fitFillEl = document.getElementById("fit-fill");
  const fitReasonsEl = document.getElementById("fit-reasons");

  let lastDraft = null;

  async function loadArchetypes() {
    try {
      const res = await fetch("/api/archetypes");
      if (!res.ok) return;
      const data = await res.json();
      Object.values(data).forEach((a) => {
        const opt = document.createElement("option");
        opt.value = a.id;
        opt.textContent = `${a.id} — ${a.name}`;
        archetypeSelect.appendChild(opt);
      });
    } catch (err) {
      console.warn("Failed to load archetypes", err);
    }
  }

  async function loadLlmStatus() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) return;
      const h = await res.json();
      const configured = !!h?.loaded_files?.llm_configured;
      if (configured) {
        llmStatusEl.textContent = " — mirrors JD language while preserving truth-model facts.";
        useLlmEl.checked = true;
      } else {
        useLlmEl.checked = false;
        useLlmEl.disabled = true;
        llmStatusEl.textContent = " — no OPENAI_API_KEY set in .env (deterministic only).";
      }
    } catch (err) {
      llmStatusEl.textContent = " — status unavailable.";
    }
  }

  function setList(el, items) {
    el.innerHTML = "";
    (items || []).forEach((item) => {
      const li = document.createElement("li");
      li.textContent = item;
      el.appendChild(li);
    });
  }

  function escapeHtml(s) {
    const d = document.createElement("div");
    d.textContent = s == null ? "" : String(s);
    return d.innerHTML;
  }

  function renderMeetingAdviceHtml(raw) {
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

  function renderMeetingAdvice(data) {
    const wrap = document.getElementById("resume-meeting-advisor");
    const noteEl = document.getElementById("resume-meeting-advisor-note");
    const bodyEl = document.getElementById("resume-meeting-advice-body");
    if (!wrap || !noteEl || !bodyEl) return;

    const note = data.meeting_advisor_note;
    if (note) {
      noteEl.textContent = note;
      noteEl.hidden = false;
    } else {
      noteEl.textContent = "";
      noteEl.hidden = true;
    }

    const raw = data.meeting_advice;
    if (!raw) {
      bodyEl.innerHTML = "";
      if (note) {
        wrap.classList.remove("hidden");
      } else {
        wrap.classList.add("hidden");
      }
      return;
    }
    wrap.classList.remove("hidden");
    bodyEl.innerHTML = renderMeetingAdviceHtml(raw);
  }

  function collectBody() {
    const fd = new FormData(form);
    return {
      description: (fd.get("description") || "").toString().trim(),
      question: (fd.get("question") || "").toString().trim() || null,
      title: (fd.get("title") || "").toString().trim() || null,
      company: (fd.get("company") || "").toString().trim() || null,
      archetype_override: (fd.get("archetype_override") || "").toString() || null,
      use_llm: !!useLlmEl.checked && !useLlmEl.disabled,
      meeting_advisor: !!meetingAdvisorEl.checked,
      advisor_subject_name:
        (fd.get("advisor_subject_name") || "").toString().trim() || null,
    };
  }

  async function onSubmit(ev) {
    ev.preventDefault();
    const body = collectBody();
    if (!body.description) {
      statusEl.textContent = "Paste a job description first.";
      return;
    }

    goBtn.disabled = true;
    downloadBtn.disabled = true;
    downloadAdvisorBtn.disabled = true;
    statusEl.textContent = "Generating...";

    try {
      const res = await fetch("/api/full-draft", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`HTTP ${res.status}: ${errText}`);
      }
      const data = await res.json();
      lastDraft = { body, data };
      render(data);
      downloadBtn.disabled = false;
      downloadAdvisorBtn.disabled = !data.meeting_advice;
      statusEl.textContent = "Done.";
    } catch (err) {
      statusEl.textContent = `Error: ${err.message}`;
    } finally {
      goBtn.disabled = false;
    }
  }

  async function onDownload() {
    if (!lastDraft) return;
    const { body, data } = lastDraft;
    downloadBtn.disabled = true;
    statusEl.textContent = "Building .docx...";
    try {
      const res = await fetch("/api/generate-resume", {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({
          description: body.description,
          archetype_override: body.archetype_override || data.classification.archetype_id,
          target_company: body.company,
          target_title: body.title,
          use_llm: body.use_llm,
        }),
      });
      if (!res.ok) {
        const errText = await res.text();
        throw new Error(`HTTP ${res.status}: ${errText}`);
      }
      const cd = res.headers.get("content-disposition") || "";
      const match = /filename="?([^"]+)"?/i.exec(cd);
      const filename = match ? match[1] : "resume.docx";
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      statusEl.textContent = `Downloaded ${filename}.`;
    } catch (err) {
      statusEl.textContent = `Download failed: ${err.message}`;
    } finally {
      downloadBtn.disabled = false;
    }
  }

  function _safeFilenamePart(s) {
    return String(s || "job")
      .replace(/[^A-Za-z0-9._-]+/g, "_")
      .slice(0, 48);
  }

  function onDownloadAdvisor() {
    if (!lastDraft?.data?.meeting_advice) return;
    downloadAdvisorBtn.disabled = true;
    statusEl.textContent = "Downloading advisor JSON…";
    try {
      const blob = new Blob([JSON.stringify(lastDraft.data.meeting_advice, null, 2)], {
        type: "application/json",
      });
      const url = URL.createObjectURL(blob);
      const a = document.createElement("a");
      a.href = url;
      const co = _safeFilenamePart(lastDraft.body.company);
      const tag = new Date().toISOString().slice(0, 10);
      const fname = `meeting_advice_${co}_${tag}.json`;
      a.download = fname;
      document.body.appendChild(a);
      a.click();
      a.remove();
      URL.revokeObjectURL(url);
      statusEl.textContent = `Downloaded ${fname}.`;
    } catch (err) {
      statusEl.textContent = `Download failed: ${err.message}`;
    } finally {
      downloadAdvisorBtn.disabled = false;
    }
  }

  function render(data) {
    resultsEl.classList.remove("hidden");

    const fit = data.fit;
    fitScoreEl.textContent = fit.score.toFixed(1);
    fitBandEl.textContent = fit.band;
    fitFillEl.style.width = Math.round((fit.score / 10) * 100) + "%";
    setList(fitReasonsEl, fit.reasons);

    const c = data.classification;
    archetypePill.textContent = c.archetype_id;
    const pct = Math.round((c.score || 0) * 100);
    scoreFill.style.width = pct + "%";
    scoreText.textContent = `confidence ${pct}%`;
    setList(reasonsEl, c.reasons);

    const r = data.resume;
    summaryEl.textContent = r.summary;
    setList(bulletsEl, r.selected_bullets);
    setList(notesEl, r.notes);
    // Mark summary card with an LLM badge when the rewrite actually ran.
    const summaryCard = summaryEl.closest("article");
    if (summaryCard) {
      const existing = summaryCard.querySelector(".llm-badge");
      if (existing) existing.remove();
      if (r.llm_applied) {
        const heading = summaryCard.querySelector("h2");
        const badge = document.createElement("span");
        badge.className = "llm-badge";
        badge.textContent = "LLM polished";
        heading?.appendChild(badge);
      }
    }

    if (data.answer) {
      answerCard.classList.remove("hidden");
      answerEl.textContent = data.answer.answer;
      const ids = data.answer.supporting_story_ids || [];
      storiesLabel.textContent = ids.length
        ? "Supporting stories: " + ids.join(", ")
        : "No specific story linked.";
    } else {
      answerCard.classList.add("hidden");
    }

    renderMeetingAdvice(data);
  }

  async function loadAdvisorStatus() {
    try {
      const res = await fetch("/api/health");
      if (!res.ok) {
        advisorStatusEl.textContent = " — health check failed; toggle still works.";
        return;
      }
      const h = await res.json();
      const ma = !!h?.loaded_files?.meeting_advisor_configured;
      if (ma) {
        meetingAdvisorEl.checked = true;
        advisorStatusEl.textContent =
          " — outreach / conversation prep (POSTs to MEETING_ADVISOR_URL).";
      } else {
        advisorStatusEl.textContent =
          " — MEETING_ADVISOR_URL not loaded; add to .env + restart, or toggle anyway to see errors.";
      }
    } catch (err) {
      advisorStatusEl.textContent = " — status unavailable; toggle still works.";
    }
  }

  form.addEventListener("submit", onSubmit);
  downloadBtn.addEventListener("click", onDownload);
  downloadAdvisorBtn.addEventListener("click", onDownloadAdvisor);
  loadArchetypes();
  loadLlmStatus();
  loadAdvisorStatus();
})();
