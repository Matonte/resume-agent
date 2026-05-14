(function () {
  const API = "/api/batch-schedule/";
  const form = document.getElementById("schedule-form");
  const ctxEl = document.getElementById("schedule-context");
  const runTimesEl = document.getElementById("run-times");
  const applyBtn = document.getElementById("apply-btn");
  const outEl = document.getElementById("apply-output");

  function hhmmFromTimeInput(name) {
    const el = form.elements.namedItem(name);
    if (!el || !el.value) return "";
    const v = el.value;
    return v.length === 5 ? v : v;
  }

  function setTimeInput(name, hhmm) {
    const el = form.elements.namedItem(name);
    if (!el || !hhmm) return;
    el.value = hhmm.length === 5 ? hhmm : hhmm.slice(0, 5);
  }

  function payloadFromForm() {
    return {
      window_start: hhmmFromTimeInput("window_start"),
      window_end: hhmmFromTimeInput("window_end"),
      interval_hours: Number(form.elements.namedItem("interval_hours").value),
      task_name: form.elements.namedItem("task_name").value.trim(),
      extra_args: form.elements.namedItem("extra_args").value.trim(),
      execution_time_limit_minutes: Number(
        form.elements.namedItem("execution_time_limit_minutes").value
      ),
    };
  }

  function fillForm(data) {
    setTimeInput("window_start", data.window_start);
    setTimeInput("window_end", data.window_end);
    form.elements.namedItem("interval_hours").value = data.interval_hours;
    form.elements.namedItem("task_name").value = data.task_name;
    form.elements.namedItem("extra_args").value = data.extra_args || "";
    form.elements.namedItem("execution_time_limit_minutes").value =
      data.execution_time_limit_minutes;
    runTimesEl.textContent = (data.run_times || []).join(", ");
  }

  function setContext(data) {
    const parts = [];
    if (!data.platform_is_windows) {
      parts.push(
        "Task Scheduler Apply is Windows-only. On Linux or cloud hosts use DAILY_RUN_WITH_SERVER=1 with uvicorn, or schedule python -m app.jobs.daily_run (cron, Kubernetes, etc.). Save to YAML still works everywhere."
      );
    } else if (!data.client_is_loopback) {
      parts.push(
        "Open this page on the machine at http://127.0.0.1:8000 (not via LAN hostname) to enable Apply."
      );
    } else if (!data.register_script_present) {
      parts.push("Missing scripts/register_scheduled_task.ps1 in the repo.");
    } else {
      parts.push("Apply will re-register the scheduled task using your saved YAML.");
    }
    ctxEl.textContent = parts.join(" ");
    applyBtn.disabled = !data.apply_available;
  }

  async function refresh() {
    const res = await fetch(API);
    if (!res.ok) {
      ctxEl.textContent = "Could not load schedule (" + res.status + ").";
      return;
    }
    const data = await res.json();
    fillForm(data);
    setContext(data);
  }

  form.addEventListener("submit", async (ev) => {
    ev.preventDefault();
    outEl.hidden = true;
    const body = payloadFromForm();
    const res = await fetch(API, {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(body),
    });
    const data = await res.json().catch(() => ({}));
    if (!res.ok) {
      alert(data.detail || "Save failed");
      return;
    }
    fillForm(data);
    const r2 = await fetch(API);
    if (r2.ok) setContext(await r2.json());
  });

  applyBtn.addEventListener("click", async () => {
    outEl.hidden = false;
    outEl.textContent = "Running register_scheduled_task.ps1…";
    const res = await fetch(API + "apply-windows-task", { method: "POST" });
    const data = await res.json().catch(() => ({}));
    const lines = [
      "HTTP " + res.status,
      "returncode: " + (data.returncode != null ? data.returncode : "—"),
      "--- stdout ---",
      data.stdout || "",
      "--- stderr ---",
      data.stderr || "",
    ];
    outEl.textContent = lines.join("\n");
    await refresh();
  });

  refresh();
})();
