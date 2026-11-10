import json
import os
import shutil
import sqlite3

BUNDLED_DB = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "horarios.db")

if os.environ.get("VERCEL"):
    # En Vercel el sistema de archivos es de solo lectura salvo /tmp.
    # Copiamos la base incluida en el despliegue a /tmp para poder escribir.
    DB_PATH = os.environ.get("DB_PATH") or "/tmp/horarios.db"
    try:
        os.makedirs(os.path.dirname(DB_PATH) or ".", exist_ok=True)
    except OSError:
        pass
    if not os.path.exists(DB_PATH) and os.path.exists(BUNDLED_DB):
        try:
            shutil.copyfile(BUNDLED_DB, DB_PATH)
        except OSError:
            pass
else:
    DB_PATH = os.environ.get("DB_PATH") or BUNDLED_DB

DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes", "Sábado", "Domingo"]
DEFAULT_DAYS = ["Lunes", "Martes", "Miércoles", "Jueves", "Viernes"]

DEFAULT_CONFIG = {
    "soft": {
        "block_pref_3plus": "auto",
        "max_consecutive": 3,
        "spread_subjects": True,
        "avoid_end_of_day": True,
        "balance_daily": True,
        "avoid_teacher_gaps": True,
        "teacher_max_consecutive": 4,
    },
    "generation": {"attempts": 6, "time_limit": 20, "improve_time": 6},
}

SCHEMA = """
CREATE TABLE IF NOT EXISTS school (
  id INTEGER PRIMARY KEY CHECK (id = 1),
  name TEXT NOT NULL,
  description TEXT DEFAULT '',
  config TEXT NOT NULL DEFAULT '{}',
  break_start TEXT,
  break_end TEXT
);
CREATE TABLE IF NOT EXISTS levels (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  entry_time TEXT NOT NULL DEFAULT '07:00',
  exit_time TEXT NOT NULL DEFAULT '13:00',
  blocks_per_day INTEGER NOT NULL DEFAULT 6,
  block_minutes INTEGER NOT NULL DEFAULT 60,
  days TEXT NOT NULL DEFAULT '["Lunes","Martes","Miércoles","Jueves","Viernes"]',
  order_index INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS grades (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  level_id INTEGER NOT NULL REFERENCES levels(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  order_index INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS courses (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  grade_id INTEGER NOT NULL REFERENCES grades(id) ON DELETE CASCADE,
  name TEXT NOT NULL,
  students INTEGER NOT NULL DEFAULT 0,
  entry_time TEXT,
  exit_time TEXT,
  blocks_per_day INTEGER,
  block_minutes INTEGER,
  days TEXT,
  base_room_id INTEGER
);
CREATE TABLE IF NOT EXISTS teachers (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  subjects TEXT NOT NULL DEFAULT '[]',
  min_hours INTEGER NOT NULL DEFAULT 0,
  max_hours INTEGER NOT NULL DEFAULT 0,
  notes TEXT DEFAULT '',
  availability TEXT NOT NULL DEFAULT '{}'
);
CREATE TABLE IF NOT EXISTS classrooms (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  kind TEXT NOT NULL DEFAULT 'normal',
  room_type TEXT,
  capacity INTEGER NOT NULL DEFAULT 0,
  allowed_subjects TEXT,
  allowed_courses TEXT,
  availability TEXT NOT NULL DEFAULT '{}',
  notes TEXT DEFAULT ''
);
CREATE TABLE IF NOT EXISTS subjects (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  default_hours INTEGER NOT NULL DEFAULT 2,
  room_type TEXT,
  double_block INTEGER NOT NULL DEFAULT 0,
  soft_block_pref TEXT NOT NULL DEFAULT 'auto',
  color TEXT NOT NULL DEFAULT '#4f8ef7'
);
CREATE TABLE IF NOT EXISTS assignments (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  teacher_id INTEGER NOT NULL REFERENCES teachers(id) ON DELETE CASCADE,
  subject_id INTEGER NOT NULL REFERENCES subjects(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL REFERENCES courses(id) ON DELETE CASCADE,
  hours INTEGER NOT NULL DEFAULT 1,
  UNIQUE(teacher_id, subject_id, course_id)
);
CREATE TABLE IF NOT EXISTS schedules (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  name TEXT NOT NULL,
  status TEXT NOT NULL DEFAULT 'ok',
  message TEXT DEFAULT '',
  diagnostics TEXT NOT NULL DEFAULT '[]',
  stats TEXT NOT NULL DEFAULT '{}',
  created_at TEXT NOT NULL DEFAULT (datetime('now','localtime')),
  is_current INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE IF NOT EXISTS schedule_entries (
  id INTEGER PRIMARY KEY AUTOINCREMENT,
  schedule_id INTEGER NOT NULL REFERENCES schedules(id) ON DELETE CASCADE,
  course_id INTEGER NOT NULL,
  day TEXT NOT NULL,
  block_index INTEGER NOT NULL,
  start_time TEXT NOT NULL,
  end_time TEXT NOT NULL,
  subject_id INTEGER NOT NULL,
  teacher_id INTEGER NOT NULL,
  classroom_id INTEGER
);
CREATE INDEX IF NOT EXISTS idx_entries_schedule ON schedule_entries(schedule_id);
CREATE INDEX IF NOT EXISTS idx_assign_course ON assignments(course_id);
CREATE INDEX IF NOT EXISTS idx_assign_teacher ON assignments(teacher_id);
"""


def connect(db_path=None):
    conn = sqlite3.connect(db_path or DB_PATH)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def init_db(db_path=None):
    path = db_path or DB_PATH
    fresh = not os.path.exists(path)
    conn = connect(path)
    conn.executescript(SCHEMA)
    _migrate(conn)
    row = conn.execute("SELECT id FROM school WHERE id = 1").fetchone()
    if row is None:
        conn.execute(
            "INSERT INTO school (id, name, description, config) VALUES (1, ?, '', ?)",
            ("Mi Colegio", json.dumps(DEFAULT_CONFIG, ensure_ascii=False)),
        )
    conn.commit()
    conn.close()
    return fresh


def _table_columns(conn, table):
    return [r[1] for r in conn.execute("PRAGMA table_info(%s)" % table).fetchall()]


def _migrate(conn):
    """Agrega columnas que falten en bases de datos creadas por versiones previas.

    El descanso pasa a ser Global (para todo el colegio, incluidos los maestros),
    por lo que se elimina el concepto de descanso por nivel/curso.
    """
    scol = _table_columns(conn, "school")
    if "break_start" not in scol:
        conn.execute("ALTER TABLE school ADD COLUMN break_start TEXT")
    if "break_end" not in scol:
        conn.execute("ALTER TABLE school ADD COLUMN break_end TEXT")

    # bases antiguas: convertir el primer descanso por nivel en el global
    if "breaks" in _table_columns(conn, "levels"):
        s = conn.execute("SELECT break_start, break_end FROM school WHERE id=1").fetchone()
        if not s or not (s["break_start"] and s["break_end"]):
            first = conn.execute(
                "SELECT breaks FROM levels WHERE breaks IS NOT NULL AND breaks != ''"
                " ORDER BY order_index, id LIMIT 1").fetchone()
            if first:
                b = jload(first["breaks"], [])
                if b:
                    start = b[0].get("start") or "10:00"
                    end = b[0].get("end") or "11:00"
                    conn.execute("UPDATE school SET break_start=?, break_end=? WHERE id=1",
                                 (start, end))
    for table in ("levels", "courses"):
        if "breaks" in _table_columns(conn, table):
            conn.execute("ALTER TABLE %s DROP COLUMN breaks" % table)


def school_break(conn):
    """Descanso global del colegio como ventana (min, min) o None."""
    s = row(conn, "SELECT break_start, break_end FROM school WHERE id=1")
    if not s or not s.get("break_start") or not s.get("break_end"):
        return None
    ws, we = t2m(s["break_start"]), t2m(s["break_end"])
    if we <= ws:
        return None
    return (ws, we)


def t2m(s):
    try:
        h, m = str(s).split(":")
        return int(h) * 60 + int(m)
    except Exception:
        return 0


def parse_breaks(v):
    """Normaliza descansos (listas de dicts {'start','end'} o de tuplas (min,min))
    a ventanas (min, min)."""
    if isinstance(v, str):
        v = jload(v, [])
    wins = []
    for b in (v or []):
        if isinstance(b, (tuple, list)) and len(b) == 2:
            ws, we = b
        elif isinstance(b, dict):
            s, e = b.get("start"), b.get("end")
            if not s or not e:
                continue
            ws, we = t2m(s), t2m(e)
        else:
            continue
        if we > ws:
            wins.append((ws, we))
    return sorted(wins)


def build_blocks(entry, block_minutes, blocks_per_day, breaks):
    """Bloques de clase (indice, inicio, fin) en minutos, saltando los descansos.

    Un descanso es una ventana sin clases: ningun bloque la invade, de modo que
    ni alumnos ni profesores tienen clase durante el descanso. Si un bloque
    quedaria partido por un descanso, se coloca entero despues de la pausa.
    """
    bm = int(block_minutes or 60)
    bpd = int(blocks_per_day or 0)
    wins = parse_breaks(breaks)
    out = []
    cur = t2m(entry)
    i = 0
    guard = 0
    while i < bpd and guard < 100000:
        guard += 1
        e = cur + bm
        jump = None
        for (ws, we) in wins:
            if cur < we and e > ws:          # el bloque se solapa con el descanso
                jump = we if jump is None else max(jump, we)
        if jump is not None:
            cur = jump
            continue
        out.append((i, cur, e))
        cur = e
        i += 1
    return out


def rows(conn, sql, params=()):
    return [dict(r) for r in conn.execute(sql, params).fetchall()]


def row(conn, sql, params=()):
    r = conn.execute(sql, params).fetchone()
    return dict(r) if r else None


def dumps(v):
    return json.dumps(v, ensure_ascii=False)


def jload(v, default=None):
    if v is None or v == "":
        return default
    try:
        return json.loads(v)
    except Exception:
        return default


def get_school(conn):
    s = row(conn, "SELECT * FROM school WHERE id = 1")
    if s:
        s["config"] = jload(s["config"], {})
        cfg = json.loads(json.dumps(DEFAULT_CONFIG))
        deep_merge(cfg, s["config"] or {})
        s["config"] = cfg
    return s


def deep_merge(base, extra):
    for k, v in (extra or {}).items():
        if isinstance(v, dict) and isinstance(base.get(k), dict):
            deep_merge(base[k], v)
        else:
            base[k] = v
