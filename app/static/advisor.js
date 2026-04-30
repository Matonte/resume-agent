(function () {
  const form = document.getElementById('advisor-form');
  const statusEl = document.getElementById('status');
  const resultPanel = document.getElementById('result-panel');
  const resultJson = document.getElementById('result-json');
  const downloadHint = document.getElementById('download-hint');
  const downloadBtn = document.getElementById('download-json');
  let lastPayload = null;

  async function checkHealth() {
    try {
      const res = await fetch('/api/health');
      if (!res.ok) return;
      const h = await res.json();
      const ok = !!h?.loaded_files?.meeting_advisor_configured;
      const sub = document.querySelector('.subtitle');
      if (sub && !ok) {
        sub.appendChild(document.createElement('br'));
        const em = document.createElement('em');
        em.textContent =
          'Health: meeting advisor not configured — set MEETING_ADVISOR_URL in .env.';
        sub.appendChild(em);
      }
    } catch (_) {}
  }

  form.addEventListener('submit', async (ev) => {
    ev.preventDefault();
    statusEl.hidden = false;
    statusEl.textContent = 'Running…';
    resultPanel.hidden = true;

    const description = document.getElementById('description').value.trim();
    const body = {
      description,
      company: document.getElementById('company').value.trim(),
      title: document.getElementById('title').value.trim(),
      listing_url: document.getElementById('listing_url').value.trim(),
      subject_name: document.getElementById('subject_name').value.trim(),
      extract_people: document.getElementById('extract-people').checked,
      use_llm: document.getElementById('use-llm').checked,
    };

    try {
      const res = await fetch('/api/meeting-advisor', {
        method: 'POST',
        headers: { 'Content-Type': 'application/json' },
        body: JSON.stringify(body),
      });
      const data = await res.json().catch(() => ({}));
      if (!res.ok) {
        statusEl.textContent = data.detail
          ? JSON.stringify(data.detail)
          : `Error ${res.status}`;
        return;
      }
      lastPayload = data;
      statusEl.textContent = data.configured
        ? 'Done.'
        : (data.meeting_advisor_note || 'Advisor not configured.');
      resultJson.textContent = JSON.stringify(data, null, 2);
      resultPanel.hidden = false;
      downloadHint.hidden = !data.configured;
    } catch (e) {
      statusEl.textContent = String(e);
    }
  });

  downloadBtn.addEventListener('click', () => {
    if (!lastPayload) return;
    const blob = new Blob([JSON.stringify(lastPayload, null, 2)], {
      type: 'application/json',
    });
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'meeting_advisor_result.json';
    a.click();
    URL.revokeObjectURL(a.href);
  });

  checkHealth();
})();
