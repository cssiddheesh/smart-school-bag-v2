/* Exhibition mode: simulated cards through the real scan pipeline (labelled SIMULATION). */
(function () {
  'use strict';
  const SSB = window.SSB;
  const buttons = new Map();
  const busy = new Set();

  function status(state, name) {
    if (state.checklist.some((b) => b.name === name && b.present)) return ['ok', 'PACKED'];
    if (state.checklist.some((b) => b.name === name)) return ['warn', state.session ? 'NEEDED' : 'ON TIMETABLE'];
    if (state.extras.includes(name)) return ['extra', 'EXTRA'];
    return ['', 'NOT REQUIRED'];
  }

  function refresh(state) {
    buttons.forEach((node, name) => {
      const [kind, label] = status(state, name);
      node.querySelector('.badge').className = 'badge' + (kind ? ' badge--' + kind : '');
      node.querySelector('.badge').textContent = label;
    });
  }

  async function scan(payload, button) {
    const key = JSON.stringify(payload);
    if (busy.has(key)) return;
    busy.add(key);
    button.disabled = true;
    try {
      const response = await SSB.api('POST', '/api/demo/scan', payload);
      SSB.live.apply(response.data.state, { own: true });
      SSB.toast(response.message, response.data.scan.level === 'success' ? 'success' : 'warning');
      if (response.data.scan.became_ready) SSB.toast('All books are in the bag. Complete the session to see the summary.', 'success');
    } catch (error) {
      SSB.toast(error.message, 'error');
    } finally {
      busy.delete(key);
      button.disabled = false;
    }
  }

  document.addEventListener('DOMContentLoaded', () => {
    const box = document.getElementById('demo-books');
    const books = JSON.parse(document.getElementById('demo-book-list').textContent);
    if (!books.length) {
      const empty = document.createElement('p');
      empty.className = 'muted';
      empty.textContent = 'No enabled books. Add books first.';
      box.append(empty);
    }
    books.forEach((book) => {
      const node = document.createElement('button');
      node.type = 'button';
      node.className = 'demo-book';
      const name = document.createElement('span');
      name.textContent = book.name;
      const tag = document.createElement('span');
      tag.className = 'badge';
      node.append(SSB.icon('card'), name, tag);
      node.addEventListener('click', () => scan({ book_id: book.id }, node));
      buttons.set(book.name, node);
      box.append(node);
    });
    const unknown = document.getElementById('demo-unknown');
    unknown.addEventListener('click', () => scan({ unknown: true }, unknown));
    SSB.live.onRender(refresh);
    if (SSB.live.state) refresh(SSB.live.state);
  });
})();
