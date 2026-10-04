/* Settings page: keep the reader status and raw read log fresh. */
(function () {
  'use strict';
  const SSB = window.SSB;

  function renderLog(rows) {
    const body = document.getElementById('raw-log');
    const lines = rows.length ? rows.map((row) => {
      const tr = document.createElement('tr');
      const time = document.createElement('td');
      time.textContent = row.time_label;
      const raw = document.createElement('td');
      raw.className = 'raw';
      raw.textContent = row.raw;
      tr.append(time, raw);
      return tr;
    }) : (() => {
      const tr = document.createElement('tr'), td = document.createElement('td');
      td.colSpan = 2; td.className = 'muted'; td.textContent = 'Nothing received yet. Hold a card to the reader.';
      tr.append(td); return [tr];
    })();
    body.replaceChildren(...lines);
  }

  async function refresh() {
    if (document.hidden) return;
    try {
      const response = await SSB.api('GET', '/api/reader');
      SSB.updateReaderChip(response.data.status);
      document.getElementById('reader-message').textContent = response.data.status.message;
      renderLog(response.data.raw);
      SSB.setConnection(true);
    } catch (e) { SSB.setConnection(false); }
  }
  document.addEventListener('DOMContentLoaded', () => setInterval(refresh, 2500));
})();
