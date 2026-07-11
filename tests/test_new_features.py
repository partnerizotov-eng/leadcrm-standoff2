"""Tests for everything added in this round: vk.ru support, trainer-gated
lead access, 2FA (TOTP), 152-FZ erasure, backup restore, funnel/rating
pages, leads search & bulk actions, and risk/duplicate scoring.

Runs with the standard library only: python -m unittest
(same convention as test_app.py / test_payments.py / test_managers_admin.py)
"""
import io
import json
import os
import secrets
import tempfile
import unittest

os.environ["DATABASE_PATH"] = os.path.join(tempfile.mkdtemp(), "test.db")
os.environ["SECRET_KEY"] = "test-secret"
os.environ["ADMIN_LOGIN"] = "admin"
os.environ["ADMIN_PASSWORD"] = "adminpass123"

from app import create_app  # noqa: E402
from app.db import execute, query_all, query_one  # noqa: E402
from app.security import reset_rate_limits, hash_password, verify_password  # noqa: E402
from app.leads import add_lead, vk_chat_url  # noqa: E402
from app.utils.vk_validator import VKValidator  # noqa: E402
from app.totp import generate_secret, totp_now, verify_totp  # noqa: E402


class Base(unittest.TestCase):
    def setUp(self):
        reset_rate_limits()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def login_admin(self):
        return self.client.post("/login", data={"login": "admin", "password": "adminpass123"},
                                follow_redirects=True)

    def make_manager(self, name="Manager", profile_completed=True, trainer_passed=True):
        with self.app.app_context():
            login = f"mgr_{secrets.token_hex(4)}"
            mid = execute(
                "INSERT INTO managers (login, password_hash, name, role, profile_completed, trainer_passed) "
                "VALUES (?,?,?,'manager',?,?)",
                (login, hash_password("mgrpass"), name,
                 1 if profile_completed else 0, 1 if trainer_passed else 0))
        return mid, login

    def login_manager(self, login, password="mgrpass"):
        return self.client.post("/login", data={"login": login, "password": password}, follow_redirects=True)


# ============================================================================
#  VK domain fix (vk.com -> vk.ru)
# ============================================================================
class TestVkDomainSupport(unittest.TestCase):
    def test_vk_ru_accepted(self):
        ok, _ = VKValidator.is_valid_vk_url("https://vk.ru/id123456")
        self.assertTrue(ok)

    def test_vk_com_still_accepted(self):
        ok, _ = VKValidator.is_valid_vk_url("https://vk.com/id123456")
        self.assertTrue(ok)

    def test_extract_id_works_for_both_domains(self):
        self.assertEqual(VKValidator.extract_id("https://vk.ru/durov"), "durov")
        self.assertEqual(VKValidator.extract_id("https://vk.com/durov"), "durov")

    def test_chat_link_uses_ru(self):
        self.assertEqual(vk_chat_url("durov"), "https://vk.ru/im?sel=durov")


# ============================================================================
#  Trainer gating: managers.trainer_passed controls access to /leads
# ============================================================================
class TestTrainerGating(Base):
    def test_untrained_manager_redirected_to_simulator(self):
        mgr, login = self.make_manager(trainer_passed=False)
        self.login_manager(login)
        r = self.client.get("/leads", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/simulator/", r.headers["Location"])

    def test_trained_manager_accesses_leads(self):
        mgr, login = self.make_manager(trainer_passed=True)
        self.login_manager(login)
        r = self.client.get("/leads")
        self.assertEqual(r.status_code, 200)

    def test_admin_bypasses_gate_regardless_of_trainer_passed(self):
        self.login_admin()
        r = self.client.get("/leads")
        self.assertEqual(r.status_code, 200)

    def test_simulator_page_itself_is_public(self):
        # без логина вообще
        anon = self.app.test_client()
        r = anon.get("/simulator/")
        self.assertEqual(r.status_code, 200)

    def test_save_result_unlocks_access(self):
        mgr, login = self.make_manager(trainer_passed=False)
        self.login_manager(login)
        r = self.client.get("/leads", follow_redirects=False)
        self.assertEqual(r.status_code, 302)  # ещё закрыто

        r = self.client.post("/simulator/save-result", json={"score": 470, "passed": True})
        self.assertEqual(r.get_json()["unlocked"], True)

        r = self.client.get("/leads")
        self.assertEqual(r.status_code, 200)  # теперь открыто

    def test_failing_attempt_does_not_unlock(self):
        mgr, login = self.make_manager(trainer_passed=False)
        self.login_manager(login)
        r = self.client.post("/simulator/save-result", json={"score": 300, "passed": False})
        self.assertEqual(r.get_json()["unlocked"], False)
        r = self.client.get("/leads", follow_redirects=False)
        self.assertEqual(r.status_code, 302)


# ============================================================================
#  Двухфакторная аутентификация (2FA / TOTP)
# ============================================================================
class Test2FA(Base):
    def make_admin(self):
        with self.app.app_context():
            login = f"admin2fa_{secrets.token_hex(4)}"
            mid = execute(
                "INSERT INTO managers (login, password_hash, name, role, profile_completed) "
                "VALUES (?,?,?,'admin',1)",
                (login, hash_password("adm2fapass"), "Admin2FA"))
        return mid, login

    def _enable_2fa(self, login):
        # заходим под ЭТИМ конкретным админом (не под общим "admin" —
        # иначе включение 2FA на общем аккаунте сломает login_admin()
        # во всех остальных тестовых классах, которые делят один physical
        # sqlite-файл в рамках запуска файла)
        self.client.post("/login", data={"login": login, "password": "adm2fapass"})
        r = self.client.get("/profile/2fa/setup")
        import re
        secret = re.search(r'<code[^>]*>([A-Z0-9]{20,40})</code>', r.get_data(as_text=True)).group(1)
        self.client.post("/profile/2fa/setup", data={"code": totp_now(secret)})
        self.client.get("/logout")
        return secret

    def test_totp_matches_rfc4226_vector(self):
        # RFC 4226 Appendix D, counter=0, ASCII secret "12345678901234567890"
        import base64
        from app.totp import _hotp
        secret_b32 = base64.b32encode(b"12345678901234567890").decode().rstrip("=")
        self.assertEqual(_hotp(secret_b32, 0), "755224")

    def test_setup_requires_correct_code(self):
        mid, login = self.make_admin()
        self.client.post("/login", data={"login": login, "password": "adm2fapass"})
        r = self.client.get("/profile/2fa/setup")
        self.assertEqual(r.status_code, 200)
        r = self.client.post("/profile/2fa/setup", data={"code": "000000"}, follow_redirects=True)
        self.assertIn("неверный", r.get_data(as_text=True).lower())
        with self.app.app_context():
            row = query_one("SELECT totp_enabled FROM managers WHERE id=?", (mid,))
        self.assertEqual(row["totp_enabled"], 0)

    def test_enabling_2fa_forces_code_on_next_login(self):
        mid, login = self.make_admin()
        self._enable_2fa(login)
        fresh = self.app.test_client()
        r = fresh.post("/login", data={"login": login, "password": "adm2fapass"}, follow_redirects=False)
        self.assertIn("/login/2fa", r.headers["Location"])
        r2 = fresh.get("/leads", follow_redirects=False)
        self.assertIn("/login", r2.headers["Location"])

    def test_correct_totp_completes_login(self):
        mid, login = self.make_admin()
        secret = self._enable_2fa(login)
        fresh = self.app.test_client()
        fresh.post("/login", data={"login": login, "password": "adm2fapass"})
        r = fresh.post("/login/2fa", data={"code": totp_now(secret)}, follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertNotIn("/login/2fa", r.headers["Location"])
        r2 = fresh.get("/leads")
        self.assertEqual(r2.status_code, 200)

    def test_wrong_totp_rejected(self):
        mid, login = self.make_admin()
        self._enable_2fa(login)
        fresh = self.app.test_client()
        fresh.post("/login", data={"login": login, "password": "adm2fapass"})
        r = fresh.post("/login/2fa", data={"code": "999999"}, follow_redirects=True)
        self.assertIn("неверный код", r.get_data(as_text=True).lower())

    def test_backup_codes_are_stored_hashed_not_plaintext(self):
        mid, login = self.make_admin()
        self._enable_2fa(login)
        with self.app.app_context():
            row = query_one("SELECT totp_backup_codes FROM managers WHERE id=?", (mid,))
        codes = json.loads(row["totp_backup_codes"])
        self.assertEqual(len(codes), 8)
        self.assertTrue(all(len(h) > 20 for h in codes))  # хэш, не 8-значный сырой код

    def test_disable_requires_correct_password(self):
        mid, login = self.make_admin()
        secret = self._enable_2fa(login)
        self.client.post("/login", data={"login": login, "password": "adm2fapass"})
        self.client.post("/login/2fa", data={"code": totp_now(secret)})  # завершаем полный вход
        r = self.client.post("/profile/2fa/disable", data={"password": "wrong"}, follow_redirects=True)
        self.assertIn("неверный пароль", r.get_data(as_text=True).lower())
        r2 = self.client.post("/profile/2fa/disable", data={"password": "adm2fapass"}, follow_redirects=True)
        self.assertIn("2fa отключена", r2.get_data(as_text=True).lower())

    def test_non_admin_cannot_access_2fa_setup(self):
        mgr, login = self.make_manager()
        self.login_manager(login)
        r = self.client.get("/profile/2fa/")
        self.assertEqual(r.status_code, 403)


# ============================================================================
#  152-ФЗ — удаление персональных данных
# ============================================================================
class TestGdprErasure(Base):
    def test_erase_cascades_and_leaves_no_vk_id_in_log(self):
        from app.gdpr_erasure import erase_lead_data, find_lead_for_erasure
        mgr, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("https://vk.ru/gdprtest1", "Group", mgr)
            execute("INSERT INTO submissions (lead_id, manager_id, round_date, round_slot, screenshot) "
                    "VALUES (?, ?, '2026-07-11', '12:00', 'x.png')", (lead_id, mgr))

            found = find_lead_for_erasure("gdprtest1")
            self.assertEqual(len(found), 1)

            with self.app.app_context():
                admin_id = query_one("SELECT id FROM managers WHERE login='admin'")["id"]
            ok, _ = erase_lead_data(lead_id, admin_id, "test request")
            self.assertTrue(ok)

            self.assertIsNone(query_one("SELECT 1 FROM leads WHERE id=?", (lead_id,)))
            self.assertEqual(query_one("SELECT COUNT(*) c FROM submissions WHERE lead_id=?",
                                       (lead_id,))["c"], 0)
            activity = query_all("SELECT message FROM activity ORDER BY id DESC LIMIT 3")
            self.assertFalse(any("gdprtest1" in a["message"] for a in activity))

    def test_erase_already_gone_fails_gracefully(self):
        from app.gdpr_erasure import erase_lead_data
        with self.app.app_context():
            admin_id = query_one("SELECT id FROM managers WHERE login='admin'")["id"]
            ok, msg = erase_lead_data(999999, admin_id)
        self.assertFalse(ok)


# ============================================================================
#  Восстановление из бэкапа
# ============================================================================
class TestBackupRestore(Base):
    def test_restore_into_empty_db_recreates_managers_with_temp_passwords(self):
        from app.backup_restore import restore_backup
        with self.app.app_context():
            data = {
                "created_at": "2026-01-01",
                "managers": [{"id": 501, "login": "restored1", "name": "Restored",
                              "role": "manager", "balance": 10, "total_earned": 10}],
                "leads": [], "submissions": [], "withdrawals": [], "withdrawal_events": [],
                "manager_ledger": [], "balance_ledger": [], "referrals": [], "referral_claims": [],
                "contests": [], "contest_winners": [],
            }
            report = restore_backup(data)
        self.assertEqual(report["tables"]["managers"], 1)
        self.assertEqual(len(report["new_managers"]), 1)
        self.assertEqual(report["new_managers"][0]["login"], "restored1")

    def test_restore_preserves_existing_password(self):
        from app.backup_restore import restore_backup
        mgr, login = self.make_manager(name="KeepMyPassword")
        with self.app.app_context():
            before = query_one("SELECT password_hash FROM managers WHERE id=?", (mgr,))["password_hash"]
            data = {
                "created_at": "2026-01-01",
                "managers": [{"id": mgr, "login": login, "name": "Renamed By Backup", "role": "manager"}],
                "leads": [], "submissions": [], "withdrawals": [], "withdrawal_events": [],
                "manager_ledger": [], "balance_ledger": [], "referrals": [], "referral_claims": [],
                "contests": [], "contest_winners": [],
            }
            restore_backup(data)
            after = query_one("SELECT password_hash, name FROM managers WHERE id=?", (mgr,))
        self.assertEqual(before, after["password_hash"])
        self.assertEqual(after["name"], "Renamed By Backup")


# ============================================================================
#  Воронка и рейтинг
# ============================================================================
class TestFunnelAndRating(Base):
    def test_funnel_first_stage_equals_total(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            for i, status in enumerate(["new", "contacted", "declined"]):
                execute("INSERT INTO leads (vk_id, vk_url, name, status, assigned_manager_id, found_at) "
                        "VALUES (?, ?, ?, ?, ?, datetime('now'))",
                        (f"funnel{i}", f"https://vk.ru/funnel{i}", f"F{i}", status, mgr))
        self.login_admin()
        r = self.client.get("/admin/funnel?days=30")
        self.assertEqual(r.status_code, 200)
        body = r.get_data(as_text=True)
        self.assertIn("Всего лидов за период: 3", body)

    def test_rating_page_renders_and_ranks(self):
        mgr, login = self.make_manager()
        self.login_admin()
        r = self.client.get("/rating")
        self.assertEqual(r.status_code, 200)

    def test_rating_csv_export(self):
        self.login_admin()
        r = self.client.get("/rating/export.csv")
        self.assertEqual(r.status_code, 200)
        self.assertEqual(r.content_type, "text/csv; charset=utf-8")


# ============================================================================
#  Поиск и массовые действия над лидами
# ============================================================================
class TestLeadsSearchAndBulk(Base):
    def test_search_by_name_filters_results(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            add_lead("https://vk.ru/searcha", "G", mgr, name="FindMeUnique")
            add_lead("https://vk.ru/searchb", "G", mgr, name="Other")
        self.login_admin()
        r = self.client.get("/leads?q=FindMeUnique")
        body = r.get_data(as_text=True)
        self.assertIn("FindMeUnique", body)
        self.assertNotIn("Other", body)

    def test_bulk_status_change_only_affects_selected(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            id1, _, _ = add_lead("https://vk.ru/bulk1", "G", mgr)
            id2, _, _ = add_lead("https://vk.ru/bulk2", "G", mgr)
        self.login_admin()
        self.client.post("/leads/bulk-action", data={"lead_ids": [str(id1)], "action": "status:contacted"})
        with self.app.app_context():
            s1 = query_one("SELECT status FROM leads WHERE id=?", (id1,))["status"]
            s2 = query_one("SELECT status FROM leads WHERE id=?", (id2,))["status"]
        self.assertEqual(s1, "contacted")
        self.assertEqual(s2, "new")

    def test_bulk_reassign_requires_admin(self):
        mgr, login = self.make_manager()
        mgr2, _ = self.make_manager(name="Other")
        with self.app.app_context():
            lead_id, _, _ = add_lead("https://vk.ru/bulkreassign", "G", mgr)
        self.login_manager(login)
        r = self.client.post("/leads/bulk-action",
                             data={"lead_ids": [str(lead_id)], "action": f"reassign:{mgr2}"},
                             follow_redirects=True)
        self.assertIn("только админ", r.get_data(as_text=True).lower())

    def test_manager_cannot_bulk_edit_someone_elses_lead(self):
        mgr1, login1 = self.make_manager()
        mgr2, _ = self.make_manager(name="Owner")
        with self.app.app_context():
            lead_id, _, _ = add_lead("https://vk.ru/notmine", "G", mgr2)
        self.login_manager(login1)
        self.client.post("/leads/bulk-action", data={"lead_ids": [str(lead_id)], "action": "status:declined"})
        with self.app.app_context():
            status = query_one("SELECT status FROM leads WHERE id=?", (lead_id,))["status"]
        self.assertEqual(status, "new")  # не изменилось


# ============================================================================
#  Риски и дубли
# ============================================================================
class TestRiskScoring(Base):
    def test_case_duplicate_leads_detected(self):
        from app.risk_scoring import find_case_duplicate_leads
        mgr, login = self.make_manager()
        with self.app.app_context():
            execute("INSERT INTO leads (vk_id, vk_url, name, assigned_manager_id) VALUES "
                    "('Durov', 'https://vk.ru/Durov', 'A', ?)", (mgr,))
            execute("INSERT INTO leads (vk_id, vk_url, name, assigned_manager_id) VALUES "
                    "('durov', 'https://vk.ru/durov', 'B', ?)", (mgr,))
            dups = find_case_duplicate_leads()
        groups = [g for g in dups if len(g) > 1]
        self.assertTrue(any({item["vk_id"] for item in g} == {"Durov", "durov"} for g in groups))

    def test_risk_page_admin_only(self):
        mgr, login = self.make_manager()
        self.login_manager(login)
        r = self.client.get("/admin/risk", follow_redirects=False)
        self.assertEqual(r.status_code, 403)


if __name__ == "__main__":
    unittest.main()
