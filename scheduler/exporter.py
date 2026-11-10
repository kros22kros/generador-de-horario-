"""Vistas del horario y exportación a XLSX / CSV / PDF."""
import csv
import io
from collections import defaultdict

from openpyxl import Workbook
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from fpdf import FPDF
from fpdf.fonts import FontFace

from . import db
from .solver import t2m


def schedule_name(conn, sid):
    s = db.row(conn, "SELECT name FROM schedules WHERE id=?", (sid,))
    return s["name"] if s else "horario"


def course_meta(conn):
    grades = {r["id"]: r for r in db.rows(conn, "SELECT * FROM grades")}
    levels = {r["id"]: r for r in db.rows(conn, "SELECT * FROM levels")}
    sb = db.school_break(conn)
    breaks = [sb] if sb else []
    meta = {}
    for c in db.rows(conn, "SELECT * FROM courses"):
        g = grades.get(c["grade_id"])
        if not g:
            continue
        lvl = levels.get(g["level_id"])
        entry = c["entry_time"] or lvl["entry_time"]
        bpd = c["blocks_per_day"] or lvl["blocks_per_day"]
        bm = c["block_minutes"] or lvl["block_minutes"]
        days = db.jload(c["days"]) or db.jload(lvl["days"]) or list(db.DEFAULT_DAYS)
        blocks = []
        for d in days:
            for (i, s, e) in db.build_blocks(entry, bm, bpd, breaks):
                blocks.append((d, i, s, e))
        meta[c["id"]] = {
            "label": "%s %s" % (g["name"], c["name"]),
            "days": days, "blocks": blocks, "bpd": bpd, "level": lvl["name"],
            "breaks": db.parse_breaks(breaks),
        }
    return meta


def entries_of(conn, sid):
    return db.rows(conn, """
        SELECT e.*, s.name AS subject, s.color AS color, t.name AS teacher,
               r.name AS room, r.room_type AS room_type,
               g.name AS grade, c.name AS course_name
        FROM schedule_entries e
        JOIN subjects s ON s.id=e.subject_id
        JOIN teachers t ON t.id=e.teacher_id
        JOIN courses c ON c.id=e.course_id
        JOIN grades g ON g.id=c.grade_id
        LEFT JOIN classrooms r ON r.id=e.classroom_id
        WHERE e.schedule_id=?
        ORDER BY e.start_time, g.name, c.name""", (sid,))


def _cell_text(e, mode):
    base = "%s · %s" % (e["subject"], e["teacher"])
    if mode == "curso":
        if e["room_type"]:
            return "%s (%s)" % (e["subject"], e["room"])
        return e["subject"]
    if mode == "profesor":
        return "%s %s %s" % (e["subject"], e["grade"], e["course_name"])
    if mode == "aula":
        return "%s %s %s" % (e["grade"], e["course_name"], e["subject"])
    return "%s%s · %s · %s" % (e["grade"], e["course_name"], e["subject"], e["teacher"])


def build_view(conn, sid, view="curso", oid=None):
    meta = course_meta(conn)
    ents = entries_of(conn, sid)
    if view in ("curso", "profesor", "aula"):
        key = {"curso": "course_id", "profesor": "teacher_id", "aula": "classroom_id"}[view]
        ents = [e for e in ents if e[key] == oid]
    if not ents:
        return {"title": "Sin clases", "days": [], "rows": []}

    course_ids = {e["course_id"] for e in ents}
    ivs = set()
    breaks = set()
    for cid in course_ids:
        for (d, i, s, e) in meta[cid]["blocks"]:
            ivs.add((s, e))
        for (ws, we) in meta[cid].get("breaks", []):
            breaks.add((ws, we))
    ivs |= breaks
    rows_sorted = sorted(ivs)
    days_order = [d for d in db.DAYS if any(m["days"].count(d) for m in meta.values())]
    used_days = []
    for d in db.DAYS:
        if any(e["day"] == d for e in ents) or view == "curso":
            if view == "curso":
                cd = meta[list(course_ids)[0]]["days"]
                if d in cd:
                    used_days.append(d)
            else:
                used_days.append(d)
    if not used_days:
        used_days = db.DEFAULT_DAYS

    grid = {}
    for e in ents:
        k = (t2m(e["start_time"]), t2m(e["end_time"]), e["day"])
        grid.setdefault(k, []).append(e)

    title = "Horario"
    if view == "curso" and oid in meta:
        title = "Curso %s" % meta[oid]["label"]
    elif view == "profesor":
        title = "Profesor: %s" % (ents[0]["teacher"])
    elif view == "aula":
        title = "Aula: %s" % (ents[0]["room"] or "?")
    elif view == "general":
        title = "Horario general del colegio"

    rows = []
    for (s, e) in rows_sorted:
        is_break = (s, e) in breaks
        cells = {}
        for d in used_days:
            if is_break:
                cells[d] = [{"text": "Descanso", "color": "#e2e2e2", "room": None, "room_type": None}]
                continue
            lst = grid.get((s, e, d), [])
            cells[d] = [
                {"text": _cell_text(x, view), "color": x["color"] or "#4f8ef7",
                 "room": x["room"], "room_type": x["room_type"]}
                for x in lst
            ]
        rows.append({"label": "DESCANSO %02d:%02d - %02d:%02d" % (s // 60, s % 60, e // 60, e % 60)
                     if is_break else "%02d:%02d - %02d:%02d" % (s // 60, s % 60, e // 60, e % 60),
                     "cells": cells, "is_break": is_break})
    return {"title": title, "days": used_days, "rows": rows}


# ------------------------------------------------------------------- CSV ----
def to_csv(conn, sid, view, oid=None):
    v = build_view(conn, sid, view, oid)
    buf = io.StringIO()
    w = csv.writer(buf, delimiter=";")
    w.writerow([v["title"]])
    w.writerow(["Bloque"] + v["days"])
    for r in v["rows"]:
        line = []
        for d in v["days"]:
            cells = r["cells"].get(d, [])
            line.append(" | ".join(c["text"] for c in cells))
        w.writerow([r["label"]] + line)
    return buf.getvalue()


# ------------------------------------------------------------------ XLSX ----
THIN = Border(*[Side(style="thin", color="B0B8C4")] * 4)
HEAD_FILL = PatternFill("solid", fgColor="1F3A5F")
HEAD_FONT = Font(bold=True, color="FFFFFF")
TITLE_FONT = Font(bold=True, size=13, color="1F3A5F")


def _write_table(ws, view, start_row, title=None):
    r = start_row
    if title:
        ws.cell(row=r, column=1, value=title).font = TITLE_FONT
        r += 1
    if not view["days"]:
        return r
    ws.cell(row=r, column=1, value="Bloque")
    for j, d in enumerate(view["days"], start=2):
        ws.cell(row=r, column=j, value=d)
    for j in range(1, len(view["days"]) + 2):
        c = ws.cell(row=r, column=j)
        c.fill = HEAD_FILL
        c.font = HEAD_FONT
        c.alignment = Alignment(horizontal="center")
        c.border = THIN
    r += 1
    for row in view["rows"]:
        ws.cell(row=r, column=1, value=row["label"]).border = THIN
        for j, d in enumerate(view["days"], start=2):
            cells = row["cells"].get(d, [])
            c = ws.cell(row=r, column=j, value="\n".join(x["text"] for x in cells) or None)
            c.alignment = Alignment(wrap_text=True, vertical="top")
            c.border = THIN
            if cells:
                c.fill = PatternFill("solid", fgColor=(cells[0]["color"] or "FFFFFF")[1:] if len(cells[0].get("color") or "") == 7 else "FFFFFF")
                c.font = Font(bold=True, color="FFFFFF")
        r += 1
    return r + 2


def to_xlsx(conn, sid):
    meta = course_meta(conn)
    ents = entries_of(conn, sid)
    wb = Workbook()

    # --- General
    ws = wb.active
    ws.title = "General"
    ws.column_dimensions["A"].width = 18
    for j in range(2, 12):
        ws.column_dimensions[chr(64 + j)].width = 34
    v = build_view(conn, sid, "general")
    _write_table(ws, v, 1, "%s — Vista general" % schedule_name(conn, sid))

    # --- Por curso
    ws = wb.create_sheet("Por curso")
    ws.column_dimensions["A"].width = 18
    for j in range(2, 12):
        ws.column_dimensions[chr(64 + j)].width = 30
    r = 1
    for cid in sorted(meta, key=lambda c: meta[c]["label"]):
        vc = build_view(conn, sid, "curso", cid)
        if vc["rows"]:
            r = _write_table(ws, vc, r, "CURSO %s" % meta[cid]["label"])

    # --- Por profesor
    ws = wb.create_sheet("Por profesor")
    ws.column_dimensions["A"].width = 18
    for j in range(2, 12):
        ws.column_dimensions[chr(64 + j)].width = 30
    r = 1
    teachers = db.rows(conn, "SELECT * FROM teachers ORDER BY name")
    for t in teachers:
        vt = build_view(conn, sid, "profesor", t["id"])
        if vt["rows"]:
            r = _write_table(ws, vt, r, "PROFESOR %s" % t["name"])

    # --- Por aula
    ws = wb.create_sheet("Por aula")
    ws.column_dimensions["A"].width = 18
    for j in range(2, 12):
        ws.column_dimensions[chr(64 + j)].width = 30
    r = 1
    rooms = db.rows(conn, "SELECT * FROM classrooms ORDER BY kind DESC, name")
    for room in rooms:
        vr = build_view(conn, sid, "aula", room["id"])
        if vr["rows"]:
            r = _write_table(ws, vr, r, "AULA %s" % room["name"])

    out = io.BytesIO()
    wb.save(out)
    return out.getvalue()


# ------------------------------------------------------------------- PDF ----
class PDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("helvetica", "I", 8)
            self.cell(0, 6, self.title_txt, align="L")
            self.ln(8)

    def footer(self):
        self.set_y(-12)
        self.set_font("helvetica", "I", 8)
        self.cell(0, 8, "Pagina %d" % self.page_no(), align="C")


def _pdf_table(pdf, view, title):
    if not view["rows"]:
        return
    pdf.set_font("helvetica", "B", 11)
    pdf.cell(0, 7, title, new_x="LMARGIN", new_y="NEXT")
    n = max(len(view["days"]), 1)
    width = pdf.w - pdf.l_margin - pdf.r_margin
    pdf.set_font("helvetica", "", 7)
    pdf.set_draw_color(140, 150, 165)
    heading_style = FontFace(emphasis="BOLD", color=255, fill_color=(70, 90, 120))
    with pdf.table(width=width, text_align="CENTER", line_height=3.8,
                    first_row_as_headings=True, headings_style=heading_style) as table:
        hr = table.row()
        hr.cell("Bloque")
        for d in view["days"]:
            hr.cell(d)
        for row in view["rows"]:
            tr = table.row()
            tr.cell(row["label"])
            for d in view["days"]:
                tr.cell("\n".join(c["text"] for c in row["cells"].get(d, [])) or "-")
    pdf.ln(4)


def to_pdf(conn, sid):
    name = schedule_name(conn, sid)
    meta = course_meta(conn)
    pdf = PDF(orientation="L", unit="mm", format="A4")
    pdf.title_txt = "Horario %s" % name
    pdf.set_auto_page_break(True, margin=15)
    pdf.add_page()
    pdf.set_font("helvetica", "B", 18)
    pdf.cell(0, 12, "Horario Academico", align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.set_font("helvetica", "", 12)
    pdf.cell(0, 8, name, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(4)

    v = build_view(conn, sid, "general")
    _pdf_table(pdf, v, "VISTA GENERAL")
    for cid in sorted(meta, key=lambda c: meta[c]["label"]):
        vc = build_view(conn, sid, "curso", cid)
        if not vc["rows"]:
            continue
        pdf.add_page()
        _pdf_table(pdf, vc, "CURSO %s" % meta[cid]["label"])
    return bytes(pdf.output())
