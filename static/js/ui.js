/* Componentes de interfaz: modales, toasts, formularios, tablas */

function toast(msg, type = '') {
  const t = document.createElement('div');
  t.className = 'toast ' + type;
  t.textContent = msg;
  document.getElementById('toasts').appendChild(t);
  setTimeout(() => { t.style.opacity = '0'; t.style.transition = '.4s'; }, 3200);
  setTimeout(() => t.remove(), 3700);
}

function openModal(html) {
  const bd = document.getElementById('modal-backdrop');
  document.getElementById('modal').innerHTML = html;
  bd.classList.remove('hidden');
  bd.onclick = e => { if (e.target === bd) closeModal(); };
  return document.getElementById('modal');
}
function closeModal() {
  document.getElementById('modal-backdrop').classList.add('hidden');
  document.getElementById('modal').innerHTML = '';
}

function confirmDialog(title, message, danger = true) {
  return new Promise(resolve => {
    const m = openModal(`
      <div class="modal-head"><h3>${esc(title)}</h3></div>
      <div class="modal-body"><p>${esc(message)}</p></div>
      <div class="modal-foot">
        <button class="btn" id="cf-no">Cancelar</button>
        <button class="btn ${danger ? 'btn-danger' : 'btn-primary'}" id="cf-yes">Aceptar</button>
      </div>`);
    m.querySelector('#cf-no').onclick = () => { closeModal(); resolve(false); };
    m.querySelector('#cf-yes').onclick = () => { closeModal(); resolve(true); };
  });
}

/* ---------------- formularios ---------------- */
const WEEK = ['Lunes', 'Martes', 'Miércoles', 'Jueves', 'Viernes', 'Sábado', 'Domingo'];

function defaultAvailability(start = '07:00', end = '13:00', days = WEEK.slice(0, 5)) {
  const a = {};
  WEEK.forEach(d => { a[d] = {on: days.includes(d), start, end}; });
  return a;
}

function fieldHtml(f, v) {
  const id = 'f_' + f.name;
  let inner = '';
  if (f.type === 'text' || f.type === 'number' || f.type === 'time' || f.type === 'color') {
    const t = f.type === 'color' ? 'color' : (f.type === 'number' ? 'number' : (f.type === 'time' ? 'time' : 'text'));
    inner = `<input id="${id}" type="${t}" value="${esc(v ?? '')}"
      ${f.type === 'number' && f.step ? `step="${f.step}"` : ''} ${f.required ? 'required' : ''}>`;
  } else if (f.type === 'textarea') {
    inner = `<textarea id="${id}" rows="3">${esc(v ?? '')}</textarea>`;
  } else if (f.type === 'select') {
    inner = `<select id="${id}">${(f.options || []).map(o =>
      `<option value="${esc(o.value)}" ${String(o.value) === String(v ?? '') ? 'selected' : ''}>${esc(o.label)}</option>`).join('')}</select>`;
  } else if (f.type === 'checkbox') {
    inner = `<label class="checks"><input type="checkbox" id="${id}" ${v ? 'checked' : ''}> ${esc(f.label)}</label>`;
  } else if (f.type === 'multiselect') {
    const sel = v || [];
    inner = `<div class="checks" id="${id}">${(f.options || []).map(o =>
      `<label><input type="checkbox" value="${esc(o.value)}" ${sel.map(String).includes(String(o.value)) ? 'checked' : ''}> ${esc(o.label)}</label>`).join('') || '<span class="hint">Sin opciones</span>'}</div>`;
  } else if (f.type === 'days') {
    const sel = v || [];
    inner = `<div class="checks" id="${id}">${WEEK.map(d =>
      `<label><input type="checkbox" value="${d}" ${sel.includes(d) ? 'checked' : ''}> ${d}</label>`).join('')}</div>`;
  } else if (f.type === 'availability') {
    inner = availabilityHtml(id, v);
  }
  const labelTag = f.type === 'checkbox' ? '' : `<label for="${id}">${esc(f.label)}${f.required ? ' *' : ''}</label>`;
  return `<div class="field" ${f.full ? 'style="grid-column:1/-1"' : ''}>
    ${labelTag}${inner}${f.hint ? `<span class="hint">${esc(f.hint)}</span>` : ''}</div>`;
}

function availabilityHtml(id, v) {
  const av = v || defaultAvailability();
  let rows = WEEK.map(d => {
    const x = av[d] || {on: false, start: '07:00', end: '13:00'};
    return `<tr class="${x.on ? '' : 'avail-off'}" data-day="${d}">
      <td class="day"><label style="display:flex;gap:6px;align-items:center;cursor:pointer">
        <input type="checkbox" class="av-on" ${x.on ? 'checked' : ''}> ${d}</label></td>
      <td><input type="time" class="av-s" value="${x.start}" ${x.on ? '' : 'disabled'}></td>
      <td><input type="time" class="av-e" value="${x.end}" ${x.on ? '' : 'disabled'}></td>
    </tr>`;
  }).join('');
  return `<div id="${id}" data-kind="availability"><table class="avail-table">
    <tr><th>Día</th><th>Desde</th><th>Hasta</th></tr>${rows}</tr></table>
    <span class="hint">Día desmarcado = profesor/aula no disponible ese día.</span></div>`;
}

function readField(f) {
  const id = 'f_' + f.name;
  const el = document.getElementById(id);
  if (!el) return undefined;
  if (f.type === 'number') return el.value === '' ? null : parseInt(el.value, 10);
  if (f.type === 'checkbox') return el.checked;
  if (f.type === 'multiselect') {
    return Array.from(el.querySelectorAll('input:checked')).map(i =>
      isNaN(+i.value) ? i.value : +i.value);
  }
  if (f.type === 'days') {
    return Array.from(el.querySelectorAll('input:checked')).map(i => i.value);
  }
  if (f.type === 'availability') {
    const out = {};
    el.querySelectorAll('tr[data-day]').forEach(tr => {
      out[tr.dataset.day] = {
        on: tr.querySelector('.av-on').checked,
        start: tr.querySelector('.av-s').value || '07:00',
        end: tr.querySelector('.av-e').value || '13:00'
      };
    });
    return out;
  }
  if (f.type === 'text' && f.trim === false) return el.value;
  return el.value;
}

function bindAvailability(root) {
  root.querySelectorAll('tr[data-day]').forEach(tr => {
    const on = tr.querySelector('.av-on');
    on.addEventListener('change', () => {
      tr.classList.toggle('avail-off', !on.checked);
      tr.querySelectorAll('.av-s,.av-e').forEach(i => i.disabled = !on.checked);
    });
  });
}

function formFieldsHtml(fields, values) {
  return `<div class="form-grid ${fields.length === 1 ? 'one' : ''}">` +
    fields.map(f => fieldHtml(f, values ? values[f.name] : f.default)).join('') + '</div>';
}

function readForm(fields) {
  const out = {};
  fields.forEach(f => {
    const v = readField(f);
    if (v !== undefined) out[f.name] = v;
  });
  return out;
}

function openFormModal({title, fields, values, submitLabel = 'Guardar', onSubmit}) {
  const m = openModal(`
    <div class="modal-head"><h3>${esc(title)}</h3>
      <button class="btn-icon" id="fm-x">✕</button></div>
    <div class="modal-body">${formFieldsHtml(fields, values)}</div>
    <div class="modal-foot">
      <button class="btn" id="fm-cancel">Cancelar</button>
      <button class="btn btn-primary" id="fm-ok">${esc(submitLabel)}</button>
    </div>`);
  bindAvailability(m);
  m.querySelector('#fm-x').onclick = closeModal;
  m.querySelector('#fm-cancel').onclick = closeModal;
  m.querySelector('#fm-ok').onclick = async () => {
    const data = readForm(fields);
    for (const f of fields) {
      if (f.required) {
        const v = data[f.name];
        if (v === '' || v === null || v === undefined) {
          toast('El campo "' + f.label + '" es obligatorio', 'bad');
          return;
        }
      }
    }
    try {
      await onSubmit(data);
      closeModal();
    } catch (e) {
      toast(e.message, 'bad');
    }
  };
}

/* ---------------- tabla ---------------- */
function renderTable(container, {columns, rows, onEdit, onDelete, empty = 'Sin registros', rowActions = true}) {
  if (!rows.length) {
    container.innerHTML = `<div class="empty"><div class="big">∅</div>${esc(empty)}</div>`;
    return;
  }
  const head = columns.map(c => `<th>${esc(c.label)}</th>`).join('');
  const acts = rowActions ? '<th class="acts"></th>' : '';
  const body = rows.map(r => {
    const tds = columns.map(c => `<td>${c.render ? c.render(r) : esc(r[c.key] ?? '')}</td>`).join('');
    const a = rowActions ? `<td class="acts">
      ${onEdit ? `<button class="btn btn-sm" data-edit="${r.id}">Editar</button>` : ''}
      ${onDelete ? `<button class="btn btn-sm btn-danger" data-del="${r.id}">Eliminar</button>` : ''}
    </td>` : '';
    return `<tr data-id="${r.id}">${tds}${a}</tr>`;
  }).join('');
  container.innerHTML = `<div class="table-wrap"><table class="tbl">
    <thead><tr>${head}${acts}</tr></thead><tbody>${body}</tbody></table></div>`;
  if (onEdit) container.querySelectorAll('[data-edit]').forEach(b =>
    b.onclick = () => onEdit(rows.find(r => String(r.id) === b.dataset.edit)));
  if (onDelete) container.querySelectorAll('[data-del]').forEach(b =>
    b.onclick = async () => {
      const row = rows.find(r => String(r.id) === b.dataset.del);
      if (await confirmDialog('Eliminar', '¿Eliminar "' + (row.name || row.label || 'registro') + '"?')) {
        try { await onDelete(row); } catch (e) { toast(e.message, 'bad'); }
      }
    });
}

function setView(html) {
  document.getElementById('view').innerHTML = html;
}
function loadingView(msg = 'Cargando…') {
  setView(`<div class="loading"><span class="spinner"></span><div style="margin-top:10px">${esc(msg)}</div></div>`);
}
