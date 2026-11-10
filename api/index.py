"""Punto de entrada serverless para Vercel.

Vercel detecta la variable ``app`` y expone toda la aplicación Flask.
Las peticiones se enrutan aquí desde ``vercel.json``.
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app import app  # noqa: E402,F401
