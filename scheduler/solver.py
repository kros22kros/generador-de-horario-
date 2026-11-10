"""Generador de horarios por satisfacción de restricciones (CSP + backtracking).

Reglas duras  : profesor, curso, aula, aulas especiales, laboratorio,
                Sala de Sistemas, jornada, intensidad horaria, bloques dobles
                y disponibilidad  ->  se cumplen SIEMPRE.
Reglas blandas: distribución diaria, horas consecutivas, huecos de profesor,
                evitar fin de jornada, etc.  ->  función de puntuación.
"""
import random
import sys
import time
from collections import Counter, defaultdict

from . import db

sys.setrecursionlimit(50000)

ROOM_TYPE_LABELS = {
    "sistemas": "Sala de Sistemas",
    "laboratorio": "Laboratorio",
    "cancha": "Cancha / Polideportivo",
    "taller": "Taller",
}


def room_type_label(rt):
    return ROOM_TYPE_LABELS.get(rt, rt or "Salón normal")


def t2m(s):
    h, m = s.split(":")
    return int(h) * 60 + int(m)


def m2t(m):
    return "%02d:%02d" % (m // 60, m % 60)


def intervals_overlap(s1, e1, s2, e2):
    return s1 < e2 and s2 < e1


# ---------------------------------------------------------------- modelo ----
class Model:
    pass


def load_model(conn):
    m = Model()
    m.school = db.get_school(conn)
    m.school_break = db.school_break(conn)   # descanso global (min, min) o None
    m.levels = {r["id"]: r for r in db.rows(conn, "SELECT * FROM levels ORDER BY order_index, id")}
    m.grades = db.rows(conn, "SELECT * FROM grades ORDER BY order_index, id")
    m.teachers = {r["id"]: r for r in db.rows(conn, "SELECT * FROM teachers ORDER BY name")}
    m.subjects = {r["id"]: r for r in db.rows(conn, "SELECT * FROM subjects ORDER BY name")}
    m.classrooms = {r["id"]: r for r in db.rows(conn, "SELECT * FROM classrooms ORDER BY name")}
    m.assignments = db.rows(conn, "SELECT * FROM assignments ORDER BY id")

    grade_by_id = {g["id"]: g for g in m.grades}
    m.courses = {}
    for c in db.rows(conn, "SELECT * FROM courses ORDER BY id"):
        g = grade_by_id.get(c["grade_id"])
        if not g:
            continue
        lvl = m.levels.get(g["level_id"])
        if not lvl:
            continue
        entry = c["entry_time"] or lvl["entry_time"]
        exit_ = c["exit_time"] or lvl["exit_time"]
        bpd = c["blocks_per_day"] or lvl["blocks_per_day"]
        bm = c["block_minutes"] or lvl["block_minutes"]
        days = db.jload(c["days"]) or db.jload(lvl["days"]) or list(db.DEFAULT_DAYS)
        blocks = []
        by_day = defaultdict(dict)
        for d in days:
            for (i, s, e) in db.build_blocks(entry, bm, bpd, [m.school_break] if m.school_break else []):
                blocks.append((d, i, s, e))
                by_day[d][i] = (s, e)
        c2 = dict(c)
        c2.update(
            level_id=lvl["id"], level_name=lvl["name"], grade_name=g["name"],
            entry=entry, exit=exit_, blocks_per_day=bpd, block_minutes=bm,
            days=days, blocks=blocks, by_day=by_day,
            breaks=[m.school_break] if m.school_break else [],
            need=0, base_room_id=c["base_room_id"],
        )
        c2["label"] = "%s %s" % (g["name"], c["name"])
        m.courses[c["id"]] = c2

    # horas requeridas por curso
    for a in m.assignments:
        if a["course_id"] in m.courses:
            m.courses[a["course_id"]]["need"] += a["hours"]

    for t in m.teachers.values():
        t["availability"] = db.jload(t["availability"], {}) or {}
        t["subjects"] = db.jload(t["subjects"], []) or []
    for r in m.classrooms.values():
        r["availability"] = db.jload(r["availability"], {}) or {}
        r["allowed_subjects"] = db.jload(r["allowed_subjects"], None)
        r["allowed_courses"] = db.jload(r["allowed_courses"], None)
    return m


def window_covers(avail, day, s, e):
    if not avail:
        return True
    w = avail.get(day)
    if not w or not w.get("on", True):
        return False
    return t2m(w.get("start", "00:00")) <= s and e <= t2m(w.get("end", "23:59"))


# ------------------------------------------------------- aulas base --------
def assign_base_rooms(m, errors):
    """Asigna un salón normal a cada curso (uso exclusivo por jornada)."""
    normal = [
        r for r in m.classrooms.values()
        if r["kind"] == "normal" and (r["room_type"] in (None, "", "normal"))
    ]
    normal.sort(key=lambda r: r["id"])
    assigned = {}

    def allows(course, room):
        ac = room.get("allowed_courses")
        if ac is not None and course["id"] not in ac:
            return False
        return True

    def overlap_days_blocks(c1, c2):
        if set(c1["days"]) & set(c2["days"]):
            for d in c1["days"]:
                for (dd, i, s1, e1) in c1["blocks"]:
                    if dd != d:
                        continue
                    for (d2, j, s2, e2) in c2["blocks"]:
                        if d2 == d and intervals_overlap(s1, e1, s2, e2):
                            return True
        return False

    courses = sorted(m.courses.values(), key=lambda c: (c["level_id"], c["label"]))
    for c in courses:
        if c["base_room_id"]:
            room = m.classrooms.get(c["base_room_id"])
            if room and allows(c, room):
                assigned[c["id"]] = room["id"]
                continue
            errors.append(
                "El aula configurada para el curso %s no existe o no permite ese curso." % c["label"]
            )
        taken = set()
        for other_id, room_id in assigned.items():
            other = m.courses[other_id]
            if overlap_days_blocks(c, other):
                taken.add(room_id)
        choice = None
        for r in normal:
            if r["id"] not in taken and allows(c, r):
                choice = r
                break
        if choice is None:
            errors.append(
                "No hay suficientes salones normales: el curso %s no encuentra aula libre "
                "(hacen falta al menos %d salones para la superposición actual de jornadas)."
                % (c["label"], len(taken) + 1)
            )
        else:
            assigned[c["id"]] = choice["id"]
    return assigned


# ---------------------------------------------------- validación previa ----
def greedy_max_slots(intervals):
    """Máximo número de intervalos mutuamente no solapados (agendar posible)."""
    iv = sorted(intervals, key=lambda x: x[1])
    count, end = 0, -1
    for s, e in iv:
        if s >= end:
            count += 1
            end = e
    return count


def prevalidate(m, base_rooms):
    errors, warnings = [], []

    if not m.assignments:
        errors.append("No hay asignaciones de profesor-asignatura-curso. Configure la sección Profesores primero.")

    # --- cursos: intensidad vs jornada
    for c in m.courses.values():
        cap = c["blocks_per_day"] * len(c["days"])
        if c["need"] > cap:
            errors.append(
                "El curso %s necesita %d horas pero su jornada solamente permite %d bloques."
                % (c["label"], c["need"], cap)
            )
        elif c["need"] < cap:
            warnings.append(
                "El curso %s tendrá %d bloque(s) libre(s) por semana (%d horas de %d bloques)."
                % (c["label"], cap - c["need"], c["need"], cap)
            )
        if c["need"] == 0:
            warnings.append("El curso %s no tiene asignaciones de horas." % c["label"])

    # --- asignaciones: profesor habilitado
    for a in m.assignments:
        t = m.teachers.get(a["teacher_id"])
        s = m.subjects.get(a["subject_id"])
        c = m.courses.get(a["course_id"])
        if not t or not s or not c:
            errors.append("Hay una asignación con referencias inválidas (profesor/asignatura/curso).")
            continue
        if t["subjects"] and s["id"] not in t["subjects"]:
            errors.append(
                "El profesor %s no está habilitado para la asignatura %s (curso %s)."
                % (t["name"], s["name"], c["label"])
            )
        if s["double_block"] and a["hours"] % 2 != 0:
            errors.append(
                "%s está configurada en bloque doble pero %s (%s) tiene %d horas semanales; "
                "deben ser pares (2, 4, ...)." % (s["name"], c["label"], t["name"], a["hours"])
            )
        if t["max_hours"] and t["max_hours"] > 0:
            pass  # se calcula abajo con el total

    # --- profesores: horas vs disponibilidad real (unión de bloques compatibles)
    for t in m.teachers.values():
        total = sum(a["hours"] for a in m.assignments if a["teacher_id"] == t["id"])
        t["_hours"] = total
        ivs = []
        for a in m.assignments:
            if a["teacher_id"] != t["id"]:
                continue
            c = m.courses.get(a["course_id"])
            if not c:
                continue
            for (d, i, s, e) in c["blocks"]:
                if window_covers(t["availability"], d, s, e):
                    ivs.append((d, s, e))
        by_day = defaultdict(list)
        for d, s, e in ivs:
            by_day[d].append((s, e))
        cap = sum(greedy_max_slots(v) for v in by_day.values())
        t["_cap"] = cap
        if total > cap:
            errors.append(
                "El profesor %s tiene asignadas %d horas pero solamente dispone de %d bloques compatibles."
                % (t["name"], total, cap)
            )
        elif t["max_hours"] and total > t["max_hours"]:
            errors.append(
                "El profesor %s tiene asignadas %d horas pero su máximo configurado es %d."
                % (t["name"], total, t["max_hours"])
            )
        if t["min_hours"] and total and total < t["min_hours"]:
            warnings.append(
                "El profesor %s tiene %d horas asignadas (mínimo configurado: %d)."
                % (t["name"], total, t["min_hours"])
            )
        if total == 0:
            warnings.append("El profesor %s no tiene horas asignadas." % t["name"])

    # --- aulas especiales: horas requeridas vs capacidad de los aulas
    needed_by_type = Counter()
    for a in m.assignments:
        s = m.subjects.get(a["subject_id"])
        if s and s["room_type"]:
            needed_by_type[s["room_type"]] += a["hours"]
    for rt, needed in needed_by_type.items():
        rooms = [r for r in m.classrooms.values() if r["room_type"] == rt]
        if not rooms:
            errors.append(
                "La asignatura requiere %s pero no existe ningún aula de ese tipo."
                % room_type_label(rt)
            )
            continue
        cap = 0
        for r in rooms:
            by_day = defaultdict(list)
            for c in m.courses.values():
                for (d, i, s, e) in c["blocks"]:
                    if window_covers(r["availability"], d, s, e):
                        by_day[d].append((s, e))
            for d, lst in by_day.items():
                merged = []
                for s, e in sorted(lst):
                    if merged and s < merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                    else:
                        merged.append((s, e))
                cap += greedy_max_slots(merged)
        if needed > cap:
            errors.append(
                "%s: se requieren %d horas semanales pero solamente hay %d bloques disponibles."
                % (room_type_label(rt), needed, cap)
            )

    # --- aulas normales con restricción de asignaturas
    for c in m.courses.values():
        rid = base_rooms.get(c["id"])
        room = m.classrooms.get(rid) if rid else None
        if room:
            allowed = room.get("allowed_subjects")
            if allowed is not None:
                for a in m.assignments:
                    if a["course_id"] != c["id"]:
                        continue
                    s = m.subjects.get(a["subject_id"])
                    if s and not s["room_type"] and s["id"] not in allowed:
                        errors.append(
                            "La asignatura %s no está permitida en el aula %s asignada al curso %s."
                            % (s["name"], room["name"], c["label"])
                        )
    return errors, warnings


# ---------------------------------------------------------- sesiones --------
def build_sessions(m, soft_cfg):
    """Convierte asignaciones en sesiones (bloques) a colocar."""
    sessions = []
    pref_global = soft_cfg.get("block_pref_3plus", "auto")
    sid = 0
    for a in m.assignments:
        t = m.teachers.get(a["teacher_id"])
        s = m.subjects.get(a["subject_id"])
        c = m.courses.get(a["course_id"])
        if not t or not s or not c:
            continue
        h = a["hours"]
        lengths = []
        if s["double_block"]:
            lengths = [2] * (h // 2)
        else:
            pref = s.get("soft_block_pref") or pref_global
            if pref == "none":
                use_pairs = False
            elif pref == "prefer":
                use_pairs = h >= 3
            else:  # auto
                use_pairs = h >= 3
            if use_pairs:
                rest = h
                while rest >= 3:
                    lengths.append(2)
                    rest -= 2
                lengths.extend([1] * rest)
            else:
                lengths = [1] * h
        for L in lengths:
            sid += 1
            sessions.append({
                "id": sid, "course": c, "teacher": t, "subject": s,
                "room_type": s["room_type"] or None, "len": L,
                "static": [],
            })
    return sessions


def relax_soft_pairs(m, sessions, soft_cfg):
    """Segundo intento: conserva solo los bloques dobles duros."""
    keep = []
    for ses in sessions:
        s = ses["subject"]
        if s["double_block"]:
            keep.append(ses)
        else:
            for _ in range(ses["len"]):
                k = dict(ses)
                k["len"] = 1
                k["id"] = len(keep) + 1
                keep.append(k)
    for i, k in enumerate(keep, 1):
        k["id"] = i
    return keep


def compute_static_candidates(m, sessions, base_rooms):
    errors = []
    for ses in sessions:
        c = ses["course"]
        t = ses["teacher"]
        L = ses["len"]
        cands = []
        for d in c["days"]:
            day_blocks = c["by_day"][d]
            for i in range(c["blocks_per_day"] - L + 1):
                if any((i + k) not in day_blocks for k in range(L)):
                    continue
                if L > 1 and any(day_blocks[i + k][1] != day_blocks[i + k + 1][0]
                                 for k in range(L - 1)):
                    continue  # un bloque doble nunca puede cruzar un descanso
                s0 = day_blocks[i][0]
                e0 = day_blocks[i + L - 1][1]
                if not window_covers(t["availability"], d, s0, e0):
                    continue
                rooms = []
                if ses["room_type"] is None:
                    rid = base_rooms.get(c["id"])
                    room = m.classrooms.get(rid)
                    if room and window_covers(room["availability"], d, s0, e0):
                        subs = room.get("allowed_subjects")
                        if subs is None or ses["subject"]["id"] in subs:
                            crs = room.get("allowed_courses")
                            if crs is None or c["id"] in crs:
                                rooms = [rid]
                else:
                    for r in m.classrooms.values():
                        if r["room_type"] != ses["room_type"]:
                            continue
                        if not window_covers(r["availability"], d, s0, e0):
                            continue
                        subs = r.get("allowed_subjects")
                        if subs is not None and ses["subject"]["id"] not in subs:
                            continue
                        crs = r.get("allowed_courses")
                        if crs is not None and c["id"] not in crs:
                            continue
                        rooms.append(r["id"])
                if rooms:
                    cands.append({"d": d, "i": i, "s": s0, "e": e0, "rooms": rooms})
        ses["static"] = cands
        if not cands:
            if ses["room_type"] is None:
                errors.append(
                    "El profesor %s no está disponible en ningún bloque del curso %s (%s) "
                    "o el aula base no cubre su jornada."
                    % (t["name"], c["label"], ses["subject"]["name"])
                )
            else:
                avail_any = any(
                    window_covers(t["availability"], d, s0, e0)
                    for d in c["days"] for (dd, i, s0, e0) in c["blocks"]
                )
                if not avail_any:
                    errors.append(
                        "El profesor %s no está disponible en ningún bloque del curso %s (%s)."
                        % (t["name"], c["label"], ses["subject"]["name"])
                    )
                else:
                    errors.append(
                        "No hay ningún aula de tipo %s disponible para %s en el curso %s "
                        "(revise la disponibilidad del aula o su lista de asignaturas permitidas)."
                        % (room_type_label(ses["room_type"]), ses["subject"]["name"], c["label"])
                    )
    return errors


# ------------------------------------------------------------- búsqueda -----
class SearchFailure(Exception):
    pass


def solve(m, sessions, base_rooms, soft_cfg, gen_cfg, seed=0):
    """CSP con MRV dinámico, forward checking y reinicios aleatorizados.

    - Variable  : sesión (profesor + asignatura + curso + longitud).
    - Dominio   : bloques (día, índice) compatibles con jornada, disponibilidad
                  del profesor y aula libre (dura).
    - Heurística: MRV (menor dominio) con desempate por grado de restricción.
    - Blandas   : ordenamiento de candidatos por penalización + puntuación final.
    """
    n = len(sessions)
    if n == 0:
        return [], {"score": 0, "attempts": 1, "nodes": 0}

    course_busy = defaultdict(set)      # (cid, day) -> bloques ocupados
    teacher_busy = defaultdict(list)    # (tid, day) -> [(s,e)]
    room_busy = defaultdict(list)       # (rid, day) -> [(s,e)]
    course_day_count = Counter()
    course_subj_day = Counter()
    fail_counter = Counter()
    rng = random.Random(seed)

    def busy(ivlist, s, e):
        for (bs, be) in ivlist:
            if intervals_overlap(s, e, bs, be):
                return True
        return False

    def shares(a, b):
        sa, sb = sessions[a], sessions[b]
        if sa["course"]["id"] == sb["course"]["id"]:
            return True
        if sa["teacher"]["id"] == sb["teacher"]["id"]:
            return True
        if sa["room_type"] and sa["room_type"] == sb["room_type"]:
            return True
        if sa["room_type"] is None and sb["room_type"] is None:
            ra = base_rooms.get(sa["course"]["id"])
            rb = base_rooms.get(sb["course"]["id"])
            return ra is not None and ra == rb
        return False

    deg = [0] * n
    for i in range(n):
        for j in range(i + 1, n):
            if shares(i, j):
                deg[i] += 1
                deg[j] += 1

    def pick_room(ses, cand):
        for rid in cand["rooms"]:
            if not busy(room_busy[(rid, cand["d"])], cand["s"], cand["e"]):
                return rid
        return None

    def compute_domain(idx):
        ses = sessions[idx]
        out = []
        cid = ses["course"]["id"]
        tid = ses["teacher"]["id"]
        L = ses["len"]
        for cand in ses["static"]:
            d = cand["d"]
            i0 = cand["i"]
            if any((i0 + k) in course_busy[(cid, d)] for k in range(L)):
                continue
            if busy(teacher_busy[(tid, d)], cand["s"], cand["e"]):
                continue
            rid = pick_room(ses, cand)
            if rid is None:
                continue
            out.append((cand, rid))
        return out

    def penalty(ses, cand):
        c = ses["course"]
        p = 0
        p += 5 * course_subj_day[(c["id"], ses["subject"]["id"], cand["d"])]
        p += course_day_count[(c["id"], cand["d"])]
        if soft_cfg.get("avoid_end_of_day", True) and cand["i"] + ses["len"] >= c["blocks_per_day"]:
            p += 3
        if cand["i"] == 0:
            p += 1
        return p

    def place(idx, cand, rid):
        ses = sessions[idx]
        c, d, i0, L = ses["course"], cand["d"], cand["i"], ses["len"]
        for k in range(L):
            course_busy[(c["id"], d)].add(i0 + k)
        teacher_busy[(ses["teacher"]["id"], d)].append((cand["s"], cand["e"]))
        room_busy[(rid, d)].append((cand["s"], cand["e"]))
        course_day_count[(c["id"], d)] += 1
        course_subj_day[(c["id"], ses["subject"]["id"], d)] += 1
        placed[ses["id"]] = (cand, rid)

    def unplace(idx, cand, rid):
        ses = sessions[idx]
        c, d, i0, L = ses["course"], cand["d"], cand["i"], ses["len"]
        for k in range(L):
            course_busy[(c["id"], d)].discard(i0 + k)
        teacher_busy[(ses["teacher"]["id"], d)].remove((cand["s"], cand["e"]))
        room_busy[(rid, d)].remove((cand["s"], cand["e"]))
        course_day_count[(c["id"], d)] -= 1
        course_subj_day[(c["id"], ses["subject"]["id"], d)] -= 1
        del placed[ses["id"]]

    def record_fail(idx):
        ses = sessions[idx]
        c, t = ses["course"], ses["teacher"]
        reasons = Counter()
        for cand in ses["static"]:
            d, i0 = cand["d"], cand["i"]
            if any((i0 + k) in course_busy[(c["id"], d)] for k in range(ses["len"])):
                continue  # el propio curso ya no puede (raro: MRV lo habría visto)
            if busy(teacher_busy[(t["id"], d)], cand["s"], cand["e"]):
                key = "profesor|%s (%s %s, %s)" % (
                    t["name"], ses["subject"]["name"], c["label"],
                    "%02d:%02d" % (cand["s"] // 60, cand["s"] % 60))
                reasons[key] += 1
                continue
            room = m.classrooms[cand["rooms"][0]]
            key = "aula|%s está ocupada (%s %s, %s %s)" % (
                room["name"], ses["subject"]["name"], c["label"], d,
                "%02d:%02d" % (cand["s"] // 60, cand["s"] % 60))
            reasons[key] += 1
        if not reasons:
            reasons["estructura|Sin bloques compatibles para %s en %s" %
                    (ses["subject"]["name"], c["label"])] += 1
        fail_counter.update(reasons)

    domains = [None] * n
    unassigned = set(range(n))
    placed = {}
    nodes = [0]

    def bt(t0, time_limit):
        if not unassigned:
            return True
        nodes[0] += 1
        best = None
        best_d = 1 << 30
        for i in unassigned:
            d = len(domains[i])
            if d < best_d or (d == best_d and deg[i] > deg[best]):
                best_d = d
                best = i
        if best_d == 0:
            record_fail(best)
            return False
        ses = sessions[best]
        cands = sorted(domains[best],
                       key=lambda cr: (penalty(ses, cr[0]), rng.random()))
        unassigned.remove(best)
        for cand, rid in cands:
            place(best, cand, rid)
            aff = [j for j in unassigned if shares(best, j)]
            for j in aff:
                domains[j] = compute_domain(j)
            if bt(t0, time_limit):
                return True
            unplace(best, cand, rid)
            for j in aff:
                domains[j] = compute_domain(j)
            if time.time() - t0 > time_limit:
                raise TimeoutError
        unassigned.add(best)
        return False

    attempts = int(gen_cfg.get("attempts", 6))
    time_limit = float(gen_cfg.get("time_limit", 20))
    timed_out = False
    for att in range(attempts):
        course_busy.clear(); teacher_busy.clear(); room_busy.clear()
        course_day_count.clear(); course_subj_day.clear()
        placed.clear()
        unassigned.clear()
        unassigned.update(range(n))
        rng.seed(seed + att * 7919)
        nodes[0] = 0
        for i in range(n):
            domains[i] = compute_domain(i)
            if not domains[i]:
                record_fail(i)
        if any(not domains[i] for i in range(n)):
            # dominio vacío desde el inicio: causa estructural, no intentar
            raise SearchFailure(
                diagnose(m, sessions, base_rooms, fail_counter,
                         "Hay clases sin ningún bloque compatible antes de empezar a buscar."))
        t0 = time.time()
        try:
            if bt(t0, time_limit):
                entries = build_entries(m, sessions, placed)
                score = soft_score(m, sessions, placed, soft_cfg)
                stats = {"score": score, "attempts": att + 1, "nodes": nodes[0]}
                return entries, stats
        except TimeoutError:
            timed_out = True
            continue

    stage_msg = "Se agotó el tiempo límite de búsqueda (%gs tras %d intentos)." % (
        time_limit, attempts) if timed_out else None
    raise SearchFailure(diagnose(m, sessions, base_rooms, fail_counter, stage_msg))


def build_entries(m, sessions, placed):
    """Filas por bloque: (course_id, day, block, start, end, subject, teacher, room)."""
    rows = []
    for ses in sessions:
        if ses["id"] not in placed:
            continue
        cand, rid = placed[ses["id"]]
        c = ses["course"]
        for k in range(ses["len"]):
            bs, be = c["by_day"][cand["d"]][cand["i"] + k]
            rows.append((
                c["id"], cand["d"], cand["i"] + k, m2t(bs), m2t(be),
                ses["subject"]["id"], ses["teacher"]["id"], rid,
            ))
    return rows


def soft_score(m, sessions, placed, soft_cfg):
    score = 0
    per_course_day = defaultdict(list)
    for ses in sessions:
        if ses["id"] not in placed:
            continue
        cand, rid = placed[ses["id"]]
        per_course_day[(ses["course"]["id"], cand["d"])].append(
            (cand["i"], ses["len"], ses["subject"]["id"])
        )
    maxc = soft_cfg.get("max_consecutive", 3)
    for key, lst in per_course_day.items():
        lst.sort()
        run, run_subj, run_len = None, None, 0
        for i, L, subj in lst:
            if subj == run_subj and run is not None and i == run + 1:
                run_len += 1
            else:
                if run_subj is not None and run_len > maxc:
                    score += (run_len - maxc) * 10
                run_subj, run_len = subj, 1
            run = i + L - 1
        if run_len > maxc:
            score += (run_len - maxc) * 10
    if soft_cfg.get("spread_subjects", True):
        subj_day = defaultdict(Counter)
        for ses in sessions:
            if ses["id"] not in placed:
                continue
            cand, _ = placed[ses["id"]]
            subj_day[(ses["course"]["id"], ses["subject"]["id"])][cand["d"]] += 1
        for key, cnt in subj_day.items():
            vals = list(cnt.values())
            if len(vals) > 1:
                mean = sum(vals) / len(vals)
                score += sum((v - mean) ** 2 for v in vals) * 2
    if soft_cfg.get("avoid_end_of_day", True):
        for ses in sessions:
            if ses["id"] not in placed:
                continue
            cand, _ = placed[ses["id"]]
            if cand["i"] + ses["len"] >= ses["course"]["blocks_per_day"]:
                score += 3
    if soft_cfg.get("balance_daily", True):
        daycnt = defaultdict(Counter)
        for ses in sessions:
            if ses["id"] not in placed:
                continue
            cand, _ = placed[ses["id"]]
            daycnt[ses["course"]["id"]][cand["d"]] += 1
        for cid, cnt in daycnt.items():
            vals = list(cnt.values())
            if vals:
                mean = sum(vals) / len(vals)
                score += sum((v - mean) ** 2 for v in vals)
    tmax = soft_cfg.get("teacher_max_consecutive", 4)
    tday = defaultdict(list)
    for ses in sessions:
        if ses["id"] not in placed:
            continue
        cand, _ = placed[ses["id"]]
        tday[(ses["teacher"]["id"], cand["d"])].append((cand["i"], ses["len"]))
    for key, lst in tday.items():
        lst.sort()
        run_end, run_len = None, 0
        for i, L in lst:
            if run_end is not None and i == run_end + 1:
                run_len += 1
            else:
                if run_len > tmax:
                    score += (run_len - tmax) * 6
                run_len = 1
            run_end = i + L - 1
        if run_len > tmax:
            score += (run_len - tmax) * 6
        if soft_cfg.get("avoid_teacher_gaps", True) and len(lst) > 1:
            gaps = 0
            for a in range(1, len(lst)):
                gaps += lst[a][0] - (lst[a - 1][0] + lst[a - 1][1])
            score += gaps * 2
    return score


# ---------------------------------------------------------- diagnóstico -----
def diagnose(m, sessions, base_rooms, fail_counter, stage_msg):
    diag = []
    if stage_msg:
        diag.append(stage_msg)
    # recursos del contador de fallos
    profs, aulas = [], []
    for key, cnt in fail_counter.items():
        kind, name = key.split("|", 1)
        if kind == "profesor":
            profs.append((cnt, name))
        else:
            aulas.append((cnt, name))
    profs.sort(reverse=True)
    aulas.sort(reverse=True)
    for cnt, name in profs[:5]:
        diag.append(
            "El profesor %s se queda sin bloques libres en la combinación solicitada "
            "(aparece en %d intentos fallidos)." % (name, cnt)
        )
    for cnt, name in aulas[:5]:
        diag.append(
            "El aula %s se queda sin bloques libres (aparece en %d intentos fallidos); "
            "probablemente dos cursos la requieren a la misma hora." % (name, cnt)
        )
    # saturación estructural
    for t in m.teachers.values():
        h, cap = t.get("_hours", 0), t.get("_cap", 0)
        if cap and h / cap >= 0.9:
            diag.append(
                "Profesor saturado: %s tiene %d horas de %d bloques disponibles (%d%% de ocupación)."
                % (t["name"], h, cap, round(100 * h / cap))
            )
    needed_by_type = Counter()
    for a in m.assignments:
        s = m.subjects.get(a["subject_id"])
        if s and s["room_type"]:
            needed_by_type[s["room_type"]] += a["hours"]
    for rt, needed in needed_by_type.items():
        rooms = [r for r in m.classrooms.values() if r["room_type"] == rt]
        cap = 0
        for r in rooms:
            by_day = defaultdict(list)
            for c in m.courses.values():
                for (d, i, s, e) in c["blocks"]:
                    if window_covers(r["availability"], d, s, e):
                        by_day[d].append((s, e))
            for d, lst in by_day.items():
                merged = []
                for s, e in sorted(lst):
                    if merged and s < merged[-1][1]:
                        merged[-1] = (merged[-1][0], max(merged[-1][1], e))
                    else:
                        merged.append((s, e))
                cap += greedy_max_slots(merged)
        if cap and needed / cap >= 0.8:
            diag.append(
                "%s saturada: %d horas requeridas de %d bloques disponibles (%d%%)."
                % (room_type_label(rt), needed, cap, round(100 * needed / cap))
            )
    for c in m.courses.values():
        cap = c["blocks_per_day"] * len(c["days"])
        if cap and c["need"] / cap >= 1.0:
            diag.append(
                "El curso %s exige %d horas en una jornada de %d bloques: "
                "cualquier restricción extra lo vuelve imposible." % (c["label"], c["need"], cap)
            )
    if not diag:
        diag.append(
            "La combinación de restricciones (disponibilidad de profesores, aulas especiales y "
            "jornadas) no admite ninguna distribución válida. Revise disponibilidades o reduzca "
            "intensidades horarias."
        )
    return diag


# --------------------------------------------------------- generación -------
def generate(conn, name=None):
    m = load_model(conn)
    soft_cfg = m.school["config"].get("soft", {})
    gen_cfg = m.school["config"].get("generation", {})
    result = {
        "status": "failed",
        "message": "NO ES POSIBLE GENERAR UN HORARIO VÁLIDO",
        "errors": [], "warnings": [], "diagnostics": [],
        "stats": {}, "schedule_id": None,
    }

    base_rooms = assign_base_rooms(m, result["errors"])
    errors, warnings = prevalidate(m, base_rooms)
    result["errors"].extend(errors)
    result["warnings"].extend(warnings)
    if result["errors"]:
        result["diagnostics"] = list(result["errors"])
        result["schedule_id"] = save_failed(conn, name, result)
        return result

    sessions = build_sessions(m, soft_cfg)
    cerr = compute_static_candidates(m, sessions, base_rooms)
    if cerr:
        result["errors"] = cerr
        result["diagnostics"] = cerr
        result["schedule_id"] = save_failed(conn, name, result)
        return result

    stats_total = {}
    entries = None
    diag = None
    try:
        entries, st = solve(m, sessions, base_rooms, soft_cfg, gen_cfg, seed=1)
        stats_total.update(st)
        stats_total["soft_blocks_relaxed"] = False
    except SearchFailure as ex:
        diag = ex.args[0]
        # relajar bloques blandos (3+ horas) y reintentar; los dobles duros se conservan
        sessions2 = relax_soft_pairs(m, sessions, soft_cfg)
        cerr2 = compute_static_candidates(m, sessions2, base_rooms)
        if not cerr2:
            try:
                entries, st = solve(m, sessions2, base_rooms, soft_cfg, gen_cfg, seed=2)
                stats_total.update(st)
                stats_total["soft_blocks_relaxed"] = True
                diag = None
            except SearchFailure as ex2:
                diag = ex2.args[0]

    if entries is None:
        result["diagnostics"] = diag or ["No fue posible construir ninguna solución."]
        result["schedule_id"] = save_failed(conn, name, result)
        return result

    result["status"] = "ok"
    result["message"] = "Horario generado correctamente"
    result["stats"] = stats_total
    if stats_total.get("soft_blocks_relaxed"):
        result["warnings"].append(
            "Se relajó la preferencia de bloques automáticos de 3+ horas para lograr la solución "
            "(regla blanda: nunca rompe reglas duras)."
        )
    result["schedule_id"] = save_success(conn, name or auto_name(), entries, stats_total)
    return result


def auto_name():
    return "Horario " + time.strftime("%Y-%m-%d %H:%M")


def save_failed(conn, name, result):
    cur = conn.execute(
        "INSERT INTO schedules (name, status, message, diagnostics, stats) VALUES (?,?,?,?,?)",
        (name or auto_name(), "failed", result["message"],
         db.dumps({"errors": result["errors"], "diagnostics": result["diagnostics"],
                   "warnings": result["warnings"]}),
         db.dumps(result.get("stats", {}))),
    )
    conn.commit()
    return cur.lastrowid


def save_success(conn, name, rows, stats):
    cur = conn.execute(
        "INSERT INTO schedules (name, status, message, diagnostics, stats, is_current) VALUES (?,?,?,?,?,1)",
        (name, "ok", "Horario generado correctamente", "[]", db.dumps(stats)),
    )
    sid = cur.lastrowid
    conn.execute("UPDATE schedules SET is_current = 0 WHERE id != ?", (sid,))
    conn.executemany(
        "INSERT INTO schedule_entries (schedule_id, course_id, day, block_index, start_time,"
        " end_time, subject_id, teacher_id, classroom_id) VALUES (?,?,?,?,?,?,?,?,?)",
        [(sid,) + tuple(r) for r in rows],
    )
    conn.commit()
    return sid
