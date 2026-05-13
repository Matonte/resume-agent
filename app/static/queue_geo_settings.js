/** Geographic restrictions on Today's queue — same API as /job-search-geography. */
(function () {
  const API = "/api/job-search-geography/";
  const form = document.getElementById("queue-geo-form");
  if (!form) return;

  const noteEl = document.getElementById("queue-geo-note");
  const defaultGeoLabel = document.getElementById("queue-default-geo-label");
  const effectiveGeo = document.getElementById("queue-effective-geo");

  async function refresh() {
    const res = await fetch(API);
    if (!res.ok) {
      if (noteEl) noteEl.textContent = "Could not load geography settings (" + res.status + ").";
      return;
    }
    const data = await res.json();
    form.elements.namedItem("locations").value = (data.locations || []).join("\n");
    form.elements.namedItem("remote_ok").checked = !!data.remote_ok;
    form.elements.namedItem("linkedin_geo_id").value = data.linkedin_geo_id || "";
    if (defaultGeoLabel) defaultGeoLabel.textContent = data.linkedin_default_geo_id || "103644278";
    if (effectiveGeo) effectiveGeo.textContent = data.linkedin_effective_geo_id || "—";
    if (noteEl) noteEl.textContent = data.save_note || "";
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    const locText = form.elements.namedItem("locations").value || "";
    const locations = locText
      .split("\n")
      .map((s) => s.trim())
      .filter(Boolean);
    const body = {
      locations,
      remote_ok: form.elements.namedItem("remote_ok").checked,
      linkedin_geo_id: (form.elements.namedItem("linkedin_geo_id").value || "").trim(),
    };
    const res = await fetch(API, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      const d = data.detail;
      alert(typeof d === "string" ? d : JSON.stringify(d));
      return;
    }
    form.elements.namedItem("locations").value = (data.locations || []).join("\n");
    form.elements.namedItem("remote_ok").checked = !!data.remote_ok;
    form.elements.namedItem("linkedin_geo_id").value = data.linkedin_geo_id || "";
    if (effectiveGeo) effectiveGeo.textContent = data.linkedin_effective_geo_id || "—";
    if (noteEl) noteEl.textContent = "Saved — next daily run uses these filters.";
  });

  refresh();
})();
