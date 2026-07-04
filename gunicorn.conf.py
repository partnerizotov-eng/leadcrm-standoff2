"""Gunicorn configuration.

Reads the port from the ``PORT`` environment variable (Timeweb / Heroku-style)
and falls back to 8000 for local runs, so the Procfile never breaks when the
platform does not export ``$PORT``.
"""
import multiprocessing
import os

bind = "0.0.0.0:" + os.getenv("PORT", "8000")
workers = int(os.getenv("WEB_CONCURRENCY", str(min(multiprocessing.cpu_count() * 2 + 1, 4))))
threads = int(os.getenv("GUNICORN_THREADS", "2"))
timeout = int(os.getenv("GUNICORN_TIMEOUT", "120"))
graceful_timeout = 30
accesslog = "-"
errorlog = "-"
loglevel = os.getenv("GUNICORN_LOGLEVEL", "info")
