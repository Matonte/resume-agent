(async function () {
  const listEl = document.getElementById('jobs-list');
  const runEl = document.getElementById('summary-run');
  const countEl = document.getElementById('summary-count');
  const approvedEl = document.getElementById('summary-approved');
  const submittedEl = document.getElementById('summary-submitted');

  function fitClass(score) {
    if (score === null || score === undefined) return 'fit-low';
    if (score >= 7.5) return 'fit-high';
    if (score >= 5.0) return 'fit-med';
    return 'fit-low';
  }

  function fmtFit(score) {
    if (score === null || score === undefined) return '-';
    return score.toFixed(1) + '/10';
  }

  function artifactHref(id, file) {
    return `/api/jobs/${encodeURIComponent(id)}/artifact?file=${encodeURIComponent(file)}`;
  }

  function renderJob(job, fullDetail) {
    const detail = fullDetail || {};
    const screening = detail.screening || [];
    const jd = detail.jd_full || '';

    const screeningHtml = screening.length
      ? screening
          .map(
            (s) =>
              `<details><summary>${escape(s.question || '(question)')}</summary>` +
              `<p class="screening-answer">${escape(s.answer || '')}</p>` +
              `<p class="screening-source">source: ${escape(s.source || 'template')}</p></details>`,
          )
          .join('')
      : '<em class="screening-empty">No screening questions extracted.</em>';

    const outreach = detail.outreach || null;
    const contacts = detail.outreach_contacts || [];
    let outreachBlock = '';
    if (outreach && outreach.contact_count) {
      const roles = (outreach.roles || []).join(', ');
      const lines = contacts.length
        ? contacts
            .slice(0, 3)
            .map((c) => {
              const op = (c.combined_opening || '').slice(0, 160);
              return `<li><strong>${escape(c.title || '')}</strong> — ${escape(op)}</li>`;
            })
            .join('')
        : '';
      outreachBlock = `
      <div class="job-outreach">
        <strong>Recruiter / HM outreach</strong>
        <p class="outreach-meta">${escape(String(outreach.contact_count))} contact(s)${roles ? ' · ' + escape(roles) : ''}</p>
        <p><a href="${artifactHref(job.id, 'outreach_contacts.json')}">outreach_contacts.json</a></p>
        ${lines ? `<ul class="outreach-list">${lines}</ul>` : ''}
      </div>`;
    }

    const status = job.status || 'new';
    const applyHref = job.apply_url || job.url;
    const listingHref = job.url;
    const showListingLink =
      job.apply_url && job.url && String(job.apply_url) !== String(job.url);
    const card = document.createElement('div');
    card.className = 'job-card';
    card.dataset.status = status;
    card.id = 'job-' + job.id;

    card.innerHTML = `
      <div class="job-head">
        <div>
          <p class="job-title">${escape(job.title)}</p>
          <p class="job-company">${escape(job.company)} · <span class="pill">${escape(
            job.source,
          )}</span> · <span class="pill">${escape(job.archetype_id || '-')}</span></p>
        </div>
        <div>
          <span class="pill fit-pill ${fitClass(job.fit_score)}">${fmtFit(job.fit_score)}</span>
        </div>
      </div>
      <div class="job-meta">
        <span>${escape(job.location || '-')}</span>
        <span>${escape(job.salary_raw || '')}</span>
        <span>status: <strong>${escape(status)}</strong></span>
        ${
          job.outreach && job.outreach.contact_count
            ? `<span class="pill outreach-pill">${escape(String(job.outreach.contact_count))} outreach</span>`
            : ''
        }
      </div>
      <div class="job-actions">
        <a href="${escape(applyHref)}" target="_blank" rel="noopener">Open apply link</a>
        ${
          showListingLink
            ? `<a href="${escape(listingHref)}" target="_blank" rel="noopener">Board listing</a>`
            : ''
        }
        <a href="${artifactHref(job.id, 'resume.docx')}">Resume.docx</a>
        <a href="${artifactHref(job.id, 'cover_letter.docx')}">Cover.docx</a>
        <a href="${artifactHref(job.id, 'screening.json')}">Screening.json</a>
        <button class="primary"   data-action="approve"        ${status === 'approved' || status === 'submitted' ? 'disabled' : ''}>Approve</button>
        <button class="secondary" data-action="prepare-apply"  ${status !== 'approved' ? 'disabled' : ''}>Open &amp; prefill</button>
        <button class="secondary" data-action="mark-submitted" ${status === 'submitted' ? 'disabled' : ''}>I submitted it</button>
        <button class="danger"    data-action="skip"           ${status === 'skipped' || status === 'submitted' ? 'disabled' : ''}>Skip</button>
      </div>
      <div class="job-screening">
        <strong>Screening drafts</strong>
        <div>${screeningHtml}</div>
      </div>
      ${outreachBlock}
      <details>
        <summary>Full JD</summary>
        <div class="jd-preview">${escape(jd).slice(0, 4000)}</div>
      </details>
    `;

    card.querySelectorAll('button[data-action]').forEach((btn) => {
      btn.addEventListener('click', () => act(job.id, btn.dataset.action));
    });

    return card;
  }

  function escape(s) {
    return String(s == null ? '' : s)
      .replace(/&/g, '&amp;')
      .replace(/</g, '&lt;')
      .replace(/>/g, '&gt;')
      .replace(/"/g, '&quot;');
  }

  async function fetchJob(id) {
    const res = await fetch(`/api/jobs/${encodeURIComponent(id)}`);
    if (!res.ok) return {};
    return res.json();
  }

  async function act(id, action) {
    let url = `/api/jobs/${encodeURIComponent(id)}/${action}`;
    const res = await fetch(url, { method: 'POST' });
    if (!res.ok) {
      const err = await res.text();
      alert(`Action failed: ${res.status}\n${err}`);
      return;
    }
    await load();
  }

  async function load() {
    const res = await fetch('/api/jobs/today');
    if (!res.ok) {
      listEl.innerHTML = `<div class="empty-state">Failed to load: ${res.status}</div>`;
      return;
    }
    const payload = await res.json();
    runEl.textContent = payload.run_id || '-';
    const jobs = payload.jobs || [];
    countEl.textContent = jobs.length;
    approvedEl.textContent = jobs.filter((j) => j.status === 'approved').length;
    submittedEl.textContent = jobs.filter((j) => j.status === 'submitted').length;

    if (jobs.length === 0) {
      listEl.innerHTML = '<div class="empty-state">No jobs surfaced today.</div>';
      return;
    }
    listEl.innerHTML = '';
    for (const job of jobs) {
      const detail = await fetchJob(job.id);
      listEl.appendChild(renderJob(job, detail));
    }
  }

  await load();
})();
