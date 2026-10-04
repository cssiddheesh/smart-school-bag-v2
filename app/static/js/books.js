/* "Scan card" on the Books page: wait for the next card from the real reader (or a simulated one). */
(function () {
  'use strict';
  const SSB = window.SSB;
  let timer = null, current = null;

  function stop(form, message) {
    clearInterval(timer);
    timer = null;
    current = null;
    document.querySelectorAll('[data-capture]').forEach((b) => { b.textContent = 'Scan card'; b.prepend(SSB.icon('card')); });
    document.querySelectorAll('[data-sim-card]').forEach((b) => { b.hidden = true; });
    if (form && message) form.querySelector('[data-capture-hint]').textContent = message;
  }

  async function start(form, button) {
    if (current) { await SSB.api('POST', '/api/capture/cancel').catch(() => {}); stop(current, 'Cancelled. Type the UID or try again.'); return; }
    try { await SSB.api('POST', '/api/capture/start'); } catch (e) { SSB.toast(e.message, 'error'); return; }
    current = form;
    button.textContent = 'Cancel';
    const sim = form.parentElement.querySelector('[data-sim-card]');
    if (sim) sim.hidden = false;
    form.querySelector('[data-capture-hint]').textContent = 'Waiting for a card… hold it to the reader (30 s).';
    timer = setInterval(async () => {
      try {
        const response = await SSB.api('GET', '/api/capture');
        if (response.data.uid) {
          form.querySelector('input[name="rfid_uid"]').value = response.data.uid;
          stop(form, 'Card read. Check the UID, then press Save card.');
          form.querySelector('button[type="submit"]').focus();
        } else if (!response.data.active) {
          stop(form, 'No card was read. Try again, or type the UID.');
        }
      } catch (e) { stop(form, e.message); }
    }, 1000);
  }

  document.addEventListener('DOMContentLoaded', () => {
    document.querySelectorAll('[data-uid-form]').forEach((form) => {
      const button = form.querySelector('[data-capture]');
      button.addEventListener('click', () => start(form, button));
    });
    document.querySelectorAll('[data-sim-card]').forEach((button) => {
      button.addEventListener('click', async () => {
        try { await SSB.api('POST', '/api/demo/new-card'); } catch (e) { SSB.toast(e.message, 'error'); }
      });
    });
  });
})();
