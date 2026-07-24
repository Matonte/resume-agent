/* Shared helpers: load a queued job into tailor / interview-prep / review forms. */
(function (global) {
  function qs(name) {
    try {
      return new URLSearchParams(window.location.search).get(name);
    } catch (_) {
      return null;
    }
  }

  async function fetchJob(jobId) {
    const res = await fetch(`/api/jobs/${encodeURIComponent(jobId)}`);
    if (!res.ok) throw new Error(`job ${jobId}: HTTP ${res.status}`);
    return res.json();
  }

  function setValue(el, value) {
    if (!el || value == null || value === "") return;
    el.value = String(value);
  }

  /**
   * Prefill form fields from ?job_id= when present.
   * selectors: { description, title, company, url }
   */
  async function prefillFromJobQuery(selectors) {
    const jobId = qs("job_id");
    if (!jobId) return null;
    const data = await fetchJob(jobId);
    setValue(selectors.description, data.jd_full);
    setValue(selectors.title, data.title);
    setValue(selectors.company, data.company);
    setValue(selectors.url, data.url || data.apply_url);
    return data;
  }

  global.ResumeAgentJobContext = {
    qs,
    fetchJob,
    prefillFromJobQuery,
  };
})(window);
