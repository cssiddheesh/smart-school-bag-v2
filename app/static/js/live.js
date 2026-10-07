/* Live dashboard: renders from one state snapshot, refreshed by cheap revision polling. */
(function () {
  'use strict';
  const SSB = window.SSB;
  const $ = (selector) => document.querySelector(selector);
  const el = (tag, className, text) => {
    const node = document.createElement(tag);
    if (className) node.className = className;
    if (text !== undefined) node.textContent = text;
    return node;
  };
  const badge = (kind, text) => el('span', 'badge' + (kind ? ' badge--' + kind : ''), text);
  const live = (SSB.live = { state: null, rev: null, lastScanId: null, handlers: [] });
  live.onRender = (handler) => live.handlers.push(handler);

  /* ---------- optional browser speech (keeps voice working through the website tunnel) ---------- */
  const voice = { enabled: false };
  function voiceSupported() {
    return 'speechSynthesis' in window && 'SpeechSynthesisUtterance' in window;
  }
  function setVoiceControls() {
    const toggle = $('#voice-toggle');
    const status = $('#voice-status');
    const stop = $('#voice-stop');
    if (!toggle || !status) return;
    toggle.textContent = voice.enabled ? 'Mute voice' : 'Enable voice';
    toggle.setAttribute('aria-pressed', String(voice.enabled));
    status.textContent = voice.enabled ? 'Voice is on for this dashboard in this browser.' :
      'Voice is off. Enable it to hear updates on this device.';
    if (stop) stop.hidden = !voice.enabled;
  }
  function speak(text) {
    if (!voice.enabled || !text) return;
    const utterance = new SpeechSynthesisUtterance(text);
    utterance.rate = 0.95;
    window.speechSynthesis.cancel();
    window.speechSynthesis.speak(utterance);
  }
  function bookNames(items) {
    return items.length ? items.map((item) => item.name).join(', ') : '';
  }
  function packingSummary(state) {
    if (!state.checklist.length) return 'There are no books on the timetable for ' + (state.day ? state.day.name : 'today') + '.';
    const packed = state.checklist.filter((item) => item.present);
    const remaining = state.checklist.filter((item) => !item.present);
    let message = 'For ' + (state.day ? state.day.name : 'today') + ', ' + packed.length + ' of ' +
      state.checklist.length + ' required books are packed.';
    if (remaining.length) {
      message += state.session ? ' Still missing: ' : ' Not scanned yet: ';
      message += bookNames(remaining) + '.';
    } else if (state.session) {
      message += ' The bag is ready.';
    }
    if (state.extras.length) message += ' Scanned but not required today: ' + state.extras.join(', ') + '.';
    return message;
  }
  function scanAnnouncement(scan, state) {
    const name = scan.book_name || 'This card';
    if (scan.outcome === 'accepted') {
      const missing = state.checklist.filter((item) => !item.present);
      return name + ' packed. ' + (missing.length ? 'Still missing: ' + bookNames(missing) + '.' : 'The bag is ready.');
    }
    if (scan.outcome === 'duplicate') return name + ' has already been scanned.';
    if (scan.outcome === 'not_required') return name + ' is not required for ' + (state.day ? state.day.name : 'today') + '.';
    if (scan.outcome === 'unknown_card') return 'Unknown card. This card is not assigned to a book.';
    return scan.message + '.';
  }
  function announceState(state, previous, first) {
    if (!voice.enabled || first) return;
    const scan = state.last_scan;
    const newScan = scan && scan.id !== live.lastScanId;
    if (state.session && (!previous.session || state.session.id !== previous.session.id)) {
      speak('Packing started for ' + state.session.day_name + '. ' +
        (newScan ? scanAnnouncement(scan, state) : packingSummary(state)));
    } else if (newScan) {
      speak(scanAnnouncement(scan, state));
    }
  }

  /* ---------- rendering ---------- */
  function renderBand(state) {
    const band = $('#band');
    if (!band) return;
    ['idle', 'ready', 'not_ready', 'empty'].forEach((p) => band.classList.remove('band--' + p));
    band.classList.add('band--' + state.phase);
    const day = state.day ? state.day.name : 'No day selected';
    $('#band-day').textContent = state.student_name ? day + ' · ' + state.student_name : day;
    $('#band-status').textContent = state.status;
    const detail = {
      ready: 'Everything for ' + day + ' is in the bag.',
      not_ready: 'Still missing: ' + state.missing.join(', '),
      idle: 'Scan a book or press Start packing.',
      empty: day + ' has no books in the timetable.',
    }[state.phase];
    $('#band-detail').textContent = detail;
    $('#band-packed').textContent = state.packed_count;
    $('#band-required').textContent = state.required_count;
    $('#band-pct').textContent = state.percentage + '% packed';
    const segments = state.checklist.map((item) => el('li', 'seg' + (item.present ? ' on' : '')));
    $('#band-segments').replaceChildren(...segments);
  }

  function group(title, count, items) {
    const wrap = el('div', 'group');
    const heading = el('h3', '', title + ' ');
    heading.append(el('span', 'count', '(' + count + ')'));
    const list = el('ul', 'books');
    items.forEach((item) => list.append(item));
    wrap.append(heading, list);
    return wrap;
  }
  function bookItem(name, kind, iconName, label) {
    const item = el('li', kind ? 'is-' + kind : '');
    item.append(SSB.icon(iconName), el('span', 'name', name), badge({ present: 'ok', missing: 'warn', extra: 'extra' }[kind] || '', label));
    return item;
  }
  function renderChecklist(state) {
    const box = $('#checklist');
    if (!box) return;
    const parts = [];
    if (!state.checklist.length) {
      parts.push(el('p', 'muted', 'No books are required on this day. Add periods in the Timetable.'));
    } else if (state.phase === 'idle') {
      parts.push(group('To pack', state.checklist.length, state.checklist.map((b) => bookItem(b.name, '', 'book', 'NOT SCANNED'))));
    } else {
      const missing = state.checklist.filter((b) => !b.present);
      const present = state.checklist.filter((b) => b.present);
      if (missing.length) parts.push(group('Missing', missing.length, missing.map((b) => bookItem(b.name, 'missing', 'alert', 'MISSING'))));
      if (present.length) parts.push(group('Present', present.length, present.map((b) => bookItem(b.name, 'present', 'check-circle', 'PRESENT'))));
    }
    if (state.extras.length) {
      parts.push(group('Not required today', state.extras.length, state.extras.map((n) => bookItem(n, 'extra', 'info', 'EXTRA'))));
    }
    box.replaceChildren(...parts);
  }

  function sourceBadge(source) {
    const node = badge(source === 'SIMULATION' ? 'sim' : '', source === 'SIMULATION' ? 'Simulated' : 'Real card');
    node.prepend(SSB.icon(source === 'SIMULATION' ? 'monitor' : 'card'));
    return node;
  }
  function renderLastScan(state) {
    const box = $('#last-scan');
    if (!box) return;
    const scan = state.last_scan;
    if (!scan) {
      box.replaceChildren(el('p', 'muted', 'No card scanned yet. Hold a book’s card to the reader.'));
      return;
    }
    const wrap = el('div', 'scan scan--' + scan.level);
    const message = el('p', 'scan__msg');
    message.append(SSB.icon(scan.level === 'success' ? 'check-circle' : 'alert'), el('span', '', scan.message));
    const meta = el('div', 'row');
    meta.append(sourceBadge(scan.source), el('span', 'muted small', scan.time_label));
    wrap.append(message, meta);
    box.replaceChildren(wrap);
  }

  function fact(term, value) {
    const row = el('div');
    row.append(el('dt', '', term), el('dd', '', value));
    return row;
  }
  function renderSession(state) {
    const box = $('#session-info');
    if (!box) return;
    const parts = [];
    if (state.session) {
      const facts = el('dl', 'facts');
      facts.append(fact('Session', '#' + state.session.id), fact('Day', state.session.day_name), fact('Started', state.session.started_label));
      parts.push(facts);
      if (state.session.has_simulated) {
        const note = el('p', 'small');
        note.append(badge('sim', state.session.has_real ? 'Mixes real and simulated scans' : 'Simulated scans only'));
        parts.push(note);
      }
    } else {
      parts.push(el('p', 'muted', 'No session running.'));
      const last = state.last_session;
      if (last) {
        const link = el('a', '', 'Last session: ' + last.day_name + ', ' + (last.status === 'completed' ? 'completed ' : 'ended ') + last.time_label);
        link.href = '/sessions/' + last.id;
        const p = el('p', 'small');
        p.append(link);
        parts.push(p);
      }
    }
    box.replaceChildren(...parts);
  }

  function renderDay(state) {
    const select = $('#day-select');
    if (select) {
      const signature = JSON.stringify(state.days);
      if (select.dataset.signature !== signature) {
        select.replaceChildren(...state.days.map((d) => { const o = el('option', '', d.name); o.value = d.id; return o; }));
        select.dataset.signature = signature;
      }
      if (state.day) select.value = state.day.id;
    }
    const pills = $('#day-pills');
    if (pills) {
      if (pills.dataset.signature !== JSON.stringify(state.days)) {
        pills.replaceChildren(...state.days.map((d) => { const b = el('button', 'pill', d.name); b.type = 'button'; b.dataset.dayId = d.id; return b; }));
        pills.dataset.signature = JSON.stringify(state.days);
      }
      pills.querySelectorAll('.pill').forEach((b) => b.setAttribute('aria-pressed', String(state.day && Number(b.dataset.dayId) === state.day.id)));
    }
  }

  function renderActions(state) {
    const active = !!state.session;
    document.querySelectorAll('[data-action]').forEach((button) => {
      const action = button.dataset.action;
      if (action === 'start') { button.hidden = active; button.disabled = state.phase === 'empty'; }
      if (action === 'complete') {
        button.hidden = !active;
        button.disabled = !state.ready;
        button.title = state.ready ? '' : 'Scan the missing books first';
      }
      if (action === 'reset') button.hidden = !active && !('always' in button.dataset);
    });
  }

  function render(state) {
    SSB.updateReaderChip(state.reader);
    const demo = $('#chip-demo');
    if (demo) demo.hidden = !state.demo_enabled;
    renderBand(state); renderChecklist(state); renderLastScan(state); renderSession(state);
    renderDay(state); renderActions(state);
    document.title = state.status + ' · Smart School Bag';
    live.handlers.forEach((handler) => handler(state));
  }

  live.apply = function (state, options) {
    const first = live.state === null;
    const previous = live.state;
    live.state = state;
    live.rev = state.revision;
    render(state);
    const scan = state.last_scan;
    announceState(state, previous, first);
    if (scan && scan.id !== live.lastScanId) {
      if (!first && !(options && options.own)) SSB.toast(scan.message, scan.level === 'success' ? 'success' : 'warning');
      live.lastScanId = scan.id;
    }
  };

  /* ---------- actions ---------- */
  function showSummary(summary) {
    const dialog = $('#summary-dialog');
    if (!dialog || !summary) return;
    const facts = $('#summary-facts');
    const rows = [fact('Day', summary.day_name), fact('Books packed', summary.packed_count + ' of ' + summary.required_count),
      fact('Time taken', summary.duration_label), fact('Scans', summary.scan_count + (summary.duplicates ? ' (' + summary.duplicates + ' duplicate)' : ''))];
    if (summary.extras.length) rows.push(fact('Extra books', summary.extras.join(', ')));
    facts.replaceChildren(...rows);
    const note = $('#summary-note');
    note.hidden = !summary.has_simulated;
    note.textContent = summary.has_simulated ? 'This session includes simulated scans.' : '';
    $('#summary-link').href = '/sessions/' + summary.id;
    if (typeof dialog.showModal === 'function') { dialog.showModal(); $('#summary-close').focus(); }
  }

  async function runAction(action, button) {
    if (action === 'reset' && live.state.session) {
      const ok = await SSB.confirm('Scans so far stay in History, and you start again from zero.', 'Reset session', 'Reset this packing session?');
      if (!ok) return;
    }
    button.disabled = true;
    button.setAttribute('aria-busy', 'true');
    try {
      const response = await SSB.api('POST', '/api/session/' + action);
      live.apply(response.data.state, { own: true });
      SSB.toast(response.message, 'success');
      if (action === 'complete') {
        showSummary(response.data.summary);
        speak('Bag packed. Session complete. All ' + response.data.summary.required_count + ' required books are packed.');
      }
    } catch (error) {
      SSB.toast(error.message, 'error');
      poll(true);
    } finally {
      button.removeAttribute('aria-busy');
      renderActions(live.state);
    }
  }

  async function changeDay(dayId, confirmed) {
    try {
      const response = await SSB.api('POST', '/api/day', { day_id: dayId, confirm: !!confirmed });
      live.apply(response.data.state, { own: true });
    } catch (error) {
      if (error.code === 'session_in_progress') {
        const n = (error.details && error.details.scan_count) || 0;
        const ok = await SSB.confirm(error.message + ' ' + n + ' scan' + (n === 1 ? '' : 's') + ' so far will stay in History.', 'Switch day', 'Switch day?');
        if (ok) return changeDay(dayId, true);
      } else {
        SSB.toast(error.message, 'error');
      }
      renderDay(live.state);
    }
  }

  /* ---------- polling ---------- */
  let failures = 0, inflight = false;
  async function poll(force) {
    if (inflight || (document.hidden && !force)) return;
    inflight = true;
    try {
      const response = await SSB.api('GET', '/api/state' + (live.rev && !force ? '?rev=' + live.rev : ''));
      failures = 0;
      SSB.setConnection(true);
      if (response.data.changed) live.apply(response.data);
    } catch (error) {
      failures += 1;
      if (failures >= 2) SSB.setConnection(false);
    } finally {
      inflight = false;
    }
  }
  function schedule() {
    setTimeout(async () => { await poll(false); schedule(); }, failures > 2 ? 5000 : 1500);
  }

  document.addEventListener('DOMContentLoaded', () => {
    const initial = document.getElementById('initial-state');
    if (!initial) return;
    live.apply(JSON.parse(initial.textContent));
    setVoiceControls();
    const voiceToggle = $('#voice-toggle');
    if (voiceToggle) voiceToggle.addEventListener('click', () => {
      if (!voiceSupported()) {
        SSB.toast('Voice output is not supported by this browser.', 'warning');
        return;
      }
      voice.enabled = !voice.enabled;
      setVoiceControls();
      if (voice.enabled) speak(packingSummary(live.state));
      else window.speechSynthesis.cancel();
    });
    const voiceRepeat = $('#voice-repeat');
    if (voiceRepeat) voiceRepeat.addEventListener('click', () => {
      if (!voice.enabled) {
        SSB.toast('Enable voice before reading the packing status.', 'info');
        return;
      }
      speak(packingSummary(live.state));
    });
    const voiceStop = $('#voice-stop');
    if (voiceStop) voiceStop.addEventListener('click', () => window.speechSynthesis.cancel());
    document.addEventListener('click', (event) => {
      const button = event.target.closest('[data-action]');
      if (button) runAction(button.dataset.action, button);
      const pill = event.target.closest('.pill');
      if (pill) changeDay(Number(pill.dataset.dayId), false);
    });
    const select = $('#day-select');
    if (select) select.addEventListener('change', () => changeDay(Number(select.value), false));
    const close = $('#summary-close');
    if (close) close.addEventListener('click', () => $('#summary-dialog').close());
    document.addEventListener('visibilitychange', () => { if (!document.hidden) poll(true); });
    schedule();
  });
})();
