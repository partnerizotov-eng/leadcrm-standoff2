"""Tests for manager admin features added on top of the base app:
edit, Excel import, TXT export, resubmission after rejection, journal.
"""
import io
import os
import secrets
import tempfile
import unittest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_LOGIN"] = "admin"
os.environ["ADMIN_PASSWORD"] = "adminpass123"

from app import create_app  # noqa: E402
from app.db import execute, query_one  # noqa: E402
from app.security import hash_password, reset_rate_limits  # noqa: E402
from app.leads import add_lead  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        reset_rate_limits()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def login_admin(self):
        return self.client.post("/login", data={"login": "admin", "password": "adminpass123"},
                                follow_redirects=True)

    def login_manager(self, login, password="mgrpass"):
        return self.client.post("/login", data={"login": login, "password": password}, follow_redirects=True)

    def make_manager(self, name="Manager", profile_completed=True, trainer_passed=True):
        # profile_completed=1 и trainer_passed=1 по умолчанию: иначе
        # force_profile_completion / trainer_required (before_request и
        # маршруты в leads.py) редиректят на анкету/тренажёр вместо
        # ожидаемой страницы. Тесты именно ЭТИХ гейтов создают менеджера
        # с явным trainer_passed=False/profile_completed=False.
        with self.app.app_context():
            login = f"mgr_{secrets.token_hex(4)}"
            mid = execute(
                "INSERT INTO managers (login, password_hash, name, role, profile_completed, trainer_passed) "
                "VALUES (?,?,?,'manager',?,?)",
                (login, hash_password("mgrpass"), name,
                 1 if profile_completed else 0, 1 if trainer_passed else 0))
        return mid, login


class TestManagerEdit(Base):
    def test_admin_can_change_login_and_password(self):
        mid, login = self.make_manager()
        self.login_admin()
        resp = self.client.post(f"/managers/{mid}/edit",
                                data={"name": "Renamed", "login": "newlogin", "password": "newpass123"},
                                follow_redirects=True)
        self.assertEqual(resp.status_code, 200)
        with self.app.app_context():
            row = query_one("SELECT name, login FROM managers WHERE id=?", (mid,))
        self.assertEqual(row["login"], "newlogin")
        self.assertEqual(row["name"], "Renamed")
        # New password works
        self.client.get("/logout")
        resp = self.login_manager("newlogin", "newpass123")
        self.assertIn(b"logout", resp.data.lower() + b"logout")  # smoke: no exception

    def test_manager_cannot_edit_managers(self):
        mid, login = self.make_manager()
        other_id, _ = self.make_manager("Other")
        self.login_manager(login)
        resp = self.client.post(f"/managers/{other_id}/edit",
                                data={"name": "Hacked", "login": "hacked"})
        self.assertEqual(resp.status_code, 403)

    def test_edit_rejects_duplicate_login(self):
        m1, login1 = self.make_manager("One")
        m2, login2 = self.make_manager("Two")
        self.login_admin()
        resp = self.client.post(f"/managers/{m2}/edit",
                                data={"name": "Two", "login": login1, "password": ""},
                                follow_redirects=True)
        self.assertIn("уже занят".encode(), resp.data)


class TestManagerExcelImport(Base):
    def test_import_creates_managers_and_returns_txt(self):
        from openpyxl import Workbook
        wb = Workbook()
        ws = wb.active
        ws.append(["Имя", "Логин", "Пароль"])
        ws.append(["Иван Иванов", "ivan.imp", "supersecret1"])
        ws.append(["Пётр Петров", "", ""])  # auto-generated login/password
        buf = io.BytesIO()
        wb.save(buf)
        buf.seek(0)

        self.login_admin()
        resp = self.client.post("/managers/import",
                                data={"file": (buf, "managers.xlsx")},
                                content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 200)
        self.assertIn(b"ivan.imp", resp.data)
        with self.app.app_context():
            self.assertIsNotNone(query_one("SELECT 1 FROM managers WHERE login='ivan.imp'"))
            self.assertIsNotNone(query_one("SELECT 1 FROM managers WHERE name='Пётр Петров'"))

    def test_manager_cannot_import(self):
        _, login = self.make_manager()
        self.login_manager(login)
        resp = self.client.post("/managers/import", data={}, content_type="multipart/form-data")
        self.assertEqual(resp.status_code, 403)


class TestManagerTxtExport(Base):
    def test_export_lists_logins(self):
        self.make_manager("Экспорт Тест")
        self.login_admin()
        resp = self.client.get("/managers/export")
        self.assertEqual(resp.status_code, 200)
        self.assertIn("Экспорт Тест".encode(), resp.data)
        self.assertIn(b"attachment", resp.headers.get("Content-Disposition", "").encode())


class TestSubmissionReopensAfterRejection(Base):
    def test_rejected_submission_can_be_resubmitted_same_round(self):
        mid, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("https://vk.com/reopen_test", "grp", mid)
        self.login_manager(login)
        img = (io.BytesIO(b"fakepngdata"), "shot1.png")
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "round_date": "2026-01-01", "screenshot": img},
                         content_type="multipart/form-data", follow_redirects=True)
        with self.app.app_context():
            sub = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))
        self.client.get("/logout")

        self.login_admin()
        self.client.post(f"/submissions/{sub['id']}/review",
                         data={"decision": "rejected", "comment": "плохой скриншот"},
                         follow_redirects=True)
        self.client.get("/logout")

        self.login_manager(login)
        img2 = (io.BytesIO(b"fakepngdata2"), "shot2.png")
        resp = self.client.post(f"/leads/{lead_id}/submit",
                                data={"round_slot": "12:00", "round_date": "2026-01-01", "screenshot": img2},
                                content_type="multipart/form-data", follow_redirects=True)
        self.assertNotIn("уже отправлена заявка".encode(), resp.data)
        with self.app.app_context():
            row = query_one("SELECT status FROM submissions WHERE lead_id=?", (lead_id,))
            count = query_one("SELECT COUNT(*) c FROM submissions WHERE lead_id=?", (lead_id,))["c"]
        self.assertEqual(row["status"], "pending")
        self.assertEqual(count, 1)  # reopened the same row, not a duplicate


class TestJournal(Base):
    def test_manager_creation_is_logged(self):
        self.login_admin()
        self.client.post("/managers/create",
                         data={"name": "Журнальный", "login": "jrn1", "password": "pass1234"},
                         follow_redirects=True)
        resp = self.client.get("/journal")
        self.assertIn("Журнальный".encode(), resp.data)

    def test_manager_cannot_view_journal(self):
        _, login = self.make_manager()
        self.login_manager(login)
        resp = self.client.get("/journal")
        self.assertEqual(resp.status_code, 403)


if __name__ == "__main__":
    unittest.main()
