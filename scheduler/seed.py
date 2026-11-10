"""Datos de prueba: un colegio completo con Primaria y Secundaria."""
from . import db

WEEK = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]


def avail(start, end, days=None, off=()):
    days = days or WEEK
    return {d: {"on": d not in off, "start": start, "end": end} for d in days}


def clear(conn):
    conn.execute("DELETE FROM schedule_entries")
    conn.execute("DELETE FROM schedules")
    conn.execute("DELETE FROM assignments")
    conn.execute("DELETE FROM courses")
    conn.execute("DELETE FROM grades")
    conn.execute("DELETE FROM levels")
    conn.execute("DELETE FROM teachers")
    conn.execute("DELETE FROM subjects")
    conn.execute("DELETE FROM classrooms")
    conn.execute(
        "UPDATE school SET name=?, description=?, config=?, break_start=NULL, break_end=NULL",
        ("Mi Colegio", "", db.dumps(db.DEFAULT_CONFIG)),
    )
    conn.commit()


def new_school(conn, name="Mi Colegio"):
    clear(conn)
    conn.execute("UPDATE school SET name=? WHERE id=1", (name,))
    conn.commit()


def seed_demo(conn, reset=True):
    if reset:
        clear(conn)
    conn.execute(
        "UPDATE school SET name=?, description=?, config=?, break_start=?, break_end=? WHERE id=1",
        (
            "Colegio San Martín (demo)",
            "Colegio de ejemplo con Primaria y Secundaria, aulas especiales y bloques dobles.",
            db.dumps({
                "soft": {
                    "block_pref_3plus": "auto",
                    "max_consecutive": 3,
                    "spread_subjects": True,
                    "avoid_end_of_day": True,
                    "balance_daily": True,
                    "avoid_teacher_gaps": True,
                    "teacher_max_consecutive": 4,
                },
                "generation": {"attempts": 6, "time_limit": 25, "improve_time": 5},
            }),
            "10:00",
            "10:30",
        ),
    )

    # ------------------------------------------------------------ niveles
    # Un unico descanso global (school.break_start/break_end) aplica a todos
    # los niveles: nadie tiene clase durante la pausa (alumnos ni maestros).
    lid_prim = conn.execute(
        "INSERT INTO levels (name, entry_time, exit_time, blocks_per_day, block_minutes, days, order_index)"
        " VALUES (?,?,?,?,?,?,0)",
        ("Primaria", "07:00", "12:30", 5, 60, db.dumps(WEEK)),
    ).lastrowid
    lid_sec = conn.execute(
        "INSERT INTO levels (name, entry_time, exit_time, blocks_per_day, block_minutes, days, order_index)"
        " VALUES (?,?,?,?,?,?,1)",
        ("Secundaria", "07:00", "13:30", 6, 60, db.dumps(WEEK)),
    ).lastrowid

    # ------------------------------------------------- grados y cursos
    def grade(level_id, name, idx):
        return conn.execute(
            "INSERT INTO grades (level_id, name, order_index) VALUES (?,?,?)",
            (level_id, name, idx),
        ).lastrowid

    def course(gid, name, students):
        return conn.execute(
            "INSERT INTO courses (grade_id, name, students) VALUES (?,?,?)",
            (gid, name, students),
        ).lastrowid

    grades, courses = {}, {}
    for i in range(1, 6):
        g = grade(lid_prim, "%d°" % i, i - 1)
        grades["%d" % i] = g
        courses["%dA" % i] = course(g, "A", 30 + (i % 3))
    for i in range(6, 12):
        g = grade(lid_sec, "%d°" % i, i - 6)
        grades["%d" % i] = g
        courses["%dA" % i] = course(g, "A", 28 + (i % 4))

    # ---------------------------------------------------------- aulas
    def room(name, kind, rt, notes="", allowed_subj=None, start="07:00", end="13:30", off=()):
        return conn.execute(
            "INSERT INTO classrooms (name, kind, room_type, capacity, allowed_subjects,"
            " allowed_courses, availability, notes) VALUES (?,?,?,?,?,?,?,?)",
            (name, kind, rt, 0, db.dumps(allowed_subj) if allowed_subj else None,
             None, db.dumps(avail(start, end, off=off)), notes),
        ).lastrowid

    # aulas especiales primero para referenciar sus ids
    r_sistemas = room("Sala de Sistemas", "special", "sistemas",
                      "Informática, Diseño y Animación")
    r_lab = room("Laboratorio de Química", "special", "laboratorio",
                 "Química y Física")
    r_cancha = room("Cancha", "special", "cancha", "Educación Física")
    r_taller = room("Taller", "special", "taller", "Taller PER")

    # ------------------------------------------------------ asignaturas
    def subj(name, hours, rt=None, dbl=0, pref="auto", color="#4f8ef7"):
        return conn.execute(
            "INSERT INTO subjects (name, default_hours, room_type, double_block,"
            " soft_block_pref, color) VALUES (?,?,?,?,?,?)",
            (name, hours, rt, dbl, pref, color),
        ).lastrowid

    S = {}
    S["mate"] = subj("Matemáticas", 5, None, 0, "prefer", "#e5484d")
    S["espanol"] = subj("Español", 4, None, 0, "auto", "#f76b15")
    S["ingles"] = subj("Inglés", 3, None, 0, "auto", "#30a46c")
    S["cnat"] = subj("Ciencias Naturales", 3, None, 0, "auto", "#0090ff")
    S["sociales"] = subj("Sociales", 3, None, 0, "auto", "#8e4ec6")
    S["edfis"] = subj("Educación Física", 2, "cancha", 0, "none", "#f5d90a")
    S["musica"] = subj("Música", 2, None, 0, "none", "#ff62c0")
    S["arte"] = subj("Arte", 2, None, 0, "none", "#d6409f")
    S["inform"] = subj("Informática", 2, "sistemas", 1, "none", "#0091b5")
    S["diseno"] = subj("Diseño", 2, "sistemas", 0, "none", "#6e56cf")
    S["anim"] = subj("Animación", 2, "sistemas", 0, "none", "#e93d82")
    S["taller"] = subj("Taller PER", 2, "taller", 0, "none", "#8da4ef")
    S["quimica"] = subj("Química", 2, "laboratorio", 1, "none", "#12a594")
    S["fisica"] = subj("Física", 2, "laboratorio", 1, "none", "#0e7490")
    S["bio"] = subj("Biología", 1, None, 0, "none", "#46a758")

    # restringir aulas especiales a sus asignaturas (reglas duras configurables)
    conn.execute("UPDATE classrooms SET allowed_subjects=? WHERE id=?",
                 (db.dumps([S["inform"], S["diseno"], S["anim"]]), r_sistemas))
    conn.execute("UPDATE classrooms SET allowed_subjects=? WHERE id=?",
                 (db.dumps([S["quimica"], S["fisica"]]), r_lab))
    conn.execute("UPDATE classrooms SET allowed_subjects=? WHERE id=?",
                 (db.dumps([S["edfis"]]), r_cancha))
    conn.execute("UPDATE classrooms SET allowed_subjects=? WHERE id=?",
                 (db.dumps([S["taller"]]), r_taller))

    # salones normales (la disponibilidad vacía o total permite cualquier jornada)
    for i in range(101, 106):
        room("Salón %d" % i, "normal", None, "Primaria", start="07:00", end="12:30")
    for i in range(201, 207):
        room("Salón %d" % i, "normal", None, "Secundaria", start="07:00", end="13:30")

    # ------------------------------------------------------- profesores
    def teacher(name, subjects, hours_range, notes="", off=()):
        return conn.execute(
            "INSERT INTO teachers (name, subjects, min_hours, max_hours, notes, availability)"
            " VALUES (?,?,?,?,?,?)",
            (name, db.dumps(subjects), 0, 0, notes, db.dumps(avail(*hours_range, off=off))),
        ).lastrowid

    P = {}
    prim_win = ("07:00", "12:30")
    full_win = ("07:00", "13:30")
    P["marta"] = teacher("Marta López", [S["mate"], S["espanol"], S["cnat"], S["sociales"]], prim_win, "Profe de aula 1°")
    P["jorge"] = teacher("Jorge Ruiz", [S["mate"], S["espanol"], S["cnat"], S["sociales"]], prim_win, "Profe de aula 2°")
    P["ana"] = teacher("Ana Torres", [S["mate"], S["espanol"], S["cnat"], S["sociales"]], prim_win, "Profe de aula 3°")
    P["luis"] = teacher("Luis García", [S["mate"], S["espanol"], S["cnat"], S["sociales"]], prim_win, "Profe de aula 4°")
    P["diana"] = teacher("Diana Castro", [S["espanol"], S["cnat"], S["sociales"]], prim_win, "Profe de aula 5°")
    P["carlos"] = teacher("Carlos Pérez", [S["mate"]], full_win, "Da Matemáticas en Primaria y Secundaria")
    P["laura"] = teacher("Laura Gómez", [S["ingles"]], full_win, "Inglés en Primaria y Secundaria")
    P["diego"] = teacher("Diego Herrera", [S["edfis"]], prim_win, "Ed. Física Primaria")
    P["pablo"] = teacher("Pablo Soto", [S["musica"]], prim_win, "Música Primaria")
    P["sofia"] = teacher("Sofía Ramos", [S["arte"]], prim_win, "Arte Primaria (no disponible los miércoles)", off=("Miércoles",))
    P["veronica"] = teacher("Verónica Díaz", [S["mate"]], full_win)
    P["andres"] = teacher("Andrés Molina", [S["mate"]], full_win)
    P["marcela"] = teacher("Marcela Nieto", [S["espanol"]], full_win)
    P["fernanda"] = teacher("Fernanda Ríos", [S["espanol"]], full_win)
    P["camilo"] = teacher("Camilo Ortiz", [S["espanol"]], full_win)
    P["ryan"] = teacher("Ryan Miller", [S["ingles"]], full_win)
    P["gloria"] = teacher("Gloria Peña", [S["sociales"]], full_win)
    P["hugo"] = teacher("Hugo Salazar", [S["sociales"]], full_win)
    P["rosa"] = teacher("Rosa Jiménez", [S["cnat"], S["bio"]], full_win)
    P["tomas"] = teacher("Tomás Vega", [S["quimica"]], full_win)
    P["elena"] = teacher("Elena Blanco", [S["fisica"]], full_win)
    P["ricardo"] = teacher("Ricardo León", [S["edfis"]], full_win, "Ed. Física Secundaria")
    P["camila"] = teacher("Camila Soto", [S["inform"]], full_win)
    P["paula"] = teacher("Paula Cárdenas", [S["diseno"]], full_win)
    P["ivan"] = teacher("Iván Morales", [S["anim"]], full_win)
    P["nadia"] = teacher("Nadia Franco", [S["taller"]], full_win)
    P["sergio"] = teacher("Sergio Lima", [S["musica"]], full_win)

    # ------------------------------------------ asignaciones (qué da qué)
    def assign(t, s, c, hours):
        conn.execute(
            "INSERT INTO assignments (teacher_id, subject_id, course_id, hours) VALUES (?,?,?,?)",
            (t, s, c, hours),
        )

    # Primaria: 1A-4A con profe de aula, 5A con Carlos (mate) + Diana
    for k, main in (("1A", "marta"), ("2A", "jorge"), ("3A", "ana"), ("4A", "luis")):
        cid = courses[k]
        assign(P[main], S["mate"], cid, 5)
        assign(P[main], S["espanol"], cid, 4)
        assign(P[main], S["cnat"], cid, 3)
        assign(P[main], S["sociales"], cid, 3)
    cid = courses["5A"]
    assign(P["carlos"], S["mate"], cid, 5)
    assign(P["diana"], S["espanol"], cid, 4)
    assign(P["diana"], S["cnat"], cid, 3)
    assign(P["diana"], S["sociales"], cid, 3)
    for k in ("1A", "2A", "3A", "4A", "5A"):
        cid = courses[k]
        assign(P["laura"], S["ingles"], cid, 3)
        assign(P["diego"], S["edfis"], cid, 2)
        assign(P["pablo"], S["musica"], cid, 2)
        assign(P["sofia"], S["arte"], cid, 2)

    # Secundaria: base común de 21 h + ciencias (3 h) + 4 h de sala = 28 h
    mat = {"6A": "veronica", "7A": "andres", "8A": "carlos", "9A": "veronica",
           "10A": "andres", "11A": "andres"}
    esp = {"6A": "marcela", "7A": "marcela", "8A": "fernanda", "9A": "fernanda",
           "10A": "camilo", "11A": "camilo"}
    ing = {"6A": "laura", "7A": "laura", "8A": "ryan", "9A": "ryan",
           "10A": "ryan", "11A": "ryan"}
    soc = {"6A": "gloria", "7A": "gloria", "8A": "gloria", "9A": "hugo",
           "10A": "hugo", "11A": "hugo"}
    sala = {
        "6A": [(S["inform"], "camila"), (S["diseno"], "paula")],
        "7A": [(S["inform"], "camila"), (S["anim"], "ivan")],
        "8A": [(S["diseno"], "paula"), (S["anim"], "ivan")],
        "9A": [(S["inform"], "camila"), (S["diseno"], "paula")],
        "10A": [(S["inform"], "camila"), (S["anim"], "ivan")],
        "11A": [(S["diseno"], "paula"), (S["anim"], "ivan")],
    }
    sci = {
        "6A": [(S["cnat"], "rosa", 3)],
        "7A": [(S["cnat"], "rosa", 3)],
        "8A": [(S["quimica"], "tomas", 2), (S["bio"], "rosa", 1)],
        "9A": [(S["fisica"], "elena", 2), (S["bio"], "rosa", 1)],
        "10A": [(S["quimica"], "tomas", 2), (S["bio"], "rosa", 1)],
        "11A": [(S["fisica"], "elena", 2), (S["bio"], "rosa", 1)],
    }
    for k in ("6A", "7A", "8A", "9A", "10A", "11A"):
        cid = courses[k]
        assign(P[mat[k]], S["mate"], cid, 5)
        assign(P[esp[k]], S["espanol"], cid, 4)
        assign(P[ing[k]], S["ingles"], cid, 3)
        assign(P[soc[k]], S["sociales"], cid, 3)
        assign(P["ricardo"], S["edfis"], cid, 2)
        assign(P["sergio"], S["musica"], cid, 2)
        assign(P["nadia"], S["taller"], cid, 2)
        for sub, tk in sala[k]:
            assign(P[tk], sub, cid, 2)
        for sub, tk, h in sci[k]:
            assign(P[tk], sub, cid, h)

    conn.commit()
    return {
        "levels": 2, "grades": len(grades), "courses": len(courses),
        "teachers": len(P), "subjects": len(S), "rooms": 11 + 4,
        "assignments": conn.execute("SELECT COUNT(*) FROM assignments").fetchone()[0],
    }
