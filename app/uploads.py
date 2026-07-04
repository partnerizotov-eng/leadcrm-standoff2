"""Screenshot uploads — proof for submissions (game ID in comments) and
withdrawals (skin sold). Stored on disk under DATA_DIR/uploads with a random
filename (never trust the original name), served back only to logged-in
managers.
"""
import secrets
from pathlib import Path

from flask import Blueprint, abort, current_app, send_from_directory
from werkzeug.utils import secure_filename

from .security import login_required

bp = Blueprint("uploads", __name__)

ALLOWED_EXTENSIONS = {"png", "jpg", "jpeg", "webp", "gif"}
MAX_BYTES = 8 * 1024 * 1024  # 8 MB — a phone screenshot, not a video


def _upload_dir():
    from config import DATA_DIR
    d = DATA_DIR / "uploads"
    d.mkdir(parents=True, exist_ok=True)
    return d


def save_screenshot(file_storage, prefix):
    """Validates and saves an uploaded image. Returns the stored filename,
    or None (with no side effect) if the file is missing/invalid — callers
    treat None as 'no valid screenshot was provided'."""
    if not file_storage or not file_storage.filename:
        return None

    original = secure_filename(file_storage.filename)
    ext = original.rsplit(".", 1)[-1].lower() if "." in original else ""
    if ext not in ALLOWED_EXTENSIONS:
        return None

    file_storage.seek(0, 2)  # seek to end to measure size
    size = file_storage.tell()
    file_storage.seek(0)
    if size == 0 or size > MAX_BYTES:
        return None

    filename = f"{prefix}_{secrets.token_hex(12)}.{ext}"
    file_storage.save(_upload_dir() / filename)
    return filename


@bp.route("/media/<filename>")
@login_required
def serve(filename):
    # secure_filename-style check: reject anything with path separators —
    # our own filenames never contain them, so this only blocks tampering.
    if "/" in filename or "\\" in filename:
        abort(400)
    path = _upload_dir() / filename
    if not path.is_file():
        abort(404)
    return send_from_directory(_upload_dir(), filename)
