"""Доказательства выплат и фото топа игроков"""
from .db import execute, query_one, query_all
import os
from werkzeug.utils import secure_filename
import datetime

ALLOWED_EXTENSIONS = {'png', 'jpg', 'jpeg', 'gif', 'webp'}
UPLOAD_FOLDER = 'static/uploads/payments'


def allowed_file(filename):
    return '.' in filename and filename.rsplit('.', 1)[1].lower() in ALLOWED_EXTENSIONS


def upload_payment_proof(file, withdrawal_id, description, admin_id):
    """Загрузить скриншот выплаты"""
    
    if not file or file.filename == '':
        return False, "❌ Файл не выбран"
    
    if not allowed_file(file.filename):
        return False, "❌ Неподдерживаемый формат файла"
    
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    filename = secure_filename(file.filename)
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S_')
    filename = timestamp + filename
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    proof_id = execute("""
        INSERT INTO payment_proofs (withdrawal_id, file_path, description, admin_id, created_at)
        VALUES (?, ?, ?, ?, datetime('now'))
    """, (withdrawal_id, filepath, description, admin_id))
    
    if withdrawal_id:
        withdrawal = query_one("SELECT * FROM withdrawals WHERE id = ?", (withdrawal_id,))
        if withdrawal:
            msg = f"✅ Ваш вывод на сумму {withdrawal['requested_amount']}G был выплачен! Скриншот приложен."
            execute("INSERT INTO notifications (manager_id, message, created_at) VALUES (?, ?, datetime('now'))",
                    (withdrawal['manager_id'], msg))
    
    return True, "✅ Скриншот выплаты загружен"


def upload_top_player_photo(file, description, admin_id):
    """Загрузить фото топа игроков"""
    
    if not file or file.filename == '':
        return False, "❌ Файл не выбран"
    
    if not allowed_file(file.filename):
        return False, "❌ Неподдерживаемый формат файла"
    
    os.makedirs(UPLOAD_FOLDER, exist_ok=True)
    
    filename = secure_filename(file.filename)
    timestamp = datetime.datetime.utcnow().strftime('%Y%m%d_%H%M%S_')
    filename = timestamp + filename
    filepath = os.path.join(UPLOAD_FOLDER, filename)
    file.save(filepath)
    
    execute("""
        INSERT INTO top_player_photos (file_path, description, admin_id, created_at)
        VALUES (?, ?, ?, datetime('now'))
    """, (filepath, description, admin_id))
    
    return True, "✅ Фото топа игроков загружено"


def get_payment_proofs(limit=50):
    """Получить историю доказательств выплат"""
    sql = """
        SELECT pp.*, w.requested_amount, w.manager_id, m.name as manager_name
        FROM payment_proofs pp
        LEFT JOIN withdrawals w ON pp.withdrawal_id = w.id
        LEFT JOIN managers m ON w.manager_id = m.id
        ORDER BY pp.created_at DESC
        LIMIT ?
    """
    return query_all(sql, (limit,))


def get_top_player_photos():
    """Получить все фото топа игроков"""
    return query_all("SELECT * FROM top_player_photos ORDER BY created_at DESC")


def delete_payment_proof(proof_id):
    """Удалить скриншот выплаты"""
    proof = query_one("SELECT * FROM payment_proofs WHERE id = ?", (proof_id,))
    
    if not proof:
        return False, "❌ Скриншот не найден"
    
    try:
        if os.path.exists(proof['file_path']):
            os.remove(proof['file_path'])
    except:
        pass
    
    execute("DELETE FROM payment_proofs WHERE id = ?", (proof_id,))
    
    return True, "✅ Скриншот удалён"


def delete_top_photo(photo_id):
    """Удалить фото топа"""
    photo = query_one("SELECT * FROM top_player_photos WHERE id = ?", (photo_id,))
    
    if not photo:
        return False, "❌ Фото не найдено"
    
    try:
        if os.path.exists(photo['file_path']):
            os.remove(photo['file_path'])
    except:
        pass
    
    execute("DELETE FROM top_player_photos WHERE id = ?", (photo_id,))
    
    return True, "✅ Фото удалено"
