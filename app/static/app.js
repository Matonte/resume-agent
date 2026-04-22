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
  const useLlmEl = document.getElementById("use-llm");
  const llmStatusEl = document.getElementById("llm-status");
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

  function collectBody() {
    const fd = new FormData(form);
    return {
      description: (fd.get("description") || "").toString().trim(),
      question: (fd.get("question") || "").toString().trim() || null,
      title: (fd.get("title") || "").toString().trim() || null,
      company: (fd.get("company") || "").toString().trim() || null,
      archetype_override: (fd.get("archetype_override") || "").toString() || null,
      use_llm: !!useLlmEl.checked && !useLlmEl.disabled,
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
  }

  form.addEventListener("submit", onSubmit);
  downloadBtn.addEventListener("click", onDownload);
  loadArchetypes();
  loadLlmStatus();
})();
