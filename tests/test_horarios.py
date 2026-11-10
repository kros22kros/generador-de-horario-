"""Pruebas automáticas del generador de horarios.

1) Colegio de prueba completo: generación válida + las 9 comprobaciones.
2) Casos de conflicto deliberadamente imposibles: deben detectarse con mensaje claro.
3) El validador independiente debe rechazar horarios corruptos.
"""
import os
import sys
import tempfile
import unittest
from collections import defaultdict

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scheduler import db, seed, solver, validator, exporter


def fresh_db():
    path = os.path.join(tempfile.mkdtemp(), "test.db")
    db.init_db(path)
    cn = db.connect(path)
    return cn


# ------------------------------------------------- mini-colegios para fallos --
def mini_level(cn, entry="07:00", blocks=2, minutes=60, days=("Lunes",)):
    return cn.execute(
        "INSERT INTO levels (name, entry_time, exit_time, blocks_per_day, block_minutes, days, order_index)"
        " VALUES (?,?,?,?,?,?,0)",
        ("Nivel", entry, "18:00", blocks, minutes, db.dumps(list(days))),
    ).lastrowid


def mini_grade(cn, lid, name="G"):
    return cn.execute("INSERT INTO grades (level_id, name, order_index) VALUES (?,?,0)",
                      (lid, name)).lastrowid


def mini_course(cn, gid, name, entry=None, blocks=None):
    return cn.execute(
        "INSERT INTO courses (grade_id, name, students, entry_time, blocks_per_day) VALUES (?,?,?,?,?)",
        (gid, name, 20, entry, blocks)).lastrowid


def mini_subj(cn, name, hours=1, room_type=None, dbl=0):
    return cn.execute(
        "INSERT INTO subjects (name, default_hours, room_type, double_block) VALUES (?,?,?,?)",
        (name, hours, room_type, dbl)).lastrowid


def mini_teacher(cn, name, start="07:00", end="18:00", off=()):
    av = {d: {"on": d not in off, "start": start, "end": end} for d in db.DAYS}
    return cn.execute("INSERT INTO teachers (name, subjects, availability) VALUES (?,?,?)",
                      (name, "[]", db.dumps(av))).lastrowid


def mini_room(cn, name, kind="normal", rt=None, start="07:00", end="18:00"):
    av = {d: {"on": True, "start": start, "end": end} for d in db.DAYS}
    return cn.execute(
        "INSERT INTO classrooms (name, kind, room_type, availability) VALUES (?,?,?,?)",
        (name, kind, rt, db.dumps(av))).lastrowid


def mini_assign(cn, tid, sid, cid, hours):
    cn.execute("INSERT INTO assignments (teacher_id, subject_id, course_id, hours) VALUES (?,?,?,?)",
               (tid, sid, cid, hours))
    cn.commit()


def txt(result):
    return " | ".join(result.get("errors", []) + result.get("diagnostics", []))


# ==================================================== 0. bloques y descansos ==
class TestBloquesConDescansos(unittest.TestCase):
    """La rejilla de bloques debe saltar los descansos."""

    def test_sin_descanso_es_continuo(self):
        b = db.build_blocks("07:00", 60, 5, [])
        self.assertEqual([(i, s, e) for (i, s, e) in b],
                         [(0, 420, 480), (1, 480, 540), (2, 540, 600),
                          (3, 600, 660), (4, 660, 720)])

    def test_descanso_primaria(self):
        b = db.build_blocks("07:00", 60, 5, [{"start": "10:00", "end": "10:30"}])
        self.assertEqual(b, [(0, 420, 480), (1, 480, 540), (2, 540, 600),
                             (3, 630, 690), (4, 690, 750)])
        self.assertEqual(len(b), 5)  # siguen siendo 5 bloques de clase
        for (_, s, e) in b:          # ningun bloque invade 10:00-10:30
            self.assertFalse(s < 630 and e > 600)

    def test_descanso_secundaria(self):
        b = db.build_blocks("07:00", 60, 6, [{"start": "11:00", "end": "11:30"}])
        self.assertEqual(b[-2], (4, 690, 750))   # 11:30-12:30
        self.assertEqual(b[-1], (5, 750, 810))   # 12:30-13:30
        for (_, s, e) in b:
            self.assertFalse(s < 690 and e > 660)

    def test_bloque_que_cruzaria_descanso_se_mueve(self):
        # bloque de 90' con descanso a las 08:30-09:00
        b = db.build_blocks("07:00", 90, 2, [{"start": "08:30", "end": "09:00"}])
        self.assertEqual(b[0], (0, 420, 510))    # 07:00-08:30 (termina justo antes)
        self.assertEqual(b[1], (1, 540, 630))    # 09:00-10:30


# ============================================================ 1. generación ==
class TestColegioPrueba(unittest.TestCase):
    """El colegio de demostración completo debe generar un horario 100% válido."""

    @classmethod
    def setUpClass(cls):
        cls.cn = fresh_db()
        cls.seed_stats = seed.seed_demo(cls.cn)
        cls.res = solver.generate(cls.cn, name="Horario test")
        cls.sid = cls.res.get("schedule_id")

    @classmethod
    def tearDownClass(cls):
        cls.cn.close()

    def test_genera_correctamente(self):
        self.assertEqual(self.res["status"], "ok", txt(self.res))
        self.assertIn("correctamente", self.res["message"])

    def checks(self):
        return {c["key"]: c for c in validator.validate(self.cn, self.sid)}

    # 1. no hay profesores duplicados
    def test_no_profesores_duplicados(self):
        names = [r["name"] for r in db.rows(self.cn, "SELECT name FROM teachers")]
        self.assertEqual(len(names), len(set(names)))

    # (1b) no hay aulas duplicadas
    def test_no_aulas_duplicadas(self):
        names = [r["name"] for r in db.rows(self.cn, "SELECT name FROM classrooms")]
        self.assertEqual(len(names), len(set(names)))

    # 2. ningún curso con dos materias a la vez
    def test_curso_sin_solapes(self):
        c = self.checks()["courses"]
        self.assertTrue(c["ok"], c["errors"])

    # 3. ningún profesor en dos cursos a la vez (incluye primaria vs secundaria)
    def test_profesor_sin_solapes(self):
        c = self.checks()["teachers"]
        self.assertTrue(c["ok"], c["errors"])

    # 4. aulas sin solapes (incluye Sala de Sistemas)
    def test_aulas_sin_solapes(self):
        for key in ("rooms", "room_sistemas"):
            c = self.checks()[key]
            self.assertTrue(c["ok"], (key, c["errors"]))

    # 5. laboratorio exclusivo
    def test_laboratorio_exclusivo(self):
        c = self.checks()["room_laboratorio"]
        self.assertTrue(c["ok"], c["errors"])

    # 6. intensidad horaria exacta por curso y asignatura
    def test_intensidad_horaria(self):
        c = self.checks()["hours"]
        self.assertTrue(c["ok"], c["errors"])
        esperado = {}
        for a in db.rows(self.cn, "SELECT * FROM assignments"):
            esperado[(a["course_id"], a["subject_id"])] = esperado.get(
                (a["course_id"], a["subject_id"]), 0) + a["hours"]
        obtenido = {}
        for e in db.rows(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=?", (self.sid,)):
            k = (e["course_id"], e["subject_id"])
            obtenido[k] = obtenido.get(k, 0) + 1
        self.assertEqual(esperado, obtenido)

    # 7. se respetan jornadas (días, bloques y horas de cada curso)
    def test_jornada_respetada(self):
        c = self.checks()["schedule_window"]
        self.assertTrue(c["ok"], c["errors"])

    # 8. bloques dobles consecutivos (Informática, Química, Física)
    def test_bloques_dobles(self):
        c = self.checks()["double_blocks"]
        self.assertTrue(c["ok"], c["errors"])
        dobles = [s for s in db.rows(self.cn, "SELECT * FROM subjects WHERE double_block=1")]
        self.assertTrue(dobles, "El seed debe incluir asignaturas con bloque doble")

    # 8b. descanso GLOBAL del colegio: primaria, secundaria y maestros a la vez
    def test_descansos_respetados(self):
        c = self.checks()["breaks"]
        self.assertTrue(c["ok"], c["errors"])
        sch = db.row(self.cn, "SELECT break_start, break_end FROM school WHERE id=1")
        self.assertTrue(sch["break_start"] and sch["break_end"],
                        "El seed debe definir el descanso del colegio")
        ws, we = db.t2m(sch["break_start"]), db.t2m(sch["break_end"])
        self.assertGreater(we, ws)
        # ningun curso de ningun nivel tiene clase dentro de la pausa
        for e in db.rows(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=?", (self.sid,)):
            s, en = db.t2m(e["start_time"]), db.t2m(e["end_time"])
            self.assertFalse(s < we and en > ws, "clase %s-%s dentro del descanso" % (e["start_time"], e["end_time"]))
        # los bloques de clase quedan enteros antes o despues de la pausa
        starts = [db.t2m(r["s"]) for r in db.rows(self.cn, """
            SELECT DISTINCT e.start_time AS s FROM schedule_entries e
            WHERE e.schedule_id=? ORDER BY e.start_time""", (self.sid,))]
        for s in starts:
            self.assertTrue(s <= ws or s >= we,
                            "bloque %02d:%02d cruza el descanso" % (s // 60, s % 60))
        # Tras la pausa ambos niveles retoman (bloques post-descanso presentes)
        blk = defaultdict(set)
        for r in db.rows(self.cn, """
            SELECT l.name AS lvl, e.start_time AS s FROM schedule_entries e
            JOIN courses c ON c.id=e.course_id JOIN grades g ON g.id=c.grade_id
            JOIN levels l ON l.id=g.level_id WHERE e.schedule_id=?
            ORDER BY e.start_time""", (self.sid,)):
            blk[r["lvl"]].add(db.t2m(r["s"]))
        self.assertIn(630, blk["Primaria"])     # 10:30 retoma Primaria
        self.assertIn(690, blk["Secundaria"])   # 11:30 retoma Secundaria
        self.assertNotIn(ws, blk["Primaria"] | blk["Secundaria"])
        # cada maestro queda libre durante el descanso (ninguna clase en la pausa)
        for e in db.rows(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=?", (self.sid,)):
            s, en = db.t2m(e["start_time"]), db.t2m(e["end_time"])
            self.assertFalse(s < we and en > ws,
                             "el maestro de la clase %s-%s dicta durante el descanso"
                             % (e["start_time"], e["end_time"]))

    # 9. disponibilidad de profesores y aulas
    def test_disponibilidades(self):
        for key in ("teacher_availability", "room_availability"):
            c = self.checks()[key]
            self.assertTrue(c["ok"], (key, c["errors"]))

    # además: la validación completa debe pasar
    def test_validacion_completa(self):
        checks = validator.validate(self.cn, self.sid)
        fallas = [c for c in checks if not c["ok"]]
        self.assertFalse(fallas, [(c["label"], c["errors"]) for c in fallas])
        self.assertGreaterEqual(len(checks), 10)

    # primaria y secundaria coexisten con bloques distintos
    def test_primaria_y_secundaria(self):
        niveles = {r["name"] for r in db.rows(self.cn, "SELECT * FROM levels")}
        self.assertIn("Primaria", niveles)
        self.assertIn("Secundaria", niveles)
        rows = db.rows(self.cn, """
            SELECT l.name AS nivel, MIN(e.start_time) AS ini, MAX(e.end_time) AS fin
            FROM schedule_entries e
            JOIN courses c ON c.id=e.course_id JOIN grades g ON g.id=c.grade_id
            JOIN levels l ON l.id=g.level_id
            WHERE e.schedule_id=? GROUP BY l.name""", (self.sid,))
        self.assertEqual(len(rows), 2)
        fin = {r["nivel"]: r["fin"] for r in rows}
        self.assertLessEqual(fin["Secundaria"], "13:30")
        self.assertLess(fin["Primaria"], "13:00")

    def test_no_horas_faltantes_ni_sobrantes(self):
        cap = {}
        for r in db.rows(self.cn, """
            SELECT c.id, c.blocks_per_day, c.days, g.name || ' ' || c.name AS label
            FROM courses c JOIN grades g ON g.id=c.grade_id"""):
            pass  # capacidad exacta ya cubierta por test_intensidad + jornada
        c = self.checks()["hours"]
        self.assertTrue(c["ok"])

    def test_exportadores_funcionan(self):
        xlsx = exporter.to_xlsx(self.cn, self.sid)
        self.assertGreater(len(xlsx), 1000)
        self.assertTrue(xlsx[:2] == b"PK")
        csvtxt = exporter.to_csv(self.cn, self.sid, "general")
        self.assertIn("Bloque", csvtxt)
        pdf = exporter.to_pdf(self.cn, self.sid)
        self.assertEqual(pdf[:4], b"%PDF")
        v = exporter.build_view(self.cn, self.sid, "general")
        self.assertTrue(v["rows"])


# ====================================================== 2. casos de conflicto ==
class TestCasosDeConflicto(unittest.TestCase):
    """Demuestran que el sistema NO rellena tablas al azar: detecta imposibilidades."""

    def setUp(self):
        self.cn = fresh_db()

    def tearDown(self):
        self.cn.close()

    # Caso 1: dos cursos necesitan al mismo profesor al mismo tiempo
    def test_conflicto_profesor(self):
        cn = self.cn
        lid = mini_level(cn, blocks=1)
        gid = mini_grade(cn, lid)
        ca = mini_course(cn, gid, "A")
        cb = mini_course(cn, gid, "B")
        s1 = mini_subj(cn, "Matemáticas", 1)
        s2 = mini_subj(cn, "Español", 1)
        t = mini_teacher(cn, "Profesor Único")
        mini_room(cn, "Salón 1"); mini_room(cn, "Salón 2")
        mini_assign(cn, t, s1, ca, 1)
        mini_assign(cn, t, s2, cb, 1)
        res = solver.generate(cn, name="caso1")
        self.assertEqual(res["status"], "failed")
        self.assertIn("profesor", txt(res).lower())

    # Caso 2: dos cursos necesitan el laboratorio a la misma vez
    def test_conflicto_laboratorio(self):
        cn = self.cn
        lid = mini_level(cn, blocks=1)
        gid = mini_grade(cn, lid)
        ca = mini_course(cn, gid, "A")
        cb = mini_course(cn, gid, "B")
        q = mini_subj(cn, "Química", 1, room_type="laboratorio")
        f = mini_subj(cn, "Física", 1, room_type="laboratorio")
        t1 = mini_teacher(cn, "Profesor Q")
        t2 = mini_teacher(cn, "Profesor F")
        mini_room(cn, "Salón 1"); mini_room(cn, "Salón 2")
        mini_room(cn, "Laboratorio", kind="special", rt="laboratorio")
        mini_assign(cn, t1, q, ca, 1)
        mini_assign(cn, t2, f, cb, 1)
        res = solver.generate(cn, name="caso2")
        self.assertEqual(res["status"], "failed")
        self.assertIn("laboratorio", txt(res).lower())

    # Caso 3: tres cursos, una sola Sala de Sistemas, mismo bloque
    def test_conflicto_sala_sistemas(self):
        cn = self.cn
        lid = mini_level(cn, blocks=1)
        gid = mini_grade(cn, lid)
        cursos = [mini_course(cn, gid, n) for n in ("A", "B", "C")]
        subs = [mini_subj(cn, n, 1, room_type="sistemas")
                for n in ("Informática", "Diseño", "Animación")]
        teachers = [mini_teacher(cn, "P%d" % i) for i in range(3)]
        mini_room(cn, "Salón 1"); mini_room(cn, "Salón 2"); mini_room(cn, "Salón 3")
        mini_room(cn, "Sala de Sistemas", kind="special", rt="sistemas")
        for i in range(3):
            mini_assign(cn, teachers[i], subs[i], cursos[i], 1)
        res = solver.generate(cn, name="caso3")
        self.assertEqual(res["status"], "failed")
        self.assertIn("sala de sistemas", txt(res).lower())

    # Caso 4: un curso necesita más horas que su jornada permite
    def test_horas_insuficientes(self):
        cn = self.cn
        lid = mini_level(cn, blocks=5)   # jornada: 5 bloques (1 día)
        gid = mini_grade(cn, lid)
        c = mini_course(cn, gid, "A")
        s = mini_subj(cn, "Matemáticas", 10)
        t = mini_teacher(cn, "Profesor")
        mini_room(cn, "Salón 1")
        mini_assign(cn, t, s, c, 10)     # 10 h > 5 bloques
        res = solver.generate(cn, name="caso4")
        self.assertEqual(res["status"], "failed")
        joined = txt(res).lower()
        self.assertTrue("jornada" in joined or "5 bloques" in joined, joined)

    # Caso 5: un profesor tiene más horas que su disponibilidad
    def test_disponibilidad_insuficiente(self):
        cn = self.cn
        lid = mini_level(cn, blocks=4)
        gid = mini_grade(cn, lid)
        c = mini_course(cn, gid, "A")
        s = mini_subj(cn, "Matemáticas", 4)
        t = mini_teacher(cn, "Profesor Ocupado", start="07:00", end="08:00")  # 1 bloque
        mini_room(cn, "Salón 1")
        mini_assign(cn, t, s, c, 4)
        res = solver.generate(cn, name="caso5")
        self.assertEqual(res["status"], "failed")
        joined = txt(res).lower()
        self.assertTrue("dispo" in joined, joined)  # "disponibilidad"/"dispone"

    # Caso 6: solapamiento parcial de jornadas — solo falla DURANTE la búsqueda
    def test_conflicto_parcial_en_busqueda(self):
        cn = self.cn
        # A: 7:00-8:00, 8:00-9:00   B: 7:30-8:30, 8:30-9:30  (solape parcial)
        lid = mini_level(cn, entry="07:00", blocks=2)
        gid = mini_grade(cn, lid)
        ca = mini_course(cn, gid, "A")
        cb = mini_course(cn, gid, "B", entry="07:30")
        sa = mini_subj(cn, "AsigA", 1)
        sb = mini_subj(cn, "AsigB", 1)
        t = mini_teacher(cn, "Profesor Cruz", start="07:30", end="09:30")
        mini_room(cn, "Salón 1"); mini_room(cn, "Salón 2")
        mini_assign(cn, t, sa, ca, 1)
        mini_assign(cn, t, sb, cb, 1)
        # la validación previa pasa (2 horas, 2 huecos compatibles por separado),
        # pero durante la búsqueda los huecos se solapan siempre.
        res = solver.generate(cn, name="caso6")
        self.assertEqual(res["status"], "failed")
        self.assertIn("profesor", txt(res).lower())

    # Caso 7: un curso con doble asignatura en el mismo bloque es imposible
    def test_curso_sobrecargado(self):
        cn = self.cn
        lid = mini_level(cn, blocks=3)
        gid = mini_grade(cn, lid)
        c = mini_course(cn, gid, "A")
        s1 = mini_subj(cn, "Mate", 2)
        s2 = mini_subj(cn, "Español", 2)
        t1 = mini_teacher(cn, "P1")
        t2 = mini_teacher(cn, "P2")
        mini_room(cn, "Salón 1")
        mini_assign(cn, t1, s1, c, 2)
        mini_assign(cn, t2, s2, c, 2)   # 4 h > 3 bloques
        res = solver.generate(cn, name="caso7")
        self.assertEqual(res["status"], "failed")
        self.assertIn("jornada", txt(res).lower())

    # Caso 8: asignatura que exige un aula especial inexistente
    def test_aula_especial_inexistente(self):
        cn = self.cn
        lid = mini_level(cn, blocks=2)
        gid = mini_grade(cn, lid)
        c = mini_course(cn, gid, "A")
        s = mini_subj(cn, "Química", 2, room_type="laboratorio")
        t = mini_teacher(cn, "P")
        mini_room(cn, "Salón 1")
        mini_assign(cn, t, s, c, 2)
        res = solver.generate(cn, name="caso8")
        self.assertEqual(res["status"], "failed")
        self.assertIn("laboratorio", txt(res).lower())


# ============================================ 3. validador independiente =====
class TestValidadorDetectaCorrupcion(unittest.TestCase):
    """Si alguien (o un bug) deja un horario mal, la validación lo rechaza."""

    @classmethod
    def setUpClass(cls):
        cls.cn = fresh_db()
        seed.seed_demo(cls.cn)
        cls.ok = solver.generate(cls.cn, name="base")
        cls.sid = cls.ok["schedule_id"]

    @classmethod
    def tearDownClass(cls):
        cls.cn.close()

    def _checks(self, sid):
        return {c["key"]: c for c in validator.validate(self.cn, sid)}

    def test_horario_valido_pasa_todo(self):
        self.assertFalse([c for c in self._checks(self.sid).values() if not c["ok"]])

    def test_detecta_profesor_duplicado(self):
        e = db.rows(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=? LIMIT 2", (self.sid,))[0]
        cur = self.cn.execute(
            "INSERT INTO schedule_entries (schedule_id, course_id, day, block_index, start_time,"
            " end_time, subject_id, teacher_id, classroom_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.sid, 9999, e["day"], e["block_index"], e["start_time"], e["end_time"],
             e["subject_id"], e["teacher_id"], e["classroom_id"]))
        self.cn.commit()
        checks = self._checks(self.sid)
        self.assertFalse(checks["teachers"]["ok"], "Debe detectar al profesor duplicado")
        self.cn.execute("DELETE FROM schedule_entries WHERE id=?", (cur.lastrowid,))
        self.cn.commit()

    def test_detecta_aula_ocupada_dos_cursos(self):
        e = db.rows(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=? LIMIT 1", (self.sid,))[0]
        otro_curso = db.row(self.cn, "SELECT id FROM courses WHERE id != ?", (e["course_id"],))["id"]
        cur = self.cn.execute(
            "INSERT INTO schedule_entries (schedule_id, course_id, day, block_index, start_time,"
            " end_time, subject_id, teacher_id, classroom_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.sid, otro_curso, e["day"], e["block_index"], e["start_time"], e["end_time"],
             e["subject_id"], e["teacher_id"], e["classroom_id"]))
        self.cn.commit()
        checks = self._checks(self.sid)
        self.assertFalse(checks["rooms"]["ok"], "Debe detectar el aula ocupada a la vez")
        self.cn.execute("DELETE FROM schedule_entries WHERE id=?", (cur.lastrowid,))
        self.cn.commit()

    def test_detecta_horas_faltantes(self):
        e = db.row(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=? LIMIT 1", (self.sid,))
        self.cn.execute("DELETE FROM schedule_entries WHERE id=?", (e["id"],))
        self.cn.commit()
        checks = self._checks(self.sid)
        self.assertFalse(checks["hours"]["ok"], "Debe detectar la hora faltante")
        self.cn.execute(
            "INSERT INTO schedule_entries (schedule_id, course_id, day, block_index, start_time,"
            " end_time, subject_id, teacher_id, classroom_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.sid, e["course_id"], e["day"], e["block_index"], e["start_time"], e["end_time"],
             e["subject_id"], e["teacher_id"], e["classroom_id"]))
        self.cn.commit()


    def test_detecta_clase_en_descanso(self):
        # el descanso GLOBAL del colegio no debe admitir clases para nadie
        sch = db.row(self.cn, "SELECT break_start, break_end FROM school WHERE id=1")
        e = db.row(self.cn, "SELECT * FROM schedule_entries WHERE schedule_id=? LIMIT 1", (self.sid,))
        cur = self.cn.execute(
            "INSERT INTO schedule_entries (schedule_id, course_id, day, block_index, start_time,"
            " end_time, subject_id, teacher_id, classroom_id) VALUES (?,?,?,?,?,?,?,?,?)",
            (self.sid, e["course_id"], e["day"], 99, sch["break_start"], sch["break_end"],
             e["subject_id"], e["teacher_id"], e["classroom_id"]))
        self.cn.commit()
        checks = self._checks(self.sid)
        self.assertFalse(checks["breaks"]["ok"], "Debe detectar una clase dentro del descanso")
        self.cn.execute("DELETE FROM schedule_entries WHERE id=?", (cur.lastrowid,))
        self.cn.commit()


if __name__ == "__main__":
    unittest.main(verbosity=2)
