/* API + utilidades de red */
const API = {
  async req(method, url, body) {
    const opts = {method, headers: {}};
    if (body !== undefined) {
      opts.headers['Content-Type'] = 'application/json';
      opts.body = JSON.stringify(body);
    }
    const r = await fetch(url, opts);
    let data = null;
    try { data = await r.json(); } catch (e) { data = null; }
    if (!r.ok) {
      const msg = (data && (data.error || data.message)) || ('Error ' + r.status);
      throw new Error(msg);
    }
    return data;
  },
  get(url) { return this.req('GET', url); },
  post(url, body) { return this.req('POST', url, body === undefined ? {} : body); },
  put(url, body) { return this.req('PUT', url, body); },
  del(url) { return this.req('DELETE', url); },
  list(table) { return this.get('/api/' + table); },
  create(table, data) { return this.post('/api/' + table, data); },
  update(table, id, data) { return this.put('/api/' + table + '/' + id, data); },
  remove(table, id) { return this.del('/api/' + table + '/' + id); },
  download(url, filename) {
    return fetch(url).then(r => {
      if (!r.ok) throw new Error('Error al descargar');
      return r.blob();
    }).then(b => {
      const a = document.createElement('a');
      a.href = URL.createObjectURL(b);
      a.download = filename;
      document.body.appendChild(a);
      a.click();
      a.remove();
      setTimeout(() => URL.revokeObjectURL(a.href), 4000);
    });
  }
};

function esc(s) {
  return String(s ?? '').replace(/[&<>"']/g, c => ({
    '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;'
  }[c]));
}
function fmtHours(n) { return n + ' h'; }
