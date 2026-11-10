"""Generador Automático de Horarios Académicos — API y servidor web."""
import io
import json
import os
import time

from flask import Flask, jsonify, request, send_file, send_from_directory

from scheduler import db, seed as seedmod
from scheduler import solver, validator, exporter

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
app = Flask(__name__, static_folder=os.path.join(BASE_DIR, "static"), static_url_path="/static")

db.init_db()


def conn():
    return db.connect()


@app.errorhandler(Exception)
def on_error(e):
    from werkzeug.exceptions import HTTPException
    if isinstance(e, HTTPException):
        return e
    return jsonify({"error": str(e)}), 500


# ------------------------------------------------------------ utilidades ----
JSON_FIELDS = {
    "levels": ["days"],
    "courses": ["days"],
    "teachers": ["subjects", "availability"],
    "classrooms": ["allowed_subjects", "allowed_courses", "availability"],
    "subjects": [],
    "grades": [],
    "assignments": [],
}

LIST_SQL = {
    "levels": "SELECT * FROM levels ORDER BY order_index, id",
    "grades": ("SELECT g.*, l.name AS level_name FROM grades g JOIN levels l ON l.id=g.level_id"
               " ORDER BY l.order_index, g.order_index"),
    "courses": ("SELECT c.*, g.name AS grade_name, l.name AS level_name, l.id AS level_id,"
                " b.name AS base_room_name FROM courses c"
                " JOIN grades g ON g.id=c.grade_id JOIN levels l ON l.id=g.level_id"
                " LEFT JOIN classrooms b ON b.id=c.base_room_id"
                " ORDER BY l.order_index, g.order_index, c.name"),
    "teachers": "SELECT * FROM teachers ORDER BY name",
    "subjects": "SELECT * FROM subjects ORDER BY name",
    "classrooms": "SELECT * FROM classrooms ORDER BY kind DESC, room_type, name",
    "assignments": ("SELECT a.*, t.name AS teacher_name, s.name AS subject_name, s.color AS subject_color,"
                    " g.name AS grade_name, co.name AS course_name,"
                    " (g.name || ' ' || co.name) AS course_label"
                    " FROM assignments a JOIN teachers t ON t.id=a.teacher_id"
                    " JOIN subjects s ON s.id=a.subject_id"
                    " JOIN courses co ON co.id=a.course_id JOIN grades g ON g.id=co.grade_id"
                    " ORDER BY g.name, co.name, s.name"),
}

INT_FIELDS = {"levels": ["blocks_per_day", "block_minutes", "order_index"],
              "grades": ["order_index"],
              "courses": ["students", "blocks_per_day", "block_minutes"],
              "teachers": ["min_hours", "max_hours"],
              "classrooms": ["capacity"],
              "subjects": ["default_hours", "double_block"],
              "assignments": ["hours"]}


def decorate(table, rowd):
    for f in JSON_FIELDS.get(table, []):
        rowd[f] = db.jload(rowd.get(f), None if f in ("allowed_subjects", "allowed_courses") else {})
        if f in ("allowed_subjects", "allowed_courses") and rowd[f] == []:
            rowd[f] = None
    if table == "courses":
        grades = db.rows(db.connect(), "SELECT * FROM grades")
        rowd["need"] = 0
    return rowd


def course_extra(c, conn):
    c["need"] = db.row(conn, "SELECT COALESCE(SUM(hours),0) AS n FROM assignments WHERE course_id=?",
                       (c["id"],))["n"]
    lvl = db.row(conn, "SELECT * FROM levels WHERE id=?", (c["level_id"],))
    if lvl:
        c["entry"] = c["entry_time"] or lvl["entry_time"]
        c["exit"] = c["exit_time"] or lvl["exit_time"]
        c["effective_blocks"] = c["blocks_per_day"] or lvl["blocks_per_day"]
        c["effective_days"] = db.jload(c["days"]) or db.jload(lvl["days"])
        c["capacity"] = c["effective_blocks"] * len(c["effective_days"])
    return c


# ------------------------------------------------------------------ CRUD ----
@app.get("/api/<table>")
def list_rows(table):
    if table not in LIST_SQL:
        return jsonify({"error": "Tabla desconocida"}), 404
    cn = conn()
    data = db.rows(cn, LIST_SQL[table])
    if table == "courses":
        data = [course_extra(r, cn) for r in data]
    else:
        data = [decorate(table, r) for r in data]
    if table == "teachers":
        for t in data:
            t["hours"] = db.row(cn, "SELECT COALESCE(SUM(hours),0) AS n FROM assignments WHERE teacher_id=?",
                                (t["id"],))["n"]
    cn.close()
    return jsonify(data)


@app.post("/api/<table>")
def create_row(table):
    if table not in JSON_FIELDS:
        return jsonify({"error": "Tabla desconocida"}), 404
    data = request.get_json(force=True)
    return jsonify(write_row(table, None, data))


@app.put("/api/<table>/<int:rid>")
def update_row(table, rid):
    if table not in JSON_FIELDS:
        return jsonify({"error": "Tabla desconocida"}), 404
    data = request.get_json(force=True)
    return jsonify(write_row(table, rid, data))


def write_row(table, rid, data):
    fields = data
    for f in JSON_FIELDS[table]:
        if f in fields and isinstance(fields[f], (list, dict)):
            fields[f] = db.dumps(fields[f])
        if f in fields and fields[f] is None:
            fields[f] = None
    for f in INT_FIELDS.get(table, []):
        if f in fields and fields[f] not in (None, ""):
            try:
                fields[f] = int(fields[f])
            except (TypeError, ValueError):
                fields[f] = 0
        elif f in fields and fields[f] == "":
            fields[f] = None
    if table == "grades" and "level_id" not in fields and rid is None:
        raise ValueError("level_id requerido")
    if table == "courses" and "grade_id" not in fields and rid is None:
        raise ValueError("grade_id requerido")
    cn = conn()
    try:
        if rid is None:
            cols = ",".join(fields.keys())
            ph = ",".join("?" * len(fields))
            cur = cn.execute("INSERT INTO %s (%s) VALUES (%s)" % (table, cols, ph),
                             tuple(fields.values()))
            rid = cur.lastrowid
        else:
            sets = ",".join("%s=?" % k for k in fields)
            cn.execute("UPDATE %s SET %s WHERE id=?" % (table, sets),
                       tuple(fields.values()) + (rid,))
        cn.commit()
    finally:
        cn.close()
    cn = conn()
    out = db.row(cn, "SELECT * FROM %s WHERE id=?" % table, (rid,))
    cn.close()
    return out


@app.delete("/api/<table>/<int:rid>")
def delete_row(table, rid):
    if table not in JSON_FIELDS:
        return jsonify({"error": "Tabla desconocida"}), 404
    cn = conn()
    cn.execute("DELETE FROM %s WHERE id=?" % table, (rid,))
    cn.commit()
    cn.close()
    return jsonify({"ok": True})


# ----------------------------------------------------------------- escuela --
@app.get("/api/school")
def get_school():
    cn = conn()
    s = db.get_school(cn)
    s["counts"] = {
        t: db.row(cn, "SELECT COUNT(*) AS n FROM %s" % t)["n"]
        for t in ("levels", "grades", "courses", "teachers", "subjects", "classrooms", "assignments")
    }
    cn.close()
    return jsonify(s)


@app.put("/api/school")
def update_school():
    data = request.get_json(force=True)
    cn = conn()
    if "name" in data or "description" in data:
        cn.execute("UPDATE school SET name=?, description=? WHERE id=1",
                   (data.get("name", "Mi Colegio"), data.get("description", "")))
    if "break_start" in data or "break_end" in data:
        cn.execute("UPDATE school SET break_start=?, break_end=? WHERE id=1",
                   (data.get("break_start") or None, data.get("break_end") or None))
    if "config" in data:
        cn.execute("UPDATE school SET config=? WHERE id=1", (db.dumps(data["config"]),))
    cn.commit()
    cn.close()
    return jsonify(db.get_school(conn()))


@app.get("/api/meta")
def meta():
    return jsonify({
        "days": db.DAYS,
        "weekdays": db.DEFAULT_DAYS,
        "room_types": [
            {"value": "sistemas", "label": "Sala de Sistemas"},
            {"value": "laboratorio", "label": "Laboratorio"},
            {"value": "cancha", "label": "Cancha / Polideportivo"},
            {"value": "taller", "label": "Taller"},
        ],
        "soft_prefs": [
            {"value": "prefer", "label": "Preferir bloques"},
            {"value": "auto", "label": "Automático"},
            {"value": "none", "label": "No usar bloques"},
        ],
    })


# -------------------------------------------------------------- generación --
@app.post("/api/generate")
def generate():
    body = request.get_json(silent=True) or {}
    cn = conn()
    try:
        res = solver.generate(cn, name=body.get("name"))
    finally:
        cn.close()
    return jsonify(res)


@app.get("/api/schedules")
def schedules():
    cn = conn()
    data = db.rows(cn, "SELECT * FROM schedules ORDER BY id DESC")
    for s in data:
        d = db.jload(s["diagnostics"], {})
        s["diagnostics"] = d if isinstance(d, dict) else {"diagnostics": d}
        s["stats"] = db.jload(s["stats"], {})
        s["entries"] = db.row(cn, "SELECT COUNT(*) AS n FROM schedule_entries WHERE schedule_id=?",
                              (s["id"],))["n"]
    cn.close()
    return jsonify(data)


@app.get("/api/schedules/<int:sid>")
def schedule_detail(sid):
    cn = conn()
    s = db.row(cn, "SELECT * FROM schedules WHERE id=?", (sid,))
    if not s:
        cn.close()
        return jsonify({"error": "No existe"}), 404
    s["diagnostics"] = db.jload(s["diagnostics"], {})
    s["stats"] = db.jload(s["stats"], {})
    s["entries"] = db.rows(cn, "SELECT * FROM schedule_entries WHERE schedule_id=?", (sid,))
    cn.close()
    return jsonify(s)


@app.delete("/api/schedules/<int:sid>")
def delete_schedule(sid):
    cn = conn()
    cn.execute("DELETE FROM schedules WHERE id=?", (sid,))
    cn.commit()
    cn.close()
    return jsonify({"ok": True})


@app.post("/api/schedules/<int:sid>/rename")
def rename_schedule(sid):
    name = (request.get_json(force=True) or {}).get("name", "")
    cn = conn()
    cn.execute("UPDATE schedules SET name=? WHERE id=?", (name, sid))
    cn.commit()
    cn.close()
    return jsonify({"ok": True})


@app.get("/api/schedules/<int:sid>/view")
def schedule_view(sid):
    v = request.args.get("type", "curso")
    oid = request.args.get("id", type=int)
    cn = conn()
    try:
        data = exporter.build_view(cn, sid, v, oid)
    finally:
        cn.close()
    return jsonify(data)


@app.get("/api/schedules/<int:sid>/validation")
def schedule_validation(sid):
    cn = conn()
    try:
        checks = validator.validate(cn, sid)
    finally:
        cn.close()
    ok = all(c["ok"] for c in checks)
    return jsonify({"ok": ok, "checks": checks})


@app.get("/api/schedules/<int:sid>/selects")
def schedule_selects(sid):
    """Listas para los selectores de la vista de horario."""
    cn = conn()
    used_t = {r["teacher_id"] for r in db.rows(
        cn, "SELECT DISTINCT teacher_id FROM schedule_entries WHERE schedule_id=?", (sid,))}
    used_r = {r["classroom_id"] for r in db.rows(
        cn, "SELECT DISTINCT classroom_id FROM schedule_entries WHERE schedule_id=? AND classroom_id IS NOT NULL",
        (sid,))}
    used_c = {r["course_id"] for r in db.rows(
        cn, "SELECT DISTINCT course_id FROM schedule_entries WHERE schedule_id=?", (sid,))}
    out = {
        "courses": [{"id": r["id"], "label": "%s %s" % (r["grade_name"], r["name"])}
                    for r in db.rows(cn, LIST_SQL["courses"]) if r["id"] in used_c],
        "teachers": [{"id": t["id"], "label": t["name"]}
                     for t in db.rows(cn, "SELECT * FROM teachers ORDER BY name") if t["id"] in used_t],
        "rooms": [{"id": r["id"], "label": "%s (%s)" % (r["name"], r["room_type"] or "normal")}
                  for r in db.rows(cn, "SELECT * FROM classrooms ORDER BY kind DESC, name")
                  if r["id"] in used_r],
    }
    cn.close()
    return jsonify(out)


# --------------------------------------------------------------- export -----
def _send(data, filename, mimetype):
    return send_file(io.BytesIO(data), mimetype=mimetype, as_attachment=True, download_name=filename)


@app.get("/api/export/xlsx")
def export_xlsx():
    sid = request.args.get("schedule_id", type=int)
    cn = conn()
    try:
        data = exporter.to_xlsx(cn, sid)
        name = exporter.schedule_name(cn, sid)
    finally:
        cn.close()
    return _send(data, "horario_%s.xlsx" % name.replace(" ", "_"), "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")


@app.get("/api/export/csv")
def export_csv():
    sid = request.args.get("schedule_id", type=int)
    view = request.args.get("view", "general")
    oid = request.args.get("id", type=int)
    cn = conn()
    try:
        data = exporter.to_csv(cn, sid, view, oid)
        name = exporter.schedule_name(cn, sid)
    finally:
        cn.close()
    return _send(data.encode("utf-8-sig"), "horario_%s_%s.csv" % (name.replace(" ", "_"), view), "text/csv")


@app.get("/api/export/pdf")
def export_pdf():
    sid = request.args.get("schedule_id", type=int)
    cn = conn()
    try:
        data = exporter.to_pdf(cn, sid)
        name = exporter.schedule_name(cn, sid)
    finally:
        cn.close()
    return _send(data, "horario_%s.pdf" % name.replace(" ", "_"), "application/pdf")


# ------------------------------------------------------- datos de prueba ----
@app.post("/api/seed")
def do_seed():
    cn = conn()
    try:
        stats = seedmod.seed_demo(cn, reset=True)
    finally:
        cn.close()
    return jsonify({"ok": True, "stats": stats})


@app.post("/api/clear")
def do_clear():
    body = request.get_json(silent=True) or {}
    cn = conn()
    try:
        seedmod.new_school(cn, name=body.get("name", "Mi Colegio"))
    finally:
        cn.close()
    return jsonify({"ok": True})


@app.get("/api/config/export")
def config_export():
    cn = conn()
    out = {"school": db.get_school(cn)}
    for t in ("levels", "grades", "courses", "teachers", "subjects", "classrooms", "assignments"):
        out[t] = db.rows(cn, "SELECT * FROM %s" % t)
    cn.close()
    return jsonify(out)


@app.post("/api/config/import")
def config_import():
    data = request.get_json(force=True)
    cn = conn()
    try:
        seedmod.clear(cn)
        s = data.get("school", {})
        cn.execute("UPDATE school SET name=?, description=?, config=?, break_start=?, break_end=? WHERE id=1",
                   (s.get("name", "Mi Colegio"), s.get("description", ""),
                    db.dumps(s.get("config", db.DEFAULT_CONFIG)),
                    s.get("break_start"), s.get("break_end")))
        # compatibilidad con exports antiguos: el descanso vivia en niveles
        if not s.get("break_start") or not s.get("break_end"):
            for r in data.get("levels", []):
                b = r.get("breaks")
                if isinstance(b, str):
                    b = db.jload(b, [])
                if b:
                    cn.execute("UPDATE school SET break_start=?, break_end=? WHERE id=1",
                               (b[0].get("start"), b[0].get("end")))
                    break
        idmap = {}
        for r in data.get("levels", []):
            cur = cn.execute(
                "INSERT INTO levels (name, entry_time, exit_time, blocks_per_day, block_minutes, days, order_index)"
                " VALUES (?,?,?,?,?,?,?)",
                (r["name"], r["entry_time"], r["exit_time"], r["blocks_per_day"], r["block_minutes"],
                 r.get("days") if isinstance(r.get("days"), str) else db.dumps(r.get("days", db.DEFAULT_DAYS)),
                 r.get("order_index", 0)))
            idmap[("levels", r["id"])] = cur.lastrowid
        for r in data.get("grades", []):
            cur = cn.execute("INSERT INTO grades (level_id, name, order_index) VALUES (?,?,?)",
                             (idmap[("levels", r["level_id"])], r["name"], r.get("order_index", 0)))
            idmap[("grades", r["id"])] = cur.lastrowid
        for r in data.get("classrooms", []):
            cur = cn.execute(
                "INSERT INTO classrooms (name, kind, room_type, capacity, allowed_subjects, allowed_courses, availability, notes)"
                " VALUES (?,?,?,?,?,?,?,?)",
                (r["name"], r.get("kind", "normal"), r.get("room_type"), r.get("capacity") or 0,
                 r.get("allowed_subjects") if isinstance(r.get("allowed_subjects"), str) else
                 (db.dumps(r["allowed_subjects"]) if r.get("allowed_subjects") else None),
                 r.get("allowed_courses") if isinstance(r.get("allowed_courses"), str) else
                 (db.dumps(r["allowed_courses"]) if r.get("allowed_courses") else None),
                 r.get("availability") if isinstance(r.get("availability"), str) else
                 db.dumps(r.get("availability", {})),
                 r.get("notes", "")))
            idmap[("classrooms", r["id"])] = cur.lastrowid
        for r in data.get("subjects", []):
            cur = cn.execute(
                "INSERT INTO subjects (name, default_hours, room_type, double_block, soft_block_pref, color)"
                " VALUES (?,?,?,?,?,?)",
                (r["name"], r.get("default_hours", 2), r.get("room_type"), r.get("double_block") or 0,
                 r.get("soft_block_pref", "auto"), r.get("color", "#4f8ef7")))
            idmap[("subjects", r["id"])] = cur.lastrowid
        for r in data.get("teachers", []):
            cur = cn.execute(
                "INSERT INTO teachers (name, subjects, min_hours, max_hours, notes, availability) VALUES (?,?,?,?,?,?)",
                (r["name"],
                 r.get("subjects") if isinstance(r.get("subjects"), str) else db.dumps(r.get("subjects", [])),
                 r.get("min_hours") or 0, r.get("max_hours") or 0, r.get("notes", ""),
                 r.get("availability") if isinstance(r.get("availability"), str) else db.dumps(r.get("availability", {}))))
            idmap[("teachers", r["id"])] = cur.lastrowid
        for r in data.get("courses", []):
            cur = cn.execute(
                "INSERT INTO courses (grade_id, name, students, entry_time, exit_time, blocks_per_day, block_minutes, days, base_room_id)"
                " VALUES (?,?,?,?,?,?,?,?,?)",
                (idmap[("grades", r["grade_id"])], r["name"], r.get("students") or 0,
                 r.get("entry_time"), r.get("exit_time"), r.get("blocks_per_day"),
                 r.get("block_minutes"),
                 r.get("days") if isinstance(r.get("days"), str) else
                 (db.dumps(r["days"]) if r.get("days") else None),
                 idmap.get(("classrooms", r.get("base_room_id")))))
            idmap[("courses", r["id"])] = cur.lastrowid

        def remap_ids(value, table):
            if not value:
                return []
            if isinstance(value, str):
                parsed = db.jload(value, [])
            else:
                parsed = value
            return [idmap.get((table, old), old) for old in parsed]

        for r in data.get("teachers", []):
            new_id = idmap[("teachers", r["id"])]
            subs = remap_ids(r.get("subjects"), "subjects")
            cn.execute("UPDATE teachers SET subjects=? WHERE id=?",
                       (db.dumps(subs) if subs else None, new_id))
        for r in data.get("classrooms", []):
            new_id = idmap[("classrooms", r["id"])]
            asub = remap_ids(r.get("allowed_subjects"), "subjects")
            acrs = remap_ids(r.get("allowed_courses"), "courses")
            cn.execute("UPDATE classrooms SET allowed_subjects=?, allowed_courses=? WHERE id=?",
                       (db.dumps(asub) if asub else None,
                        db.dumps(acrs) if acrs else None, new_id))
        for r in data.get("assignments", []):
            cn.execute("INSERT INTO assignments (teacher_id, subject_id, course_id, hours) VALUES (?,?,?,?)",
                       (idmap[("teachers", r["teacher_id"])], idmap[("subjects", r["subject_id"])],
                        idmap[("courses", r["course_id"])], r.get("hours", 1)))
        cn.commit()
    except Exception as e:
        cn.rollback()
        cn.close()
        return jsonify({"error": "Error importando configuración: %s" % e}), 400
    cn.close()
    return jsonify({"ok": True})


# ----------------------------------------------------------------- inicio ---
@app.get("/")
def index():
    return send_from_directory(app.static_folder, "index.html")


if __name__ == "__main__":
    # En local escucha solo en 127.0.0.1; en plataformas de hosting se usa
    # la variable PORT y se expone en 0.0.0.0.
    port = int(os.environ.get("PORT", "5000"))
    host = os.environ.get("HOST") or ("0.0.0.0" if os.environ.get("PORT") else "127.0.0.1")
    print("=" * 60)
    print("  Generador de Horarios Académicos")
    print("  Abra http://127.0.0.1:%d en su navegador" % port)
    print("=" * 60)
    app.run(host=host, port=port, debug=False)
