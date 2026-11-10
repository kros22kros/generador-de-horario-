"""Punto de entrada WSGI para plataformas de despliegue.

Render / Railway / Heroku / PythonAnywhere pueden ejecutar la aplicación
apuntando a ``wsgi:application`` (o ``app:app``) con Gunicorn.
"""
from app import app

application = app

if __name__ == "__main__":
    app.run()
