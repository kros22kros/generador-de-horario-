# Generador Automático de Horarios Académicos

Aplicación web (Flask + SQLite) que genera automáticamente el horario de un colegio
completo (**Primaria y Secundaria**) mediante un algoritmo **CSP con backtracking**
(MRV dinámico + forward checking). No usa asignación aleatoria: valida restricciones
**duras** y optimiza restricciones **blandas**, y cuando no existe solución lo explica.

## Características

- **Niveles, grados, cursos, profesores, asignaturas, aulas** y **asignaciones** editables.
- **Restricciones duras** siempre respetadas:
  - Un profesor no puede estar en dos cursos a la vez.
  - Un curso no puede tener dos asignaturas a la vez.
  - Un aula no puede alojar dos cursos a la vez.
  - Sala de Sistemas, Laboratorio, Cancha y Taller son exclusivos.
  - Se respeta la jornada (días, bloques y horas) de cada curso y la disponibilidad.
  - Bloques dobles consecutivos para Informática, Química y Física.
  - Intensidad horaria exacta por curso y asignatura.
- **Restricciones blandas** (puntuación optimizada): evitar huecos, distribuir carga,
  preferir bloques dobles ya definidos, respetar el tipo de aula sugerido.
- **Diagnóstico** detallado cuando no hay solución (profesores/asignaturas saturadas,
  aulas insuficientes, % de ocupación) con mensajes claros en español.
- **Validación independiente** del horario generado (13 comprobaciones).
- **Exportación** a **Excel (.xlsx)**, **CSV** y **PDF**.
- Datos de ejemplo de un colegio completo para probar de inmediato.

## Requisitos

- Python 3.10 o superior.
- Dependencias: `Flask`, `openpyxl`, `fpdf2` (ver `requirements.txt`).

## Instalación y uso

### Opción rápida (Windows)

```bat
run.bat
```

Crea el entorno virtual, instala dependencias y arranca el servidor.

### Manual

```bat
python -m venv .venv
.venv\Scripts\activate
pip install -r requirements.txt
python app.py
```

Abra **http://127.0.0.1:5000** en el navegador.

## Despliegue

- **Local (Windows):** doble clic en `run.bat`.
- **Solo ver los horarios (sin instalar nada):** abre
  `ABRIR_VISTA_PREVIA.html`; también incluye `VISTA_PREVIA.pdf` y
  `horario_ejemplo.xlsx`.
- **Hosting (Render / Railway / PythonAnywhere):** consulta
  [`DESPLIEGUE.md`](DESPLIEGUE.md). El proyecto ya incluye `wsgi.py`, `Procfile`,
  `render.yaml` y Gunicorn en Linux.
- **Entregas / aulas virtuales:** el ZIP del proyecto se puede subir tal cual.

## Flujo de trabajo

1. **Configuración → Datos de ejemplo** carga un colegio completo (o **Vaciar** para empezar de cero).
2. Revise/edite las secciones: Niveles, Grados, Cursos, Profesores, Asignaturas, Aulas y Asignaciones.
3. Vaya a **Generar horario** y pulse **GENERAR HORARIO**.
   - Éxito: `Horario generado correctamente`.
   - Fallo: `NO ES POSIBLE GENERAR UN HORARIO VÁLIDO` con la lista de conflictos.
4. Consulte **Ver horarios** (por curso, profesor, aula o vista general).
5. Exporte a Excel, CSV o PDF desde **Exportar**.

## Estructura

```
generador-horarios/
├─ app.py                  # servidor Flask + API REST
├─ wsgi.py                 # entrada WSGI para hosting (Gunicorn)
├─ api/index.py            # entrada serverless para Vercel
├─ vercel.json             # configuración de Vercel
├─ run.bat                 # arranque rápido en Windows
├─ LEEME_PRIMERO.txt       # instrucciones para el profesor
├─ ABRIR_VISTA_PREVIA.html # vista previa estática (sin instalar nada)
├─ VISTA_PREVIA.pdf        # horario de ejemplo en PDF
├─ horario_ejemplo.xlsx    # horario de ejemplo en Excel
├─ Procfile                # arranque en Railway / Heroku
├─ render.yaml             # configuración para Render
├─ requirements.txt
├─ DESPLIEGUE.md           # guía de publicación en internet
├─ scheduler/
│  ├─ db.py                # esquema SQLite y helpers
│  ├─ seed.py              # colegio de demostración
│  ├─ solver.py            # motor CSP (prevalidate, solve, diagnose, generate)
│  ├─ validator.py         # validación independiente (13 comprobaciones)
│  └─ exporter.py          # vistas y exportación XLSX/CSV/PDF
├─ static/
│  ├─ index.html
│  ├─ css/styles.css
│  └─ js/{api,ui,app}.js   # SPA (sin build step)
└─ tests/
   └─ test_horarios.py     # pruebas automáticas
```

## Pruebas

```bat
python -m unittest discover -s tests -v
```

Cubren: generación válida del colegio de ejemplo (con las 13 validaciones), los
principales **casos de conflicto** (profesor, laboratorio, Sala de Sistemas, horas
insuficientes, disponibilidad, solapamiento parcial detectado durante la búsqueda,
aula especial inexistente) y la **detección de horarios corruptos** por el validador.

## Cómo funciona el motor

1. **Pre-validación**: detecta imposibilidades evidentes (capacidad de profesores,
   aulas, jornada, disponibilidad) antes de buscar.
2. **Construcción de sesiones**: cada (profesor, asignatura, curso, longitud) es una
   variable; su dominio son los bloques `(día, índice)` válidos.
3. **Búsqueda**: backtracking con **MRV dinámico** (elige la sesión más restringida),
   **forward checking** (recomputa dominios de sesiones afectadas) y heurística de grados.
4. **Relajación**: si no hay solución con pares blandos, reintenta conservando solo
   los bloques dobles duros.
5. **Validación** y **guardado**; si falla, se guarda un diagnóstico de causas.
