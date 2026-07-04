"""Canonical WSGI module. `application` is the name most hosts look for."""
from app import app as application

app = application
