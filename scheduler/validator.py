"""Validación independiente del horario generado.

No confía en el algoritmo: relee la base y comprueba una por una todas las
reglas duras. Un solo conflicto duro => el horario NO se marca como válido.
"""
from collections import Counter, defaultdict

from . import db
from .solver import t2m, room_type_label, window_covers


def _load(conn, schedule_id):
    entries = db.rows(conn, "SELECT * FROM schedule_entries WHERE schedule_id = ?", (schedule_id,))
    courses = {r["id"]: r for r in db.rows(conn, "SELECT * FROM courses")}
    grades = {r["id"]: r for r in db.rows(conn, "SELECT * FROM grades")}
    levels = {r["id"]: r for r in db.rows(conn, "SELECT * FROM levels")}
    teachers = {r["id"]: r for r in db.rows(conn, "SELECT * FROM teachers")}
    subjects = {r["id"]: r for r in db.rows(conn, "SELECT * FROM subjects")}
    rooms = {r["id"]: r for r in db.rows(conn, "SELECT * FROM classrooms")}
    assigns = db.rows(conn, "SELECT * FROM assignments")
    for t in teachers.values():
        t["availability"] = db.jload(t["availability"], {}) or {}
    for r in rooms.values():
        r["availability"] = db.jload(r["availability"], {}) or {}
        r["allowed_subjects"] = db.jload(r["allowed_subjects"], None)
        r["allowed_courses"] = db.jload(r["allowed_courses"], None)

    meta = {}
    sb = db.school_break(conn)  # descanso global del colegio (min, min) o None
    breaks = [sb] if sb else []
    for cid, c in courses.items():
        g = grades.get(c["grade_id"])
        lvl = levels.get(g["level_id"]) if g else None
        if not g or not lvl:
            continue
        entry = c["entry_time"] or lvl["entry_time"]
        bpd = c["blocks_per_day"] or lvl["blocks_per_day"]
        bm = c["block_minutes"] or lvl["block_minutes"]
        days = db.jload(c["days"]) or db.jload(lvl["days"]) or list(db.DEFAULT_DAYS)
        grid = {}
        for d in days:
            for (i, s, e) in db.build_blocks(entry, bm, bpd, breaks):
                grid[(d, i)] = (s, e)
        meta[cid] = {
            "label": "%s %s" % (g["name"], c["name"]),
            "days": days, "blocks_per_day": bpd, "grid": grid,
            "breaks": db.parse_breaks(breaks), "level": lvl["name"],
        }
    return entries, courses, meta, teachers, subjects, rooms, assigns


def validate(conn, schedule_id):
    (entries, courses, meta, teachers, subjects, rooms, assigns) = _load(conn, schedule_id)
    checks = []

    def add(key, label, errors):
        checks.append({"key": key, "label": label, "ok": not errors, "errors": errors[:50]})

    if not entries:
        add("empty", "Horario con contenido", ["Este horario no tiene clases asignadas."])
        return checks

    # ---------- 1. profesores sin conflictos (incluye primaria vs secundaria)
    by_t = defaultdict(list)
    for e in entries:
        by_t[e["teacher_id"]].append(e)
    errs = []
    for tid, lst in by_t.items():
        tname = teachers.get(tid, {}).get("name", "??")
        per_day = defaultdict(list)
        for e in lst:
            per_day[e["day"]].append((t2m(e["start_time"]), t2m(e["end_time"]), e))
        for d, ivs in per_day.items():
            ivs.sort(key=lambda x: (x[0], x[1]))
            for i in range(1, len(ivs)):
                if ivs[i][0] < ivs[i - 1][1]:
                    e1, e2 = ivs[i - 1][2], ivs[i][2]
                    c1 = meta.get(e1["course_id"], {}).get("label", "?")
                    c2 = meta.get(e2["course_id"], {}).get("label", "?")
                    errs.append(
                        "Profesor %s: conflicto el %s a las %s (da %s a %s y %s a %s)."
                        % (tname, d, e1["start_time"], subjects.get(e1["subject_id"], {}).get("name", "?"),
                           c1, subjects.get(e2["subject_id"], {}).get("name", "?"), c2)
                    )
    add("teachers", "Profesores sin conflictos", errs)

    # ---------- 2. disponibilidad de profesores
    errs = []
    for e in entries:
        t = teachers.get(e["teacher_id"])
        if not t:
            errs.append("Clase con profesor inexistente (id %s)." % e["teacher_id"])
            continue
        if not window_covers(t["availability"], e["day"], t2m(e["start_time"]), t2m(e["end_time"])):
            errs.append(
                "Profesor %s: el %s de %s a %s está fuera de su disponibilidad."
                % (t["name"], e["day"], e["start_time"], e["end_time"])
            )
    add("teacher_availability", "Disponibilidad de profesores", errs)

    # ---------- 3. aulas sin conflictos
    by_r = defaultdict(list)
    for e in entries:
        if e["classroom_id"]:
            by_r[e["classroom_id"]].append(e)
    errs = []
    for rid, lst in by_r.items():
        rname = rooms.get(rid, {}).get("name", "??")
        per_day = defaultdict(list)
        for e in lst:
            per_day[e["day"]].append((t2m(e["start_time"]), t2m(e["end_time"]), e))
        for d, ivs in per_day.items():
            ivs.sort(key=lambda x: (x[0], x[1]))
            for i in range(1, len(ivs)):
                if ivs[i][0] < ivs[i - 1][1]:
                    c1 = meta.get(ivs[i - 1][2]["course_id"], {}).get("label", "?")
                    c2 = meta.get(ivs[i][2]["course_id"], {}).get("label", "?")
                    errs.append("Aula %s: ocupada por %s y %s a la vez el %s a las %02d:%02d."
                                % (rname, c1, c2, d, ivs[i][0] // 60, ivs[i][0] % 60))
    add("rooms", "Aulas sin conflictos", errs)

    # ---------- 4. disponibilidad de aulas
    errs = []
    for e in entries:
        r = rooms.get(e["classroom_id"])
        if not r:
            continue
        if not window_covers(r["availability"], e["day"], t2m(e["start_time"]), t2m(e["end_time"])):
            errs.append(
                "Aula %s: el %s de %s a %s está fuera de su disponibilidad."
                % (r["name"], e["day"], e["start_time"], e["end_time"])
            )
    add("room_availability", "Disponibilidad de aulas", errs)

    # ---------- 5. cursos sin conflictos
    by_c = defaultdict(list)
    for e in entries:
        by_c[e["course_id"]].append(e)
    errs = []
    for cid, lst in by_c.items():
        label = meta.get(cid, {}).get("label", "?")
        per_day = defaultdict(list)
        for e in lst:
            per_day[e["day"]].append((t2m(e["start_time"]), t2m(e["end_time"]), e))
        for d, ivs in per_day.items():
            ivs.sort(key=lambda x: (x[0], x[1]))
            for i in range(1, len(ivs)):
                if ivs[i][0] < ivs[i - 1][1]:
                    errs.append(
                        "Curso %s: dos asignaturas a la vez el %s (%s y %s)."
                        % (label, d, subjects.get(ivs[i - 1][2]["subject_id"], {}).get("name", "?"),
                           subjects.get(ivs[i][2]["subject_id"], {}).get("name", "?"))
                    )
    add("courses", "Cursos sin conflictos", errs)

    # ---------- 6/7. Sala de Sistemas y Laboratorio por separado
    for rt in ("sistemas", "laboratorio", "cancha", "taller"):
        errs = []
        for rid, lst in by_r.items():
            r = rooms.get(rid)
            if not r or r.get("room_type") != rt:
                continue
            per_day = defaultdict(list)
            for e in lst:
                per_day[e["day"]].append((t2m(e["start_time"]), t2m(e["end_time"]), e))
            for d, ivs in per_day.items():
                ivs.sort(key=lambda x: (x[0], x[1]))
                for i in range(1, len(ivs)):
                    if ivs[i][0] < ivs[i - 1][1]:
                        c1 = meta.get(ivs[i - 1][2]["course_id"], {}).get("label", "?")
                        c2 = meta.get(ivs[i][2]["course_id"], {}).get("label", "?")
                        errs.append(
                            "%s ocupada por %s y %s a la vez el %s a las %02d:%02d."
                            % (r["name"], c1, c2, d, ivs[i][0] // 60, ivs[i][0] % 60)
                        )
        add("room_%s" % rt, "%s sin conflictos" % room_type_label(rt), errs)

    # ---------- 8. intensidad horaria cumplida
    expected = defaultdict(int)
    for a in assigns:
        expected[(a["course_id"], a["subject_id"])] += a["hours"]
    actual = Counter((e["course_id"], e["subject_id"]) for e in entries)
    errs = []
    for key, exp in expected.items():
        cid, sid = key
        act = actual.get(key, 0)
        if act != exp:
            errs.append(
                "El curso %s tiene %d hora(s) de %s pero se requieren %d."
                % (meta.get(cid, {}).get("label", "?"), act,
                   subjects.get(sid, {}).get("name", "?"), exp)
            )
    for key, act in actual.items():
        if key not in expected:
            cid, sid = key
            errs.append(
                "El curso %s tiene %d hora(s) de %s sin asignación formal de profesor."
                % (meta.get(cid, {}).get("label", "?"), act, subjects.get(sid, {}).get("name", "?"))
            )
    add("hours", "Intensidad horaria cumplida", errs)

    # ---------- 9. bloques dobles cumplidos
    errs = []
    double_subjects = {s["id"] for s in subjects.values() if s["double_block"]}
    ds = defaultdict(set)
    for e in entries:
        if e["subject_id"] in double_subjects:
            ds[(e["course_id"], e["subject_id"], e["day"])].add(e["block_index"])
    for (cid, sid, d), blocks in ds.items():
        bs = sorted(blocks)
        i = 0
        while i < len(bs):
            if i + 1 < len(bs) and bs[i + 1] == bs[i] + 1:
                i += 2
            else:
                errs.append(
                    "%s (%s): la sesión del %s en el bloque %d no es un bloque doble de 2 horas consecutivas."
                    % (subjects[sid]["name"], meta.get(cid, {}).get("label", "?"), d, bs[i] + 1)
                )
                i += 1
    add("double_blocks", "Bloques dobles cumplidos", errs)

    # ---------- 9b. descanso del colegio respetado (nadie tiene clase entonces)
    errs = []
    for e in entries:
        m = meta.get(e["course_id"])
        if not m or not m["breaks"]:
            continue
        s, en = t2m(e["start_time"]), t2m(e["end_time"])
        for (ws, we) in m["breaks"]:
            if s < we and en > ws:
                errs.append(
                    "Hay clase (%s) el %s de %s a %s dentro del descanso "
                    "del colegio (%02d:%02d-%02d:%02d)."
                    % (m["label"], e["day"], e["start_time"], e["end_time"],
                       ws // 60, ws % 60, we // 60, we % 60)
                )
                break
    add("breaks", "Descanso del colegio respetado", errs)

    # ---------- 10. jornada respetada
    errs = []
    for e in entries:
        m = meta.get(e["course_id"])
        if not m:
            errs.append("Clase para un curso inexistente (id %s)." % e["course_id"])
            continue
        if e["day"] not in m["days"]:
            errs.append("Curso %s: clase el %s fuera de sus días de jornada." % (m["label"], e["day"]))
            continue
        g = m["grid"].get((e["day"], e["block_index"]))
        if not g:
            errs.append("Curso %s: clase el %s en bloque inexistente %s."
                        % (m["label"], e["day"], e["block_index"]))
        else:
            if g[0] != t2m(e["start_time"]) or g[1] != t2m(e["end_time"]):
                errs.append(
                    "Curso %s: hora %s-%s no corresponde a su jornada (esperado %02d:%02d-%02d:%02d)."
                    % (m["label"], e["start_time"], e["end_time"],
                       g[0] // 60, g[0] % 60, g[1] // 60, g[1] % 60)
                )
    add("schedule_window", "Jornada respetada (días y bloques)", errs)

    # ---------- 11. aulas adecuadas + asignaciones válidas
    errs = []
    assign_set = {(a["teacher_id"], a["subject_id"], a["course_id"]) for a in assigns}
    for e in entries:
        s = subjects.get(e["subject_id"])
        c = courses.get(e["course_id"])
        label = meta.get(e["course_id"], {}).get("label", "?")
        if (e["teacher_id"], e["subject_id"], e["course_id"]) not in assign_set:
            errs.append(
                "El profesor %s no está asignado para dar %s a %s."
                % (teachers.get(e["teacher_id"], {}).get("name", "?"),
                   s["name"] if s else "?", label)
            )
        r = rooms.get(e["classroom_id"])
        if s and s.get("room_type"):
            if not r or r.get("room_type") != s["room_type"]:
                errs.append(
                    "%s requiere %s pero %s está en %s."
                    % (s["name"], room_type_label(s["room_type"]), label,
                       r["name"] if r else "ningún aula")
                )
        if r:
            subs = r.get("allowed_subjects")
            if subs is not None and e["subject_id"] not in subs:
                errs.append("La asignatura %s no está permitida en el aula %s."
                            % (s["name"] if s else "?", r["name"]))
            crs = r.get("allowed_courses")
            if crs is not None and e["course_id"] not in crs:
                errs.append("El curso %s no está permitido en el aula %s." % (label, r["name"]))
    add("adequacy", "Aulas adecuadas y asignaciones válidas", errs)

    return checks
