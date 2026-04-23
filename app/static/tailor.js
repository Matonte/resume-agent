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
    "Working — classifying, drafting bullets, writing the cover letter, and answering screening questions. Usually 15-60s.",
    "info",
  );

  const payload = {
    url: url || null,
    description: description || null,
    company: document.getElementById("company").value.trim() || null,
    title: document.getElementById("title").value.trim() || null,
    location: document.getElementById("location").value.trim() || null,
    use_llm: document.getElementById("use-llm").checked,
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
    submitBtn.textContent = "Generate tailored package";
  }
});
