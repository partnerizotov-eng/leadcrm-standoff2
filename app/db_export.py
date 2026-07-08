"""Временный экспорт базы данных для администратора. Использует встроенный
backup API sqlite3 — безопасно копирует файл даже при активной записи
в WAL-режиме, в отличие от прямого чтения файла с диска."""
import os
import sqlite3
import tempfile
from datetime import datetime

from flask import Blueprint, current_app, send_file
from .security import admin_required

bp = Blueprint("db_export", __name__, url_prefix="/admin")


@bp.route("/export-database")
@admin_required
def export_database():
    src_path = current_app.config["DATABASE_PATH"]

    fd, tmp_path = tempfile.mkstemp(suffix=".db")
    os.close(fd)

    src_conn = sqlite3.connect(src_path)
    dst_conn = sqlite3.connect(tmp_path)
    with dst_conn:
        src_conn.backup(dst_conn)
    src_conn.close()
    dst_conn.close()

    filename = f"leadcrm_backup_{datetime.now().strftime('%Y%m%d_%H%M%S')}.db"
    return send_file(tmp_path, as_attachment=True, download_name=filename, mimetype="application/octet-stream")
