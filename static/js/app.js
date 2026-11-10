/* Router + secciones de la aplicación */
'use strict';

const state = {
  meta: null, school: null, schedules: [],
  viewer: {scheduleId: null, type: 'curso', id: null},
  lastResult: null, validation: null
};

const TITLES = {
  inicio: 'Inicio', colegio: 'Colegio', grados: 'Grados y cursos',
  profesores: 'Profesores', asignaturas: 'Asignaturas', aulas: 'Aulas',
  jornadas: 'Horarios / Jornadas', bloques: 'Configuración de bloques',
  reglas: 'Reglas', generar: 'Generar horario', horarios: 'Horarios generados',
  validacion: 'Validación del horario', exportar: 'Exportar', config: 'Configuración'
};

/* ============================== utilidades ============================== */
function opts(list, labelFn) {
  return list.map(x => ({value: x.id, label: labelFn(x)}));
}
function courseLabel(c) { return `${c.grade_name} ${c.name}`; }
async function getMeta() {
  if (!state.meta) state.meta = await API.get('/api/meta');
  return state.meta;
}
async function getSchool() {
  state.school = await API.get('/api/school');
  const name = state.school.name || 'Colegio';
  document.getElementById('brand-school').textContent = name;
  document.getElementById('school-pill').textContent = name;
  return state.school;
}
function levelBadge(level) {
  const cls = level === 'Primaria' ? 'info' : (level === 'Secundaria' ? 'warn' : 'mut');
  return `<span class="badge ${cls}">${esc(level)}</span>`;
}
function roomTypeBadge(rt) {
  if (!rt) return '<span class="badge mut">Salón normal</span>';
  const labels = {sistemas: 'Sala de Sistemas', laboratorio: 'Laboratorio', cancha: 'Cancha', taller: 'Taller'};
  return `<span class="badge warn">${esc(labels[rt] || rt)}</span>`;
}
function availSummary(av) {
  if (!av) return '<span class="muted">—</span>';
  const on = WEEK.filter(d => av[d] && av[d].on);
  if (!on.length) return '<span class="badge bad">Sin disponibilidad</span>';
  const s = on.map(d => av[d].start).sort()[0];
  const e = on.map(d => av[d].end).sort().pop();
  const off = WEEK.filter(d => !av[d] || !av[d].on);
  return `<span class="mono">${s}–${e}</span>` +
    (off.length ? ` <span class="badge mut" title="No disponible: ${off.join(', ')}">falta: ${off.slice(0,2).join(', ')}${off.length>2?'…':''}</span>` : '');
}

/* ============================== router ============================== */
const ROUTES = {};

window.addEventListener('hashchange', () => route());
window.addEventListener('DOMContentLoaded', async () => {
  document.getElementById('menu-toggle').onclick = () =>
    document.getElementById('sidebar').classList.toggle('open');
  document.getElementById('quick-generate').onclick = () => { location.hash = '#/generar'; };
  document.querySelectorAll('.nav a').forEach(a => a.addEventListener('click', () =>
    document.getElementById('sidebar').classList.remove('open')));
  await route();
});

async function route() {
  const hash = (location.hash || '#/inicio').replace(/^#\//, '');
  const name = hash.split('/')[0] || 'inicio';
  const fn = ROUTES[name] || ROUTES.inicio;
  document.querySelectorAll('.nav a').forEach(a =>
    a.classList.toggle('active', a.dataset.route === name));
  document.getElementById('page-title').textContent = TITLES[name] || 'Inicio';
  try {
    await getMeta();
    await fn();
  } catch (e) {
    console.error(e);
    setView(`<div class="card"><div class="empty"><div class="big">⚠</div>
      No se pudo cargar la sección: ${esc(e.message)}</div></div>`);
  }
}
function refresh() { return route(); }

/* ============================== 1. Inicio ============================== */
ROUTES.inicio = async () => {
  const [school, schedules] = await Promise.all([getSchool(), API.get('/api/schedules')]);
  state.schedules = schedules;
  const c = school.counts;
  const last = schedules[0];
  const okCount = schedules.filter(s => s.status === 'ok').length;
  setView(`
    <div class="grid c4" style="margin-bottom:18px">
      <div class="stat"><div class="v">${c.courses}</div><div class="l">Cursos</div></div>
      <div class="stat"><div class="v">${c.teachers}</div><div class="l">Profesores</div></div>
      <div class="stat"><div class="v">${c.subjects}</div><div class="l">Asignaturas</div></div>
      <div class="stat"><div class="v">${c.classrooms}</div><div class="l">Aulas</div></div>
    </div>
    <div class="grid c2">
      <div class="card">
        <h2>Estado del colegio</h2>
        <div class="sub">${esc(school.name)} — ${esc(school.description || 'Sin descripción')}</div>
        <table class="tbl"><tbody>
          <tr><td>Niveles</td><td><b>${c.levels}</b></td><td>Grados</td><td><b>${c.grades}</b></td></tr>
          <tr><td>Cursos</td><td><b>${c.courses}</b></td><td>Asignaciones profesor–asignatura–curso</td><td><b>${c.assignments}</b></td></tr>
          <tr><td>Horarios generados</td><td><b>${schedules.length}</b></td><td>Válidos</td><td><b>${okCount}</b></td></tr>
        </tbody></table>
        <div style="margin-top:14px;display:flex;gap:8px;flex-wrap:wrap">
          <a class="btn btn-primary" href="#/generar">⚡ Generar horario</a>
          <a class="btn" href="#/profesores">Profesores y asignaciones</a>
          <a class="btn" href="#/validacion">Validar horario</a>
        </div>
      </div>
      <div class="card">
        <h2>Último horario</h2>
        ${last ? `
          <p><span class="badge ${last.status === 'ok' ? 'ok' : 'bad'}">${last.status === 'ok' ? 'VÁLIDO' : 'FALLIDO'}</span>
             &nbsp;<b>${esc(last.name)}</b><br>
             <span class="kv">${esc(last.created_at)} · ${last.entries} bloques</span></p>
          ${last.status === 'ok' ? `<a class="btn btn-primary" href="#/horarios">Ver horarios generados</a>`
            : `<a class="btn" href="#/generar">Ver causas del fallo</a>`}`
          : `<div class="empty"><div class="big">▦</div>Todavía no se ha generado ningún horario.<br><br>
             <a class="btn btn-primary" href="#/generar">Generar el primero</a></div>`}
        <hr style="border:none;border-top:1px solid var(--line);margin:16px 0">
        <h3>Pasos recomendados</h3>
        <ol style="padding-left:18px;color:var(--muted);font-size:13px;line-height:1.9">
          <li>Configure niveles, grados y cursos.</li>
          <li>Registre profesores, asignaturas y aulas.</li>
          <li>Indique qué profesor da qué asignatura a qué curso.</li>
          <li>Ajuste bloques dobles y reglas.</li>
          <li>Genere y valide el horario.</li>
        </ol>
      </div>
    </div>`);
};

/* ============================== 2. Colegio ============================== */
ROUTES.colegio = async () => {
  const school = await getSchool();
  setView(`
    <div class="card">
      <h2>Datos del colegio</h2>
      <div class="sub">Nombre y descripción que aparecerán en los horarios exportados.</div>
      <div class="form-grid">
        <div class="field"><label>Nombre</label><input id="sc-name" value="${esc(school.name)}"></div>
        <div class="field"><label>Descripción</label><input id="sc-desc" value="${esc(school.description || '')}"></div>
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary" id="sc-save">Guardar cambios</button></div>
    </div>
    <div class="card">
      <h2>Descanso del colegio</h2>
      <div class="sub">Una sola pausa a media mañana para TODO el colegio: alumnos de Primaria, de Secundaria
        y maestros. Nadie dicta clase en ese rato y se refleja en todos los horarios.</div>
      <div class="form-grid">
        <div class="field"><label>Inicio del descanso</label><input id="sc-break-s" type="time" value="${esc(school.break_start || '10:00')}"></div>
        <div class="field"><label>Fin del descanso</label><input id="sc-break-e" type="time" value="${esc(school.break_end || '10:30')}"></div>
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary" id="sc-break-save">Guardar descanso</button></div>
    </div>
    <div class="card">
      <h2>Resumen</h2>
      <div class="grid c4">
        ${['levels|Niveles', 'grades|Grados', 'courses|Cursos', 'teachers|Profesores',
           'subjects|Asignaturas', 'classrooms|Aulas', 'assignments|Asignaciones']
          .map(x => {const [k, l] = x.split('|');
            return `<div class="stat"><div class="v">${school.counts[k]}</div><div class="l">${l}</div></div>`;}).join('')}
      </div>
    </div>
    <div class="info-box">Los <b>niveles</b> (Primaria, Secundaria, …) definen la jornada por defecto de sus cursos.
      Puede crearlos, editarlos y eliminarlos en <a href="#/grados"><b>Grados y cursos</b></a> y
      configurar su horario en <a href="#/jornadas"><b>Horarios / Jornadas</b></a>.</div>`);
  document.getElementById('sc-save').onclick = async () => {
    await API.put('/api/school', {
      name: document.getElementById('sc-name').value,
      description: document.getElementById('sc-desc').value
    });
    toast('Colegio actualizado', 'ok');
    getSchool();
  };
  document.getElementById('sc-break-save').onclick = async () => {
    const s = document.getElementById('sc-break-s').value;
    const e = document.getElementById('sc-break-e').value;
    if (!s || !e || s >= e) { toast('El descanso debe ser un rato válido (inicio < fin)', 'bad'); return; }
    await API.put('/api/school', {break_start: s, break_end: e});
    toast(`Descanso guardado: ${s}–${e}. Generará horarios con esa pausa`, 'ok');
    getSchool();
  };
};

/* ============================== 3. Grados y cursos ============================== */
const LEVEL_FIELDS = [
  {name: 'name', label: 'Nombre del nivel', type: 'text', required: true, hint: 'Ej.: Primaria, Secundaria'},
  {name: 'entry_time', label: 'Entrada', type: 'time', required: true, default: '07:00'},
  {name: 'exit_time', label: 'Salida', type: 'time', required: true, default: '12:30'},
  {name: 'blocks_per_day', label: 'Bloques por día', type: 'number', required: true, default: 5},
  {name: 'block_minutes', label: 'Minutos por bloque', type: 'number', required: true, default: 60},
  {name: 'days', label: 'Días de la semana', type: 'days', required: true, default: WEEK.slice(0, 5)}
];

ROUTES.grados = async () => {
  const [levels, grades, courses] = await Promise.all([
    API.list('levels'), API.list('grades'), API.list('courses')]);
  const norm = (await API.list('classrooms')).filter(r => r.kind === 'normal');
  const roomOpts = [{value: '', label: '— automático —'}].concat(opts(norm, r => r.name));

  const tree = levels.map(lv => {
    const lgrades = grades.filter(g => g.level_id === lv.id);
    return `<div class="tree-level">
      <div class="tree-head">
        <span>${esc(lv.name)}</span>
        <span class="badge mut">${lv.blocks_per_day} bloques · ${lv.entry_time}–${lv.exit_time}</span>
        <span class="spacer"></span>
        <button class="btn btn-sm" data-add-grade="${lv.id}">+ Grado</button>
        <button class="btn btn-sm" data-edit-level="${lv.id}">Editar</button>
        <button class="btn btn-sm btn-danger" data-del-level="${lv.id}">Eliminar</button>
      </div>
      <div class="tree-body">
        ${lgrades.length ? lgrades.map(g => {
          const gcs = courses.filter(c => c.grade_id === g.id);
          return `<div class="grade">
            <div class="grade-head">
              <span>${esc(g.name)}</span><span class="badge info">${gcs.length} curso(s)</span>
              <span class="spacer"></span>
              <button class="btn btn-sm" data-add-course="${g.id}">+ Curso</button>
              <button class="btn btn-sm" data-edit-grade="${g.id}">Editar</button>
              <button class="btn btn-sm btn-danger" data-del-grade="${g.id}">Eliminar</button>
            </div>
            <div class="courses">
              ${gcs.map(c => `<span class="course-chip">
                  <b>${esc(c.name)}</b>
                  <span class="m">${c.students || 0} est.</span>
                  <span class="m">${c.need}h/${c.capacity}b</span>
                  <button class="btn btn-sm" data-edit-course="${c.id}">✎</button>
                  <button class="btn btn-sm btn-danger" data-del-course="${c.id}">✕</button>
                </span>`).join('') || '<span class="hint">Sin cursos — agregue uno</span>'}
            </div>
          </div>`;
        }).join('') : '<div class="hint" style="padding:8px">Sin grados. Agregue un grado.</div>'}
      </div>
    </div>`;
  }).join('') || `<div class="empty"><div class="big">▤</div>No hay niveles. Cree "Primaria" y "Secundaria".</div>`;

  setView(`
    <div class="toolbar">
      <button class="btn btn-primary" id="add-level">+ Nuevo nivel</button>
      <span class="spacer"></span>
      <span class="hint">Nivel → Grado → Curso. Cada curso puede personalizar su jornada después.</span>
    </div>
    ${tree}`);

  const courseFields = gid => ([
    {name: 'grade_id', label: 'Grado', type: 'select', required: true, default: gid,
     options: grades.map(g => ({value: g.id, label: `${g.name} (${(levels.find(l => l.id === g.level_id) || {}).name})`}))},
    {name: 'name', label: 'Nombre del grupo', type: 'text', required: true, hint: 'Ej.: A, B…', default: 'A'},
    {name: 'students', label: 'N.º de estudiantes', type: 'number', default: 30},
    {name: 'base_room_id', label: 'Aula fija (opcional)', type: 'select', default: '', options: roomOpts}
  ]);

  document.getElementById('add-level').onclick = () => openFormModal({
    title: 'Nuevo nivel', fields: LEVEL_FIELDS, values: {days: WEEK.slice(0, 5)},
    onSubmit: async d => { await API.create('levels', d); toast('Nivel creado', 'ok'); refresh(); }
  });
  document.querySelectorAll('[data-edit-level]').forEach(b => b.onclick = () => {
    const lv = levels.find(l => l.id === +b.dataset.editLevel);
    openFormModal({title: 'Editar nivel: ' + lv.name, fields: LEVEL_FIELDS, values: lv,
      onSubmit: async d => { await API.update('levels', lv.id, d); toast('Nivel actualizado', 'ok'); refresh(); }});
  });
  document.querySelectorAll('[data-del-level]').forEach(b => b.onclick = async () => {
    if (await confirmDialog('Eliminar nivel', 'Se eliminarán sus grados y cursos. ¿Continuar?'))
      { await API.remove('levels', +b.dataset.delLevel); toast('Nivel eliminado', 'ok'); refresh(); }
  });
  document.querySelectorAll('[data-add-grade]').forEach(b => b.onclick = () => openFormModal({
    title: 'Nuevo grado', fields: [
      {name: 'level_id', label: 'Nivel', type: 'select', default: +b.dataset.addGrade,
       options: opts(levels, l => l.name)},
      {name: 'name', label: 'Grado', type: 'text', required: true, hint: 'Ej.: 1°, 6°'},
      {name: 'order_index', label: 'Orden', type: 'number', default: 0}
    ],
    onSubmit: async d => { await API.create('grades', d); toast('Grado creado', 'ok'); refresh(); }
  }));
  document.querySelectorAll('[data-edit-grade]').forEach(b => b.onclick = () => {
    const g = grades.find(x => x.id === +b.dataset.editGrade);
    openFormModal({title: 'Editar grado', fields: [
      {name: 'level_id', label: 'Nivel', type: 'select', value: g.level_id, options: opts(levels, l => l.name)},
      {name: 'name', label: 'Grado', type: 'text', required: true},
      {name: 'order_index', label: 'Orden', type: 'number'}], values: g,
      onSubmit: async d => { await API.update('grades', g.id, d); toast('Grado actualizado', 'ok'); refresh(); }});
  });
  document.querySelectorAll('[data-del-grade]').forEach(b => b.onclick = async () => {
    if (await confirmDialog('Eliminar grado', 'Se eliminarán sus cursos. ¿Continuar?'))
      { await API.remove('grades', +b.dataset.delGrade); toast('Grado eliminado', 'ok'); refresh(); }
  });
  document.querySelectorAll('[data-add-course]').forEach(b => b.onclick = () => openFormModal({
    title: 'Nuevo curso', fields: courseFields(+b.dataset.addCourse),
    onSubmit: async d => {
      if (d.base_room_id === '') d.base_room_id = null;
      await API.create('courses', d); toast('Curso creado', 'ok'); refresh(); }
  }));
  document.querySelectorAll('[data-edit-course]').forEach(b => b.onclick = () => {
    const c = courses.find(x => x.id === +b.dataset.editCourse);
    const f = courseFields(c.grade_id); f[0].default = c.grade_id;
    openFormModal({title: 'Editar curso: ' + courseLabel(c), fields: f, values: {...c, base_room_id: c.base_room_id || ''},
      onSubmit: async d => {
        if (d.base_room_id === '') d.base_room_id = null;
        await API.update('courses', c.id, d); toast('Curso actualizado', 'ok'); refresh(); }});
  });
  document.querySelectorAll('[data-del-course]').forEach(b => b.onclick = async () => {
    if (await confirmDialog('Eliminar curso', '¿Eliminar este curso y sus asignaciones?'))
      { await API.remove('courses', +b.dataset.delCourse); toast('Curso eliminado', 'ok'); refresh(); }
  });
};

/* ============================== 4. Profesores ============================== */
const TEACHER_FIELDS = subjects => ([
  {name: 'name', label: 'Nombre completo', type: 'text', required: true},
  {name: 'subjects', label: 'Asignaturas que puede enseñar', type: 'multiselect',
   options: opts(subjects, s => s.name), hint: 'Déjelo vacío para no restringir'},
  {name: 'min_hours', label: 'Horas mínimas / semana', type: 'number', default: 0},
  {name: 'max_hours', label: 'Horas máximas / semana (0 = sin límite)', type: 'number', default: 0},
  {name: 'availability', label: 'Disponibilidad horaria', type: 'availability', full: true},
  {name: 'notes', label: 'Restricciones / notas personales', type: 'textarea', full: true}
]);

const ASSIGN_FIELDS = async () => {
  const [teachers, subjects, courses] = await Promise.all([
    API.list('teachers'), API.list('subjects'), API.list('courses')]);
  const grades = await API.list('grades');
  const gmap = Object.fromEntries(grades.map(g => [g.id, g.name]));
  return [
    {name: 'teacher_id', label: 'Profesor', type: 'select', required: true, options: opts(teachers, t => t.name)},
    {name: 'subject_id', label: 'Asignatura', type: 'select', required: true, options: opts(subjects, s => s.name)},
    {name: 'course_id', label: 'Curso', type: 'select', required: true,
     options: courses.map(c => ({value: c.id, label: `${gmap[c.grade_id]} ${c.name}`}))},
    {name: 'hours', label: 'Horas semanales en ese curso', type: 'number', required: true, default: 2}
  ];
};

ROUTES.profesores = async () => {
  const [teachers, subjects, assignments] = await Promise.all([
    API.list('teachers'), API.list('subjects'), API.list('assignments')]);
  const smap = Object.fromEntries(subjects.map(s => [s.id, s]));

  setView(`
    <div class="toolbar">
      <button class="btn btn-primary" id="add-teacher">+ Nuevo profesor</button>
      <span class="spacer"></span>
      <span class="hint">${teachers.length} profesores · ${assignments.length} asignaciones</span>
    </div>
    <div class="card"><div id="teachers-table"></div></div>
    <div class="card">
      <h2>Asignaciones: qué profesor da qué asignatura a qué curso</h2>
      <div class="sub">Esta información es la que usa el generador. Un profesor no puede estar en dos cursos a la vez (regla dura).</div>
      <div class="toolbar"><button class="btn btn-primary" id="add-assign">+ Nueva asignación</button></div>
      <div id="assign-table"></div>
    </div>`);

  renderTable(document.getElementById('teachers-table'), {
    rows: teachers,
    columns: [
      {label: 'Profesor', render: t => `<b>${esc(t.name)}</b>${t.notes ? `<div class="kv">${esc(t.notes)}</div>` : ''}`},
      {label: 'Asignaturas', render: t => (t.subjects || []).map(id =>
        smap[id] ? `<span class="chip" style="background:${esc(smap[id].color)}">${esc(smap[id].name)}</span>` : '').join('') || '<span class="badge mut">todas</span>'},
      {label: 'Horas', render: t => `<b>${t.hours}h</b>${t.max_hours ? ` <span class="kv">/ máx ${t.max_hours}h</span>` : ''}`},
      {label: 'Disponibilidad', render: t => availSummary(t.availability)}
    ],
    onEdit: t => openFormModal({title: 'Editar profesor: ' + t.name, fields: TEACHER_FIELDS(subjects), values: t,
      onSubmit: async d => { await API.update('teachers', t.id, d); toast('Profesor actualizado', 'ok'); refresh(); }}),
    onDelete: async t => { await API.remove('teachers', t.id); toast('Profesor eliminado', 'ok'); refresh(); }
  });
  document.getElementById('add-teacher').onclick = () => openFormModal({
    title: 'Nuevo profesor', fields: TEACHER_FIELDS(subjects),
    values: {availability: defaultAvailability('07:00', '13:00'), min_hours: 0, max_hours: 0},
    onSubmit: async d => { await API.create('teachers', d); toast('Profesor creado', 'ok'); refresh(); }
  });

  const afields = await ASSIGN_FIELDS();
  renderTable(document.getElementById('assign-table'), {
    rows: assignments,
    columns: [
      {label: 'Profesor', render: a => `<b>${esc(a.teacher_name)}</b>`},
      {label: 'Asignatura', render: a => `<span class="chip" style="background:${esc(a.subject_color)}">${esc(a.subject_name)}</span>`},
      {label: 'Curso', render: a => esc(a.course_label)},
      {label: 'Horas/semana', render: a => `<b>${a.hours}h</b>`}
    ],
    onEdit: async a => {
      const f = await ASSIGN_FIELDS();
      openFormModal({title: 'Editar asignación', fields: f, values: a,
        onSubmit: async d => { await API.update('assignments', a.id, d); toast('Asignación actualizada', 'ok'); refresh(); }});
    },
    onDelete: async a => { await API.remove('assignments', a.id); toast('Asignación eliminada', 'ok'); refresh(); }
  });
  document.getElementById('add-assign').onclick = async () => {
    const f = await ASSIGN_FIELDS();
    openFormModal({title: 'Nueva asignación', fields: f, values: {hours: 2},
      onSubmit: async d => { await API.create('assignments', d); toast('Asignación creada', 'ok'); refresh(); }});
  };
};

/* ============================== 5. Asignaturas ============================== */
const SUBJECT_FIELDS = async meta => ([
  {name: 'name', label: 'Nombre', type: 'text', required: true},
  {name: 'default_hours', label: 'Intensidad semanal por defecto', type: 'number', required: true, default: 2},
  {name: 'room_type', label: 'Aula requerida', type: 'select', default: '',
   options: [{value: '', label: 'Salón normal'}].concat(meta.room_types)},
  {name: 'double_block', label: 'Bloque doble (2 horas consecutivas obligatorias)', type: 'checkbox', default: false},
  {name: 'soft_block_pref', label: 'Bloques automáticos (3+ horas, regla blanda)', type: 'select', default: 'auto',
   options: meta.soft_prefs},
  {name: 'color', label: 'Color en el horario', type: 'color', default: '#4f8ef7'}
]);

ROUTES.asignaturas = async () => {
  const [subjects, meta] = await Promise.all([API.list('subjects'), getMeta()]);
  const fields = await SUBJECT_FIELDS(meta);
  const labels = Object.fromEntries(meta.room_types.map(t => [t.value, t.label]));
  setView(`
    <div class="toolbar">
      <button class="btn btn-primary" id="add-subject">+ Nueva asignatura</button>
      <span class="spacer"></span>
      <span class="hint">La intensidad se puede ajustar por curso en cada asignación.</span>
    </div>
    <div class="card"><div id="subjects-table"></div></div>`);
  renderTable(document.getElementById('subjects-table'), {
    rows: subjects,
    columns: [
      {label: 'Asignatura', render: s => `<span class="chip" style="background:${esc(s.color)}">${esc(s.name)}</span>`},
      {label: 'Intensidad', render: s => `${s.default_hours} h/sem`},
      {label: 'Aula requerida', render: s => s.room_type ? roomTypeBadge(s.room_type) : '<span class="badge mut">Normal</span>'},
      {label: 'Bloques', render: s => (s.double_block ? '<span class="badge warn">Doble ×2 (duro)</span> ' : '') +
        `<span class="badge ${s.soft_block_pref === 'none' ? 'mut' : 'info'}">${
          {prefer: 'Preferir bloques', auto: 'Automático', none: 'Sin bloques'}[s.soft_block_pref] || s.soft_block_pref}</span>`}
    ],
    onEdit: s => openFormModal({title: 'Editar: ' + s.name, fields, values: {...s, double_block: !!s.double_block, room_type: s.room_type || ''},
      onSubmit: async d => { d.room_type = d.room_type || null; d.double_block = d.double_block ? 1 : 0;
        await API.update('subjects', s.id, d); toast('Asignatura actualizada', 'ok'); refresh(); }}),
    onDelete: async s => { await API.remove('subjects', s.id); toast('Asignatura eliminada', 'ok'); refresh(); }
  });
  document.getElementById('add-subject').onclick = () => openFormModal({
    title: 'Nueva asignatura', fields,
    onSubmit: async d => { d.room_type = d.room_type || null; d.double_block = d.double_block ? 1 : 0;
      await API.create('subjects', d); toast('Asignatura creada', 'ok'); refresh(); }
  });
};

/* ============================== 6. Aulas ============================== */
ROUTES.aulas = async () => {
  const [rooms, subjects, courses, grades, meta] = await Promise.all([
    API.list('classrooms'), API.list('subjects'), API.list('courses'),
    API.list('grades'), getMeta()]);
  const gmap = Object.fromEntries(grades.map(g => [g.id, g.name]));
  const fields = [
    {name: 'name', label: 'Nombre del aula', type: 'text', required: true},
    {name: 'kind', label: 'Tipo de aula', type: 'select', default: 'normal',
     options: [{value: 'normal', label: 'Salón normal'}, {value: 'special', label: 'Aula especial (compartida)'}]},
    {name: 'room_type', label: 'Categoría de espacio especial', type: 'select', default: '',
     options: [{value: '', label: '— no aplica —'}].concat(meta.room_types),
     hint: 'Sala de Sistemas, Laboratorio, Cancha o Taller'},
    {name: 'capacity', label: 'Capacidad (opcional)', type: 'number', default: 0},
    {name: 'allowed_subjects', label: 'Asignaturas permitidas (vacío = todas)', type: 'multiselect',
     options: opts(subjects, s => s.name)},
    {name: 'allowed_courses', label: 'Cursos que pueden usarla (vacío = todos)', type: 'multiselect',
     options: courses.map(c => ({value: c.id, label: `${gmap[c.grade_id] || ''} ${c.name}`}))},
    {name: 'availability', label: 'Disponibilidad del aula', type: 'availability', full: true},
    {name: 'notes', label: 'Notas', type: 'textarea', full: true}
  ];
  const norm = rooms.filter(r => r.kind === 'normal').length;
  const esp = rooms.length - norm;
  setView(`
    <div class="toolbar">
      <button class="btn btn-primary" id="add-room">+ Nueva aula</button>
      <span class="spacer"></span>
      <span class="badge mut">${norm} salones</span><span class="badge warn">${esp} especiales</span>
    </div>
    <div class="info-box">Las <b>aulas especiales</b> (Sala de Sistemas, Laboratorio, Cancha, Taller) son
      <b>compartidas y excluyentes</b>: solamente un curso puede ocuparlas a la vez. El generador lo garantiza
      como regla dura.</div>
    <div class="card"><div id="rooms-table"></div></div>`);
  renderTable(document.getElementById('rooms-table'), {
    rows: rooms,
    columns: [
      {label: 'Aula', render: r => `<b>${esc(r.name)}</b>${r.notes ? `<div class="kv">${esc(r.notes)}</div>` : ''}`},
      {label: 'Tipo', render: r => r.kind === 'normal' ? '<span class="badge mut">Normal</span>' : roomTypeBadge(r.room_type)},
      {label: 'Cap.', render: r => r.capacity || '—'},
      {label: 'Asignaturas permitidas', render: r => (r.allowed_subjects || []).map(id => {
        const s = subjects.find(x => x.id === id); return s ? `<span class="chip" style="background:${esc(s.color)}">${esc(s.name)}</span>` : '';
      }).join('') || '<span class="badge mut">todas</span>'},
      {label: 'Disponibilidad', render: r => availSummary(r.availability)}
    ],
    onEdit: r => openFormModal({title: 'Editar: ' + r.name, fields,
      values: {...r, room_type: r.room_type || ''},
      onSubmit: async d => {
        d.room_type = d.kind === 'normal' ? null : (d.room_type || null);
        if (!d.allowed_subjects || !d.allowed_subjects.length) d.allowed_subjects = null;
        if (!d.allowed_courses || !d.allowed_courses.length) d.allowed_courses = null;
        await API.update('classrooms', r.id, d); toast('Aula actualizada', 'ok'); refresh(); }}),
    onDelete: async r => { await API.remove('classrooms', r.id); toast('Aula eliminada', 'ok'); refresh(); }
  });
  document.getElementById('add-room').onclick = () => openFormModal({
    title: 'Nueva aula', fields, values: {kind: 'normal', availability: defaultAvailability('07:00', '13:30')},
    onSubmit: async d => {
      d.room_type = d.kind === 'normal' ? null : (d.room_type || null);
      if (!d.allowed_subjects || !d.allowed_subjects.length) d.allowed_subjects = null;
      if (!d.allowed_courses || !d.allowed_courses.length) d.allowed_courses = null;
      await API.create('classrooms', d); toast('Aula creada', 'ok'); refresh(); }
  });
};

/* ============================== 7. Horarios / Jornadas ============================== */
ROUTES.jornadas = async () => {
  const [levels, courses, school] = await Promise.all([API.list('levels'), API.list('courses'), getSchool()]);
  const rooms = (await API.list('classrooms')).filter(r => r.kind === 'normal');
  const breakInfo = school.break_start && school.break_end
    ? `<span class="badge warn">Descanso del colegio: ${esc(school.break_start)}–${esc(school.break_end)}</span>
       <span class="hint" style="margin-left:6px">Se aplica a todos los niveles y maestros. Se edita en <a href="#/colegio"><b>Datos del colegio</b></a>.</span>`
    : '<span class="badge mut">Sin descanso configurado</span>';
  const courseJFields = c => ([
    {name: 'entry_time', label: 'Entrada (vacío = hereda del nivel)', type: 'time', default: ''},
    {name: 'exit_time', label: 'Salida (vacío = hereda)', type: 'time', default: ''},
    {name: 'blocks_per_day', label: 'Bloques por día (vacío = hereda)', type: 'number', default: null},
    {name: 'block_minutes', label: 'Minutos por bloque (vacío = hereda)', type: 'number', default: null},
    {name: 'days', label: 'Días (vacío = hereda)', type: 'days'},
    {name: 'base_room_id', label: 'Aula fija', type: 'select', default: '',
     options: [{value: '', label: '— automático —'}].concat(opts(rooms, r => r.name))}
  ]);
  setView(`
    <div class="card">
      <h2>Jornadas por nivel</h2>
      <div class="sub">Primaria y Secundaria pueden tener horarios diferentes. El sistema nunca mezcla sus bloques y
        detecta conflictos de profesores entre niveles. &nbsp; ${breakInfo}</div>
      <div id="levels-jornada"></div>
    </div>
    <div class="card">
      <h2>Jornada personalizada por curso</h2>
      <div class="sub">Si un curso necesita otra entrada, otra cantidad de bloques u otros días, personalícelo aquí.
        Los campos vacíos heredan la jornada de su nivel. El descanso lo define el colegio y no puede heredarse por curso.</div>
      <div id="courses-jornada"></div>
    </div>`);
  renderTable(document.getElementById('levels-jornada'), {
    rows: levels, rowActions: false,
    columns: [
      {label: 'Nivel', render: l => `<b>${esc(l.name)}</b>`},
      {label: 'Entrada', render: l => `<span class="mono">${l.entry_time}</span>`},
      {label: 'Salida', render: l => `<span class="mono">${l.exit_time}</span>`},
      {label: 'Bloques/día', render: l => l.blocks_per_day},
      {label: 'Min./bloque', render: l => l.block_minutes},
      {label: 'Días', render: l => (Array.isArray(l.days) ? l.days : JSON.parse(l.days || '[]')).map(d => d.slice(0, 3)).join(', ')},
      {label: '', render: l => `<button class="btn btn-sm" data-editl="${l.id}">Editar</button>`}
    ]
  });
  document.querySelectorAll('[data-editl]').forEach(b => b.onclick = () => {
    const lv = levels.find(l => l.id === +b.dataset.editl);
    openFormModal({title: 'Jornada: ' + lv.name, fields: LEVEL_FIELDS, values: lv,
      onSubmit: async d => { await API.update('levels', lv.id, d); toast('Jornada actualizada', 'ok'); refresh(); }});
  });
  renderTable(document.getElementById('courses-jornada'), {
    rows: courses,
    columns: [
      {label: 'Curso', render: c => `<b>${esc(courseLabel(c))}</b> ${levelBadge(c.level_name)}`},
      {label: 'Jornada efectiva', render: c => `<span class="mono">${c.entry}–${c.exit} · ${c.effective_blocks} bloques</span>`},
      {label: 'Horas/config', render: c => `<span class="badge ${c.need > c.capacity ? 'bad' : (c.need < c.capacity ? 'warn' : 'ok')}">${c.need}h / ${c.capacity} bloques</span>`},
      {label: 'Aula', render: c => esc(c.base_room_name || 'automática')},
      {label: '', render: c => `<button class="btn btn-sm" data-editc="${c.id}">Personalizar</button>`}
    ]
  });
  document.querySelectorAll('[data-editc]').forEach(b => b.onclick = () => {
    const c = courses.find(x => x.id === +b.dataset.editc);
    openFormModal({title: 'Jornada del curso ' + courseLabel(c),
      fields: courseJFields(c),
      values: {...c, entry_time: c.entry_time || '', exit_time: c.exit_time || '',
               blocks_per_day: c.blocks_per_day || '', block_minutes: c.block_minutes || '',
               days: c.days || null, base_room_id: c.base_room_id || ''},
      onSubmit: async d => {
        d.entry_time = d.entry_time || null; d.exit_time = d.exit_time || null;
        d.blocks_per_day = d.blocks_per_day || null; d.block_minutes = d.block_minutes || null;
        d.days = (!d.days || !d.days.length) ? null : d.days;
        d.base_room_id = d.base_room_id || null;
        await API.update('courses', c.id, d); toast('Jornada del curso actualizada', 'ok'); refresh(); }});
  });
};

/* ============================== 8. Bloques ============================== */
ROUTES.bloques = async () => {
  const [subjects, school, meta] = await Promise.all([API.list('subjects'), getSchool(), getMeta()]);
  setView(`
    <div class="card">
      <h2>Asignaturas en bloques de dos horas</h2>
      <div class="sub">Marque las asignaturas que deben darse en <b>bloques dobles obligatorios</b> (dos horas
        consecutivas = una sesión). Es una regla DURA: sus horas semanales deben ser pares.</div>
      <div id="dbl-list"></div>
    </div>
    <div class="card">
      <h2>Bloques automáticos para asignaturas de 3 o más horas</h2>
      <div class="sub">Regla BLANDA: el generador intentará repartir las horas en sesiones de 2 (p. ej. Matemáticas 5 h
        → 2 + 2 + 1). Si no es posible, relaja la preferencia y nunca lo declara imposible.</div>
      <div class="form-grid">
        <div class="field"><label>Preferencia global</label>
          <select id="pref-global">${meta.soft_prefs.map(o =>
            `<option value="${o.value}" ${school.config.soft.block_pref_3plus === o.value ? 'selected' : ''}>${o.label}</option>`).join('')}</select>
          <span class="hint">Cada asignatura puede tener su propia preferencia (se edita aquí abajo).</span>
        </div>
      </div>
      <div style="margin-top:12px"><button class="btn btn-primary" id="save-pref">Guardar preferencia global</button></div>
      <h3>Preferencia por asignatura (≥ 3 horas)</h3>
      <div id="soft-list"></div>
    </div>`);

  const dbl = document.getElementById('dbl-list');
  dbl.innerHTML = `<div class="table-wrap"><table class="tbl"><thead><tr>
    <th>Asignatura</th><th>Horas por defecto</th><th>Aula requerida</th><th>¿Bloque doble de 2 h?</th></tr></thead>
    <tbody>${subjects.map(s => `<tr>
      <td><span class="chip" style="background:${esc(s.color)}">${esc(s.name)}</span></td>
      <td>${s.default_hours} h</td><td>${s.room_type ? roomTypeBadge(s.room_type) : '<span class="badge mut">Normal</span>'}</td>
      <td><input type="checkbox" data-dbl="${s.id}" ${s.double_block ? 'checked' : ''}></td>
    </tr>`).join('')}</tbody></table></div>
    <div style="margin-top:12px"><button class="btn btn-primary" id="save-dbl">Guardar bloques dobles</button></div>`;
  dbl.querySelectorAll('[data-dbl]').forEach(ch => ch.addEventListener('change', async () => {
    const id = +ch.dataset.dbl;
    const s = subjects.find(x => x.id === id);
    await API.update('subjects', id, {double_block: ch.checked ? 1 : 0});
    toast(`"${s.name}": bloque doble ${ch.checked ? 'activado' : 'desactivado'}`, 'ok');
  }));
  document.getElementById('save-dbl').onclick = () => { toast('Configuración de bloques dobles guardada', 'ok'); refresh(); };

  const soft = document.getElementById('soft-list');
  soft.innerHTML = `<div class="table-wrap"><table class="tbl"><thead><tr>
    <th>Asignatura</th><th>Horas</th><th>Preferencia de bloques (regla blanda)</th></tr></thead>
    <tbody>${subjects.map(s => `<tr>
      <td><span class="chip" style="background:${esc(s.color)}">${esc(s.name)}</span></td>
      <td>${s.default_hours} h</td>
      <td><select class="ctrl" data-soft="${s.id}">${meta.soft_prefs.map(o =>
        `<option value="${o.value}" ${s.soft_block_pref === o.value ? 'selected' : ''}>${o.label}</option>`).join('')}</select></td>
    </tr>`).join('')}</tbody></table></div>`;
  soft.querySelectorAll('[data-soft]').forEach(sel => sel.addEventListener('change', async () => {
    await API.update('subjects', +sel.dataset.soft, {soft_block_pref: sel.value});
    toast('Preferencia actualizada', 'ok');
  }));
  document.getElementById('save-pref').onclick = async () => {
    const cfg = school.config;
    cfg.soft.block_pref_3plus = document.getElementById('pref-global').value;
    await API.put('/api/school', {config: cfg});
    toast('Preferencia global guardada', 'ok');
    getSchool();
  };
};

/* ============================== 9. Reglas ============================== */
ROUTES.reglas = async () => {
  const school = await getSchool();
  const s = school.config.soft;
  const g = school.config.generation;
  setView(`
    <div class="card">
      <h2>Reglas blandas (preferencias de optimización)</h2>
      <div class="sub">Nunca hacen fallar la generación: el sistema las incumple antes que una regla dura.</div>
      <div class="form-grid">
        <div class="field"><label>Máx. horas consecutivas de una asignatura en un día</label>
          <input type="number" id="r-maxc" value="${s.max_consecutive}"></div>
        <div class="field"><label>Máx. horas consecutivas del mismo profesor</label>
          <input type="number" id="r-tmaxc" value="${s.teacher_max_consecutive}"></div>
        <div class="field"><label>Preferencias activas</label>
          <div class="checks" id="r-toggles">
            <label><input type="checkbox" data-k="spread_subjects" ${s.spread_subjects ? 'checked' : ''}> Distribuir asignaturas en la semana</label>
            <label><input type="checkbox" data-k="avoid_end_of_day" ${s.avoid_end_of_day ? 'checked' : ''}> Evitar quedar siempre al final</label>
            <label><input type="checkbox" data-k="balance_daily" ${s.balance_daily ? 'checked' : ''}> Equilibrar carga diaria</label>
            <label><input type="checkbox" data-k="avoid_teacher_gaps" ${s.avoid_teacher_gaps ? 'checked' : ''}> Evitar huecos innecesarios del profesor</label>
          </div></div>
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary" id="save-rules">Guardar reglas</button></div>
    </div>
    <div class="card">
      <h2>Parámetros del algoritmo</h2>
      <div class="sub">Búsqueda CSP con backtracking, MRV dinámico y reinicios aleatorizados.</div>
      <div class="form-grid">
        <div class="field"><label>Intentos de búsqueda</label><input type="number" id="g-att" value="${g.attempts}"></div>
        <div class="field"><label>Tiempo límite por intento (segundos)</label><input type="number" id="g-time" value="${g.time_limit}"></div>
      </div>
      <div style="margin-top:14px"><button class="btn btn-primary" id="save-gen">Guardar parámetros</button></div>
      <div class="hint-box" style="margin-top:14px"><b>Reglas duras</b> (siempre): profesor en dos cursos a la vez,
        aula ocupada por dos cursos, Sala de Sistemas / Laboratorio / Cancha compartidos, un curso con dos asignaturas
        a la vez, jornada, disponibilidad e intensidad horaria exacta.</div>
    </div>`);
  document.getElementById('save-rules').onclick = async () => {
    const cfg = school.config;
    cfg.soft.max_consecutive = +document.getElementById('r-maxc').value || 3;
    cfg.soft.teacher_max_consecutive = +document.getElementById('r-tmaxc').value || 4;
    document.querySelectorAll('#r-toggles input').forEach(i => cfg.soft[i.dataset.k] = i.checked);
    await API.put('/api/school', {config: cfg});
    toast('Reglas guardadas', 'ok'); getSchool();
  };
  document.getElementById('save-gen').onclick = async () => {
    const cfg = school.config;
    cfg.generation.attempts = +document.getElementById('g-att').value || 6;
    cfg.generation.time_limit = +document.getElementById('g-time').value || 20;
    await API.put('/api/school', {config: cfg});
    toast('Parámetros guardados', 'ok'); getSchool();
  };
};

/* ============================== 10. Generar ============================== */
ROUTES.generar = async () => {
  const school = await getSchool();
  const c = school.counts;
  const noAssign = c.assignments === 0;
  setView(`
    <div class="card">
      <h2>Generar horario académico</h2>
      <div class="sub">El sistema valida la configuración, ejecuta el algoritmo de restricciones (CSP con
        backtracking) y vuelve a validar el resultado de forma independiente.</div>
      <div class="grid c4" style="margin-bottom:14px">
        <div class="stat"><div class="v">${c.courses}</div><div class="l">Cursos</div></div>
        <div class="stat"><div class="v">${c.assignments}</div><div class="l">Asignaciones</div></div>
        <div class="stat"><div class="v">${c.classrooms}</div><div class="l">Aulas</div></div>
        <div class="stat"><div class="v">${c.teachers}</div><div class="l">Profesores</div></div>
      </div>
      ${noAssign ? `<div class="hint-box">No hay asignaciones de profesor–asignatura–curso. Cree al menos una en
        <a href="#/profesores"><b>Profesores</b></a> antes de generar.</div>` : ''}
      <div class="toolbar">
        <button class="btn btn-primary btn-lg" id="gen-btn" ${noAssign ? 'disabled' : ''}>⚡ GENERAR HORARIO</button>
        <span id="gen-status"></span>
      </div>
    </div>
    <div id="gen-result"></div>`);

  const renderResult = (res) => {
    const box = document.getElementById('gen-result');
    if (res.status === 'ok') {
      const relax = res.stats && res.stats.soft_blocks_relaxed;
      box.innerHTML = `<div class="result ok">
        <h3>✅ Horario generado correctamente</h3>
        <div>${esc(res.message)} — se guardó como <b>${esc(res.scheduleName || 'versión nueva')}</b>
          (${(res.stats && res.stats.nodes) || 0} nodos de búsqueda, ${(res.stats && res.stats.attempts) || 1} intento(s),
          puntuación blanda ${Math.round((res.stats && res.stats.score) || 0)}).</div>
        ${(res.warnings || []).length ? `<div class="warns"><b>Avisos:</b><ul>${res.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
        ${relax ? `<div class="warns">Se relajaron bloques automáticos blandos para lograr la solución.</div>` : ''}
        <div style="margin-top:12px;display:flex;gap:8px;flex-wrap:wrap">
          <a class="btn btn-ok" href="#/horarios">Ver horario</a>
          <a class="btn" href="#/validacion">Validar</a>
          <a class="btn" href="#/exportar">Exportar</a>
        </div></div>`;
    } else {
      const diags = res.diagnostics || [];
      box.innerHTML = `<div class="result bad">
        <h3>❌ NO ES POSIBLE GENERAR UN HORARIO VÁLIDO</h3>
        <div>No se encontró ninguna distribución que cumpla todas las reglas duras con la configuración actual.</div>
        ${diags.length ? `<p style="margin:10px 0 4px"><b>CONFLICTOS ENCONTRADOS:</b></p>
          <ol>${diags.map(d => `<li>${esc(d)}</li>`).join('')}</ol>` : ''}
        ${(res.warnings || []).length ? `<div class="warns"><b>Avisos:</b><ul>${res.warnings.map(w => `<li>${esc(w)}</li>`).join('')}</ul></div>` : ''}
        <div style="margin-top:12px"><a class="btn" href="#/profesores">Revisar asignaciones</a>
          <a class="btn" href="#/jornadas">Revisar jornadas</a>
          <a class="btn" href="#/aulas">Revisar aulas</a></div>
      </div>`;
    }
    window.scrollTo({top: 0, behavior: 'smooth'});
  };
  if (state.lastResult) renderResult(state.lastResult);

  document.getElementById('gen-btn').onclick = async () => {
    const btn = document.getElementById('gen-btn');
    const st = document.getElementById('gen-status');
    btn.disabled = true;
    st.innerHTML = `<span class="spinner"></span> <span style="color:var(--muted)">Validando configuración y
      buscando solución…</span>`;
    document.getElementById('gen-result').innerHTML = '';
    try {
      const res = await API.post('/api/generate', {});
      res.scheduleName = res.schedule_id ? 'v' + res.schedule_id : '';
      state.lastResult = res;
      renderResult(res);
      toast(res.status === 'ok' ? 'Horario generado' : 'No fue posible generar el horario',
            res.status === 'ok' ? 'ok' : 'bad');
    } catch (e) {
      toast(e.message, 'bad');
      document.getElementById('gen-result').innerHTML =
        `<div class="result bad"><h3>Error inesperado</h3><div>${esc(e.message)}</div></div>`;
    } finally {
      btn.disabled = false;
      st.innerHTML = '';
      state.schedules = await API.get('/api/schedules');
    }
  };
};

/* ============================== 11. Horarios generados ============================== */
function renderSchedTable(v) {
  if (!v.rows || !v.rows.length) return '<div class="empty"><div class="big">▦</div>Sin clases en esta vista.</div>';
  const head = `<tr><th class="rowh">Bloque</th>${v.days.map(d => `<th>${esc(d)}</th>`).join('')}</tr>`;
  const body = v.rows.map(r => `<tr class="${r.is_break ? 'sched-break' : ''}">
    <td class="rowh">${esc(r.label)}</td>
    ${v.days.map(d => {
      if (r.is_break) return `<td><div class="cell-break">☕ Descanso</div></td>`;
      const cells = r.cells[d] || [];
      if (!cells.length) return `<td><div class="cell-free">— libre —</div></td>`;
      return `<td>${cells.map(c =>
        `<div class="cell-item" style="background:${esc(c.color || '#4f8ef7')}">${esc(c.text)}</div>`).join('')}</td>`;
    }).join('')}
  </tr>`).join('');
  return `<div class="sched-wrap"><table class="sched"><thead>${head}</thead><tbody>${body}</tbody></table></div>`;
}

async function loadViewer() {
  const v = state.viewer;
  const data = await API.get(`/api/schedules/${v.scheduleId}/view?type=${v.type}` +
    (v.id ? `&id=${v.id}` : ''));
  document.getElementById('sched-area').innerHTML = `
    <div class="kv" style="margin-bottom:8px"><b>${esc(data.title)}</b></div>${renderSchedTable(data)}`;
}

ROUTES.horarios = async () => {
  const schedules = await API.get('/api/schedules');
  state.schedules = schedules;
  const sid = state.viewer.scheduleId ||
    (schedules.find(s => s.status === 'ok' && s.is_current) || schedules.find(s => s.status === 'ok') || {}).id || null;
  state.viewer.scheduleId = sid;
  if (!sid) {
    setView(`<div class="card"><div class="empty"><div class="big">▧</div>
      Aún no hay horarios generados.<br><br><a class="btn btn-primary" href="#/generar">Generar horario</a></div></div>`);
    return;
  }
  setView(`
    <div class="card">
      <h2>Versiones guardadas</h2>
      <div class="sub">Cada generación crea una versión que puede consultarse o eliminarse.</div>
      <div id="sched-list"></div>
    </div>
    <div class="card">
      <div class="tabs" id="view-tabs">
        <button class="tab" data-t="curso">Por curso</button>
        <button class="tab" data-t="profesor">Por profesor</button>
        <button class="tab" data-t="aula">Por aula</button>
        <button class="tab" data-t="general">General del colegio</button>
        <span class="spacer" style="flex:1"></span>
        <select class="ctrl" id="view-select"></select>
      </div>
      <div id="sched-area"><div class="loading"><span class="spinner"></span></div></div>
    </div>`);

  renderTable(document.getElementById('sched-list'), {
    rows: schedules, rowActions: false,
    columns: [
      {label: 'Versión', render: s => `<b>${esc(s.name)}</b> ${s.is_current ? '<span class="badge ok">actual</span>' : ''}`},
      {label: 'Estado', render: s => s.status === 'ok'
        ? `<span class="badge ok">VÁLIDO</span>` : `<span class="badge bad">FALLIDO</span>`},
      {label: 'Creado', render: s => `<span class="kv">${esc(s.created_at)}</span>`},
      {label: 'Bloques', render: s => s.entries},
      {label: '', render: s => `
        <button class="btn btn-sm ${s.status === 'ok' ? 'btn-primary' : ''}" data-open="${s.id}">Ver</button>
        <button class="btn btn-sm" data-ren="${s.id}">Renombrar</button>
        <button class="btn btn-sm btn-danger" data-del="${s.id}">Eliminar</button>`}
    ]
  });
  document.querySelectorAll('[data-open]').forEach(b => b.onclick = () => {
    state.viewer = {scheduleId: +b.dataset.open, type: state.viewer.type, id: null};
    ROUTES.horarios();
  });
  document.querySelectorAll('[data-ren]').forEach(b => b.onclick = async () => {
    const s = schedules.find(x => x.id === +b.dataset.ren);
    openFormModal({title: 'Renombrar versión', fields: [{name: 'name', label: 'Nombre', type: 'text', required: true}],
      values: s, onSubmit: async d => { await API.post(`/api/schedules/${s.id}/rename`, d); toast('Renombrado', 'ok'); refresh(); }});
  });
  document.querySelectorAll('[data-del]').forEach(b => b.onclick = async () => {
    if (await confirmDialog('Eliminar horario', '¿Eliminar esta versión del horario?'))
      { await API.del(`/api/schedules/${b.dataset.del}`); toast('Eliminado', 'ok');
        if (state.viewer.scheduleId === +b.dataset.del) state.viewer.scheduleId = null; refresh(); }
  });

  const selects = await API.get(`/api/schedules/${sid}/selects`);
  const type = state.viewer.type;
  const selEl = document.getElementById('view-select');
  function fillSelect() {
    const t = state.viewer.type;
    let items = [];
    if (t === 'curso') items = selects.courses;
    else if (t === 'profesor') items = selects.teachers;
    else if (t === 'aula') items = selects.rooms;
    if (t === 'general') { selEl.style.display = 'none'; state.viewer.id = null; }
    else {
      selEl.style.display = '';
      selEl.innerHTML = items.map(i => `<option value="${i.id}">${esc(i.label)}</option>`).join('');
      if (!state.viewer.id || !items.some(i => i.id === state.viewer.id))
        state.viewer.id = items.length ? items[0].id : null;
      selEl.value = state.viewer.id;
    }
  }
  document.querySelectorAll('#view-tabs .tab').forEach(tb => {
    tb.classList.toggle('active', tb.dataset.t === type);
    tb.onclick = () => {
      document.querySelectorAll('#view-tabs .tab').forEach(x => x.classList.remove('active'));
      tb.classList.add('active');
      state.viewer.type = tb.dataset.t;
      state.viewer.id = null;
      fillSelect();
      loadViewer();
    };
  });
  selEl.onchange = () => { state.viewer.id = +selEl.value; loadViewer(); };
  fillSelect();
  await loadViewer();
};

/* ============================== 12. Validación ============================== */
ROUTES.validacion = async () => {
  const schedules = await API.get('/api/schedules');
  const okOnes = schedules.filter(s => s.status === 'ok');
  if (!okOnes.length) {
    setView(`<div class="card"><div class="empty"><div class="big">✓</div>
      No hay horarios generados para validar.<br><br>
      <a class="btn btn-primary" href="#/generar">Generar horario</a></div></div>`);
    return;
  }
  const sid = state.viewer.scheduleId && okOnes.some(s => s.id === state.viewer.scheduleId)
    ? state.viewer.scheduleId : (okOnes.find(s => s.is_current) || okOnes[0]).id;
  setView(`
    <div class="toolbar">
      <label style="font-weight:700">Horario:</label>
      <select class="ctrl" id="val-select">${okOnes.map(s =>
        `<option value="${s.id}" ${s.id === sid ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select>
      <button class="btn btn-primary" id="val-run">Validar ahora</button>
    </div>
    <div id="val-result"><div class="loading"><span class="spinner"></span></div></div>`);
  async function run() {
    const id = +document.getElementById('val-select').value;
    const res = await API.get(`/api/schedules/${id}/validation`);
    const box = document.getElementById('val-result');
    box.innerHTML = `
      <div class="result ${res.ok ? 'ok' : 'bad'}">
        <h3>${res.ok ? '✅ VALIDACIÓN DEL HORARIO: todas las comprobaciones pasan'
                     : '❌ VALIDACIÓN DEL HORARIO: se detectaron conflictos'}</h3>
        <div>${res.ok ? 'El horario cumple todas las reglas duras.'
                      : 'Este horario NO debe considerarse válido: corrija los siguientes puntos.'}</div>
      </div>
      ${res.checks.map(c => `<div class="check ${c.ok ? 'ok' : 'bad'}">
        <div class="ico">${c.ok ? '✅' : '❌'}</div>
        <div style="flex:1"><div class="t">${esc(c.label)}</div>
        ${c.ok ? '<div class="kv">Sin conflictos</div>'
               : `<ul class="errs">${c.errors.map(e => `<li>${esc(e)}</li>`).join('')}</ul>`}</div>
      </div>`).join('')}`;
  }
  document.getElementById('val-run').onclick = async () => {
    try { await run(); } catch (e) { toast(e.message, 'bad'); }
  };
  await run();
};

/* ============================== 13. Exportar ============================== */
ROUTES.exportar = async () => {
  const schedules = await API.get('/api/schedules');
  const okOnes = schedules.filter(s => s.status === 'ok');
  if (!okOnes.length) {
    setView(`<div class="card"><div class="empty"><div class="big">⤓</div>
      Genere un horario antes de exportar.<br><br><a class="btn btn-primary" href="#/generar">Generar</a></div></div>`);
    return;
  }
  const sid = state.viewer.scheduleId && okOnes.some(s => s.id === state.viewer.scheduleId)
    ? state.viewer.scheduleId : (okOnes.find(s => s.is_current) || okOnes[0]).id;
  const selects = await API.get(`/api/schedules/${sid}/selects`);
  setView(`
    <div class="card">
      <h2>Exportar horario</h2>
      <div class="sub">Excel incluye hojas: General, Por curso, Por profesor y Por aula.</div>
      <div class="form-grid" style="max-width:640px">
        <div class="field"><label>Versión del horario</label>
          <select class="ctrl" id="ex-sel">${okOnes.map(s =>
            `<option value="${s.id}" ${s.id === sid ? 'selected' : ''}>${esc(s.name)}</option>`).join('')}</select></div>
        <div class="field"><label>Vista para CSV</label>
          <select class="ctrl" id="ex-view">
            <option value="general">General del colegio</option>
            <option value="curso">Curso…</option>
            <option value="profesor">Profesor…</option>
            <option value="aula">Aula…</option>
          </select></div>
        <div class="field" id="ex-obj-wrap" style="display:none"><label>Elemento</label>
          <select class="ctrl" id="ex-obj"></select></div>
      </div>
      <div style="margin-top:16px;display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary" id="ex-xlsx">⤓ Descargar Excel (.xlsx)</button>
        <button class="btn" id="ex-pdf">⤓ Descargar PDF</button>
        <button class="btn" id="ex-csv">⤓ Descargar CSV</button>
      </div>
    </div>`);
  const viewSel = document.getElementById('ex-view');
  const objWrap = document.getElementById('ex-obj-wrap');
  const objSel = document.getElementById('ex-obj');
  function fillObjs() {
    const v = viewSel.value;
    if (v === 'general') { objWrap.style.display = 'none'; return; }
    objWrap.style.display = '';
    const items = v === 'curso' ? selects.courses : (v === 'profesor' ? selects.teachers : selects.rooms);
    objSel.innerHTML = items.map(i => `<option value="${i.id}">${esc(i.label)}</option>`).join('');
  }
  viewSel.onchange = fillObjs;
  fillObjs();
  const id = () => document.getElementById('ex-sel').value;
  document.getElementById('ex-xlsx').onclick = () =>
    API.download(`/api/export/xlsx?schedule_id=${id()}`, 'horario.xlsx').then(() => toast('Excel descargado', 'ok')).catch(e => toast(e.message, 'bad'));
  document.getElementById('ex-pdf').onclick = () =>
    API.download(`/api/export/pdf?schedule_id=${id()}`, 'horario.pdf').then(() => toast('PDF descargado', 'ok')).catch(e => toast(e.message, 'bad'));
  document.getElementById('ex-csv').onclick = () => {
    const v = viewSel.value;
    const oid = v === 'general' ? '' : '&id=' + objSel.value;
    API.download(`/api/export/csv?schedule_id=${id()}&view=${v}${oid}`, 'horario.csv')
      .then(() => toast('CSV descargado', 'ok')).catch(e => toast(e.message, 'bad'));
  };
};

/* ============================== 14. Configuración ============================== */
ROUTES.config = async () => {
  const school = await getSchool();
  setView(`
    <div class="card">
      <h2>Datos de prueba</h2>
      <div class="sub">Colegio completo de ejemplo: Primaria y Secundaria, 11 cursos, 27 profesores,
        Sala de Sistemas, Laboratorio, Cancha, Taller y bloques dobles.</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap">
        <button class="btn btn-primary" id="cfg-seed">♻ Cargar colegio de demostración</button>
        <button class="btn btn-danger" id="cfg-clear">Nuevo colegio vacío</button>
      </div>
    </div>
    <div class="card">
      <h2>Guardar y cargar configuración</h2>
      <div class="sub">Exporte toda la configuración del colegio (niveles, cursos, profesores, asignaturas,
        aulas y asignaciones) como archivo JSON para respaldarla o copiarla a otro equipo.</div>
      <div style="display:flex;gap:10px;flex-wrap:wrap;align-items:center">
        <button class="btn" id="cfg-export">⤓ Exportar configuración (JSON)</button>
        <label class="btn" style="cursor:pointer">⤒ Importar configuración
          <input type="file" id="cfg-import" accept="application/json" style="display:none"></label>
      </div>
    </div>
    <div class="card">
      <h2>Información</h2>
      <table class="tbl"><tbody>
        <tr><td>Colegio</td><td><b>${esc(school.name)}</b></td></tr>
        <tr><td>Configuración</td><td class="mono">${Object.keys(school.counts).length} entidades ·
          ${school.counts.assignments} asignaciones</td></tr>
        <tr><td>Algoritmo</td><td>CSP con backtracking + MRV dinámico, validación independiente posterior</td></tr>
        <tr><td>Reglas duras</td><td>Profesores, cursos, aulas, aulas especiales, jornada, disponibilidad,
          intensidad horaria y bloques dobles obligatorios</td></tr>
      </tbody></table>
    </div>`);

  document.getElementById('cfg-seed').onclick = async () => {
    if (await confirmDialog('Cargar datos de prueba',
      'Se reemplazará toda la configuración actual por el colegio de demostración. ¿Continuar?')) {
      await API.post('/api/seed');
      state.lastResult = null; state.viewer.scheduleId = null;
      toast('Colegio demostración cargado', 'ok');
      getSchool(); refresh();
    }
  };
  document.getElementById('cfg-clear').onclick = async () => {
    if (await confirmDialog('Nuevo colegio',
      'Se eliminarán todos los datos (cursos, profesores, aulas, horarios). Esta acción no se puede deshacer. ¿Continuar?')) {
      await API.post('/api/clear', {});
      state.lastResult = null; state.viewer.scheduleId = null;
      toast('Colegio vacío creado', 'ok');
      getSchool(); refresh();
    }
  };
  document.getElementById('cfg-export').onclick = async () => {
    const data = await API.get('/api/config/export');
    const blob = new Blob([JSON.stringify(data, null, 2)], {type: 'application/json'});
    const a = document.createElement('a');
    a.href = URL.createObjectURL(blob);
    a.download = 'configuracion_horarios.json';
    a.click();
    toast('Configuración exportada', 'ok');
  };
  document.getElementById('cfg-import').onchange = async ev => {
    const f = ev.target.files[0];
    if (!f) return;
    try {
      const txt = await f.text();
      const data = JSON.parse(txt);
      if (await confirmDialog('Importar configuración',
        'Se reemplazará la configuración actual. ¿Continuar?')) {
        await API.post('/api/config/import', data);
        state.lastResult = null; state.viewer.scheduleId = null;
        toast('Configuración importada', 'ok');
        getSchool(); refresh();
      }
    } catch (e) {
      toast('Archivo inválido: ' + e.message, 'bad');
    }
    ev.target.value = '';
  };
};
