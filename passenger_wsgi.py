"""Phusion Passenger entry point (used by some shared hosts)."""
from app import app as application

app = application
