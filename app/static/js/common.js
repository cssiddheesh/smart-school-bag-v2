/* Shared helpers: API calls, toasts, confirmation dialog, reader chip. No dependencies. */
(function () {
  'use strict';
  const SSB = (window.SSB = window.SSB || {});
  const NS = 'http://www.w3.org/2000/svg';

  SSB.csrf = () => document.querySelector('meta[name="csrf-token"]').content;
  SSB.iconHref = () => (document.querySelector('use') || { getAttribute: () => '' }).getAttribute('href').split('#')[0];

  SSB.icon = function (name) {
    const svg = document.createElementNS(NS, 'svg');
    svg.setAttribute('class', 'icon');
    svg.setAttribute('aria-hidden', 'true');
    const use = document.createElementNS(NS, 'use');
    use.setAttribute('href', SSB.iconHref() + '#' + name);
    svg.append(use);
    return svg;
  };

  /** Call the JSON API. Resolves with the payload, rejects with {code, message, details}. */
  SSB.api = async function (method, url, body) {
    let response;
    try {
      response = await fetch(url, {
        method, credentials: 'same-origin',
        headers: { 'Accept': 'application/json', 'Content-Type': 'application/json', 'X-CSRF-Token': SSB.csrf() },
        body: body === undefined ? undefined : JSON.stringify(body),
      });
    } catch (e) {
      throw { code: 'network', message: 'Cannot reach the school bag. Check the connection.' };
    }
    let payload = null;
    try { payload = await response.json(); } catch (e) { /* not JSON */ }
    if (!response.ok || !payload || payload.success === false) {
      const error = (payload && payload.error) || {};
      throw {
        code: error.code || 'http_' + response.status,
        message: (payload && payload.message) || 'Something went wrong. Please try again.',
        details: error.details || {},
      };
    }
    return payload;
  };

  /* ---------- toasts ---------- */
  function dismissLater(node, level) {
    const ms = { success: 5000, info: 5000, warning: 7000, error: 10000 }[level] || 6000;
    setTimeout(() => node.remove(), ms);
  }
  function addCloseButton(node) {
    const close = document.createElement('button');
    close.type = 'button';
    close.setAttribute('aria-label', 'Dismiss message');
    close.textContent = '×';
    close.addEventListener('click', () => node.remove());
    node.append(close);
  }
  SSB.toast = function (message, level) {
    level = level || 'info';
    const box = document.getElementById('toasts');
    if (!box) return;
    const node = document.createElement('div');
    node.className = 'toast toast--' + level;
    const text = document.createElement('span');
    text.className = 'toast__text';
    text.textContent = message;
    node.append(text);
    addCloseButton(node);
    box.append(node);
    while (box.children.length > 4) box.firstElementChild.remove();
    dismissLater(node, level);
  };
  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-flash]').forEach((node) => {
      addCloseButton(node);
      dismissLater(node, node.classList.contains('toast--error') ? 'error' : 'success');
    });
  });

  /* ---------- confirmation dialog (replaces window.confirm) ---------- */
  SSB.confirm = function (message, confirmLabel, title) {
    const dialog = document.getElementById('confirm-dialog');
    if (!dialog || typeof dialog.showModal !== 'function') return Promise.resolve(window.confirm(message));
    document.getElementById('confirm-title').textContent = title || 'Are you sure?';
    document.getElementById('confirm-message').textContent = message;
    document.getElementById('confirm-ok').textContent = confirmLabel || 'Confirm';
    return new Promise((resolve) => {
      dialog.addEventListener('close', () => resolve(dialog.returnValue === 'ok'), { once: true });
      dialog.returnValue = '';
      dialog.showModal();
      document.getElementById('confirm-cancel').focus();
    });
  };

  document.addEventListener('submit', async (event) => {
    const form = event.target;
    if (!(form instanceof HTMLFormElement) || !form.dataset.confirm || form.dataset.confirmed) return;
    event.preventDefault();
    if (await SSB.confirm(form.dataset.confirm, form.dataset.confirmLabel)) {
      form.dataset.confirmed = '1';
      form.submit();
    }
  });

  /* ---------- reader chip (header + settings) ---------- */
  const READER = {
    connected: ['Connected', 'chip--ok', 'check-circle'], disabled: ['Not set up', '', 'minus-circle'],
    unavailable: ['Unavailable', 'chip--warn', 'alert'], disconnected: ['Disconnected', 'chip--warn', 'plug'],
    error: ['Error', 'chip--err', 'alert'],
  };
  SSB.updateReaderChip = function (reader) {
    const [label, cls, icon] = READER[reader.state] || ['Unknown', '', 'info'];
    document.querySelectorAll('[data-reader-chip]').forEach((chip) => {
      chip.className = ('chip ' + cls).trim();
      chip.title = reader.message || '';
      const text = document.createElement('span');
      const full = document.createElement('span');
      full.className = 'chip__full';
      full.textContent = 'RFID reader';
      const short = document.createElement('span');
      short.className = 'chip__short';
      short.textContent = 'Reader';
      text.append(full, short, ': ');
      const strong = document.createElement('strong');
      strong.textContent = label;
      text.append(strong);
      chip.replaceChildren(SSB.icon(icon), text);
    });
  };

  /* ---------- connection banner ---------- */
  SSB.setConnection = function (online) {
    const banner = document.getElementById('conn-banner');
    if (banner) banner.hidden = online;
  };
})();
