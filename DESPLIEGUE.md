# Generador de Horarios Académicos — Guía de despliegue

Este proyecto se puede usar de tres formas. Elige la que necesites.

---

## 1. Ejecutar en local (Windows) — recomendado para uso diario

1. Descomprime el ZIP.
2. Haz doble clic en `run.bat`.
3. Se abre el navegador en <http://127.0.0.1:5000>.

`run.bat` crea el entorno virtual e instala las dependencias la primera vez.

Manual:

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

---

## 2. Subir el ZIP a una plataforma de entregas (Classroom, Moodle, etc.)

El ZIP ya contiene todo el proyecto listo (`app.py`, `scheduler/`, `static/`,
`tests/`, `README.md`, base de datos de ejemplo y esta guía). Puedes subirlo
tal cual, sin modificar nada.

---

## 3. Publicarlo en internet (hosting)

La aplicación es Flask + SQLite y ya incluye lo necesario para producción:

| Archivo | Para qué sirve |
|---|---|
| `wsgi.py` | Expone `application` para servidores WSGI |
| `Procfile` | Comando de arranque para Railway / Heroku |
| `render.yaml` | Configuración lista para Render |
| `requirements.txt` | Incluye Gunicorn en Linux |

### Render (recomendado, plan gratuito)

1. Sube el proyecto a un repositorio de GitHub.
2. En <https://render.com> → **New → Web Service** → conecta el repositorio.
3. Render detecta `render.yaml`; si no, usa:
   - **Build Command:** `pip install -r requirements.txt`
   - **Start Command:** `gunicorn --bind 0.0.0.0:$PORT wsgi:application --timeout 300`
4. Listo: Render asigna una URL pública HTTPS.

> El generador puede tardar hasta ~30 s en resolver el horario; por eso el
> timeout de Gunicorn está en 300 s.

### Railway / Heroku (con GitHub o CLI)

El `Procfile` se detecta automáticamente:

```
web: gunicorn --bind 0.0.0.0:$PORT wsgi:application --timeout 300
```

### Vercel (serverless)

El proyecto ya incluye `api/index.py` y `vercel.json`, así que se despliega
directo con la CLI:

```bash
npm i -g vercel        # o usa: npx vercel
vercel login
vercel --prod
```

La primera vez pide confirmar el nombre del proyecto y el equipo; acepta los
valores por defecto. Al terminar entrega una URL como
`https://generador-horarios-xxxx.vercel.app`.

> **Importante en Vercel:** el plan gratuito usa un sistema de archivos de solo
> lectura. La app copia automáticamente `horarios.db` a `/tmp` para funcionar,
> pero los cambios (horarios generados, ediciones) pueden perderse al
> reiniciarse la función o al hacer un nuevo despliegue. Para datos
> persistentes en producción usa una base externa (Turso, Neon, Postgres) o
> mantén la app en Render/Railway con disco persistente.

### PythonAnywhere (permite subir el ZIP directamente)

1. **Files → Upload a file** y sube el ZIP.
2. En una consola de Bash:
   ```bash
   unzip generador-horarios-plataforma.zip
   cd generador-horarios
   python3 -m venv .venv
   source .venv/bin/activate
   pip install -r requirements.txt
   ```
3. **Web → Add a new web app → Manual configuration → Python 3.10+**.
4. Edita el archivo WSGI y coloca:
   ```python
   import sys
   path = "/home/TU_USUARIO/generador-horarios"
   if path not in sys.path:
       sys.path.insert(0, path)
   from wsgi import application
   ```
5. Pulsa **Reload**.

---

## Nota sobre la base de datos

El ZIP incluye `horarios.db` con los datos de ejemplo y los horarios ya
generados. En local y en PythonAnywhere los cambios se conservan.

En plataformas con disco efímero (Render gratuito, Railway) los cambios se
pueden perder al redeploy o reiniciar. Para conservarlos:

- Añade un **disco persistente** y monta el proyecto ahí, o
- Define la variable de entorno `DB_PATH` con la ruta completa del archivo
  SQLite dentro del disco persistente (por ejemplo
  `/var/data/horarios.db`). La carpeta debe existir.
- Usa **Configuración → Exportar configuración** y vuelve a importarla.

---

## Variables de entorno

| Variable | Uso | Valor por defecto |
|---|---|---|
| `PORT` | Puerto HTTP que asigna la plataforma | `5000` |
| `HOST` | Interfaz de escucha al ejecutar `python app.py` | `127.0.0.1` (local) / `0.0.0.0` si hay `PORT` |
| `DB_PATH` | Ruta alternativa del archivo SQLite | `horarios.db` en la raíz del proyecto |

Los servidores WSGI (Gunicorn) no necesitan `python app.py`; usan `wsgi:application`.
