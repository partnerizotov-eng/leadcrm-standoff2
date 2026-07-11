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


@bp.route("/backups")
@admin_required
def backups_list():
    from .backup_scheduler import list_backups
    from flask import render_template
    return render_template("backups.html", backups=list_backups())


@bp.route("/backups/create", methods=["POST"])
@admin_required
def backups_create_now():
    from .backup_scheduler import create_backup
    from flask import flash, redirect, url_for
    filename = create_backup()
    flash(f"✅ Бэкап создан: {filename}", "success")
    return redirect(url_for("db_export.backups_list"))


@bp.route("/backups/<path:filename>/download")
@admin_required
def backups_download(filename):
    import os
    from flask import current_app, abort
    safe_name = os.path.basename(filename)
    if not (safe_name.startswith("backup_") and safe_name.endswith(".json")):
        abort(404)
    backups_dir = os.path.join(current_app.root_path, "..", "backups")
    full_path = os.path.join(backups_dir, safe_name)
    if not os.path.isfile(full_path):
        abort(404)
    return send_file(full_path, as_attachment=True, download_name=safe_name, mimetype="application/json")


@bp.route("/backups/restore", methods=["GET"])
@admin_required
def backups_restore_form():
    from flask import render_template
    return render_template("backup_restore.html")


@bp.route("/backups/restore", methods=["POST"])
@admin_required
def backups_restore_run():
    import json
    from flask import flash, redirect, render_template, request, url_for
    from .backup_restore import restore_backup, validate_backup_shape

    file = request.files.get("backup_file")
    confirmed = request.form.get("confirm") == "yes"

    if not file or not file.filename:
        flash("Файл не выбран.", "error")
        return redirect(url_for("db_export.backups_restore_form"))
    if not confirmed:
        flash("Нужно подтвердить восстановление — отметь чекбокс ниже формы.", "error")
        return redirect(url_for("db_export.backups_restore_form"))

    try:
        data = json.load(file.stream)
    except Exception:
        flash("Файл повреждён или это не JSON.", "error")
        return redirect(url_for("db_export.backups_restore_form"))

    err = validate_backup_shape(data)
    if err:
        flash(err, "error")
        return redirect(url_for("db_export.backups_restore_form"))

    report = restore_backup(data)
    return render_template("backup_restore_result.html", report=report, backup_created_at=data.get("created_at"))
