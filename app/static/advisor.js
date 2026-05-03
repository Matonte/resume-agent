(function () {
  const form = document.getElementById('advisor-form');
  const statusEl = document.getElementById('status');
  const resultPanel = document.getElementById('result-panel');
  const resultJson = document.getElementById('result-json');
  const downloadHint = document.getElementById('download-hint');
  const downloadBtn = document.getElementById('download-json');
  const advisorNote = document.getElementById('advisor-note');
  const advisorVisual = document.getElementById('advisor-visual');
  let lastPayload = null;

  function pickTacticalAdvice(advisorPayload) {
    if (!advisorPayload || typeof advisorPayload !== 'object') return null;
    const a = advisorPayload.advice;
    if (!a || typeof a !== 'object' || Array.isArray(a)) return null;
    if (typeof a.opening_move === 'string' || Array.isArray(a.do)) return a;
    if (a.advice && typeof a.advice === 'object' && !Array.isArray(a.advice)) {
      return a.advice;
    }
    return null;
  }

  function appendList(parent, label, items) {
    if (!items || !items.length) return;
    const wrap = document.createElement('div');
    wrap.className = 'advisor-list-block';
    const strong = document.createElement('strong');
    strong.textContent = label;
    wrap.appendChild(strong);
    const ul = document.createElement('ul');
    for (const raw of items) {
      const s = String(raw || '').trim();
      if (!s) continue;
      const li = document.createElement('li');
      li.textContent = s;
      ul.appendChild(li);
    }
    if (!ul.children.length) return;
    wrap.appendChild(ul);
    parent.appendChild(wrap);
  }

  function renderTacticalSection(tactical, heading) {
    const tacticalInner = typeof tactical === 'object' && tactical ? tactical : null;
    if (!tacticalInner) return null;

    const opening = String(tacticalInner.opening_move || '').trim();
    const obs = String(tacticalInner.key_observations || '').trim();
    const esc = String(tacticalInner.escalation_plan || '').trim();
    const doList = Array.isArray(tacticalInner.do) ? tacticalInner.do : [];
    const dontList = Array.isArray(tacticalInner.dont) ? tacticalInner.dont : [];
    const watch = Array.isArray(tacticalInner.watchpoints) ? tacticalInner.watchpoints : [];

    if (!opening && !obs && !doList.length && !dontList.length && !watch.length && !esc) {
      return null;
    }

    const sec = document.createElement('section');
    sec.className = 'advisor-tactics';

    if (heading) {
      const h = document.createElement('h3');
      h.textContent = heading;
      sec.appendChild(h);
    }

    if (opening) {
      const op = document.createElement('p');
      op.className = 'advisor-opening';
      op.textContent = opening;
      sec.appendChild(op);
    }
    if (obs) {
      const p = document.createElement('p');
      p.className = 'body';
      p.textContent = obs;
      sec.appendChild(p);
    }
    appendList(sec, 'Do', doList);
    appendList(sec, "Don't", dontList);
    appendList(
      sec,
      'Watchpoints',
      watch.map((w) => (w == null ? '' : `Watch for: ${w}`)),
    );
    if (esc) {
      const p = document.createElement('p');
      p.className = 'body';
      p.textContent = 'If it goes sideways: ' + esc;
      sec.appendChild(p);
    }
    return sec;
  }

  function renderServiceErrors(blob) {
    if (!blob || typeof blob !== 'object') return null;
    const parts = [];
    const ke = blob.k_error;
    const he = blob.hoss_error;
    if (ke) parts.push('K / WhoIsWhat: ' + String(ke));
    if (he) parts.push('HOSS: ' + String(he));
    if (!parts.length) return null;
    const div = document.createElement('div');
    div.className = 'advisor-errors';
    div.textContent = parts.join(' — ');
    return div;
  }

  function renderStakeBlock(title, notes) {
    if (!notes || typeof notes !== 'object') return null;
    const summary = String(notes.summary || '').trim();
    const how = Array.isArray(notes.how_to_talk) ? notes.how_to_talk : [];
    const avoid = Array.isArray(notes.what_to_avoid) ? notes.what_to_avoid : [];
    if (!summary && !how.length && !avoid.length) return null;

    const block = document.createElement('div');
    block.className = 'stake-block';
    const h4 = document.createElement('h4');
    h4.textContent = title;
    block.appendChild(h4);
    if (summary) {
      const p = document.createElement('p');
      p.className = 'body';
      p.textContent = summary;
      block.appendChild(p);
    }
    appendList(block, 'How to talk', how);
    appendList(block, 'Avoid', avoid);
    return block;
  }

  function renderPersonCard(person, index) {
    const card = document.createElement('article');
    card.className = 'advisor-person-card';

    const header = document.createElement('header');
    const h = document.createElement('h3');
    const title = String(person.title || '').trim() || 'Contact ' + (index + 1);
    h.textContent = title;
    header.appendChild(h);

    const role = String(person.inferred_primary_role || '').trim();
    if (role) {
      const meta = document.createElement('p');
      meta.className = 'person-meta';
      meta.textContent = 'Inferred role: ' + role;
      header.appendChild(meta);
    }
    card.appendChild(header);

    const sn = String(person.snippet || '').trim();
    if (sn) {
      const pre = document.createElement('p');
      pre.className = 'person-snippet';
      pre.textContent = sn;
      card.appendChild(pre);
    }

    const combined = String(person.combined_opening || '').trim();
    if (combined) {
      const op = document.createElement('p');
      op.className = 'advisor-opening';
      op.textContent = combined;
      card.appendChild(op);
    }

    const rec = renderStakeBlock('Recruiter angle', person.recruiter);
    if (rec) card.appendChild(rec);
    const hm = renderStakeBlock('Hiring manager angle', person.hiring_manager);
    if (hm) card.appendChild(hm);

    const raw = person.whoiswhat_raw;
    const ma = raw && typeof raw === 'object' ? raw.meeting_advisor : null;
    const tact = renderTacticalSection(pickTacticalAdvice(ma || {}), 'Raw tactic block');
    if (tact) card.appendChild(tact);
    const err = renderServiceErrors(ma || {});
    if (err) card.appendChild(err);

    return card;
  }

  function renderReport(data) {
    while (advisorVisual.firstChild) advisorVisual.removeChild(advisorVisual.firstChild);

    const note = (data.meeting_advisor_note || '').trim();
    if (note) {
      advisorNote.textContent = note;
      advisorNote.hidden = false;
    } else {
      advisorNote.hidden = true;
    }

    const people = Array.isArray(data.people) ? data.people : [];
    let anyBlock = false;

    if (people.length) {
      people.forEach((p, i) => {
        const card = renderPersonCard(p, i);
        if (card.querySelector('.advisor-tactics, .advisor-opening, .stake-block')) {
          anyBlock = true;
        }
        advisorVisual.appendChild(card);
      });
    } else if (data.advice) {
      const blob = data.advice;
      const err = renderServiceErrors(blob);
      if (err) advisorVisual.appendChild(err);
      const tact = renderTacticalSection(pickTacticalAdvice(blob), 'Tactics');
      if (tact) {
        advisorVisual.appendChild(tact);
        anyBlock = true;
      } else if (!err) {
        const p = document.createElement('p');
        p.className = 'body';
        p.textContent =
          'Advisor returned a response without a structured tactics block. Expand Raw JSON for detail.';
        advisorVisual.appendChild(p);
        anyBlock = true;
      }
    } else if (!data.configured) {
      const p = document.createElement('p');
      p.className = 'body';
      p.textContent = data.meeting_advisor_note || 'Advisor not configured.';
      advisorVisual.appendChild(p);
      anyBlock = true;
    }

    if (!anyBlock && people.length && !note) {
      const p = document.createElement('p');
      p.className = 'body';
      p.textContent = 'No displayable tactics for extracted contacts. See Raw JSON.';
      advisorVisual.appendChild(p);
    }
  }

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
          'Health: meeting advisor API URL not set — set MEETING_ADVISOR_URL in .env to run advice.';
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
        : data.meeting_advisor_note || 'Advisor not configured.';
      resultJson.textContent = JSON.stringify(data, null, 2);
      renderReport(data);
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
