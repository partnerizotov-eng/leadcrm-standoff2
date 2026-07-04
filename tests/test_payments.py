"""Tests for the payment system: submissions with screenshot proof, admin
approval crediting balance, withdrawals with race-safe deduction and
commission-based list price, rejection refunds, admin balance overrides,
notifications, and the VK chat link helper.

Runs with the standard library only: python -m unittest
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
from app.db import execute, query_all, query_one  # noqa: E402
from app.security import reset_rate_limits, hash_password  # noqa: E402
from app.leads import add_lead, vk_chat_url  # noqa: E402
from app.withdrawals import compute_list_price, MIN_WITHDRAWAL  # noqa: E402


def fake_image(name="proof.png"):
    return (io.BytesIO(b"\x89PNG\r\n\x1a\n" + b"0" * 100), name)


class Base(unittest.TestCase):
    def setUp(self):
        reset_rate_limits()
        self.app = create_app()
        self.app.config["TESTING"] = True
        self.client = self.app.test_client()

    def login_admin(self):
        return self.client.post("/login", data={"login": "admin", "password": "adminpass123"},
                                follow_redirects=True)

    def make_manager(self, name="Manager"):
        with self.app.app_context():
            login = f"mgr_{secrets.token_hex(4)}"
            mid = execute("INSERT INTO managers (login, password_hash, name, role) VALUES (?,?,?,'manager')",
                         (login, hash_password("mgrpass"), name))
        return mid, login

    def login_manager(self, login, password="mgrpass"):
        return self.client.post("/login", data={"login": login, "password": password}, follow_redirects=True)

    def make_lead(self, manager_id, vk=None):
        vk = vk or f"vk.com/testlead_{secrets.token_hex(6)}"
        with self.app.app_context():
            lead_id, _, _ = add_lead(vk, "Group", manager_id)
        return lead_id


class TestVkChatLink(unittest.TestCase):
    def test_builds_direct_message_url(self):
        self.assertEqual(vk_chat_url("durov"), "https://vk.com/im?sel=durov")


class TestSubmissionFlow(Base):
    def test_manager_submits_and_admin_approves_credits_balance(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)

        r = self.client.post(f"/leads/{lead_id}/submit",
                             data={"round_slot": "12:00", "screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("отправлена на проверку", r.get_data(as_text=True))

        self.client.get("/logout")
        self.login_admin()
        with self.app.app_context():
            sub_id = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))["id"]
        r = self.client.post(f"/submissions/{sub_id}/review",
                             data={"decision": "approved", "comment": "Отлично, видно ID"},
                             follow_redirects=True)
        self.assertEqual(r.status_code, 200)

        with self.app.app_context():
            lead = query_one("SELECT balance, status, participation_count FROM leads WHERE id=?", (lead_id,))
            ledger = query_one("SELECT amount, reason FROM balance_ledger WHERE lead_id=?", (lead_id,))
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
            mgr_ledger = query_one("SELECT amount, reason FROM manager_ledger WHERE manager_id=?", (mgr,))
        self.assertEqual(lead["balance"], 10)
        self.assertEqual(lead["status"], "participated")
        self.assertEqual(lead["participation_count"], 1)
        self.assertEqual(ledger["amount"], 10)
        self.assertEqual(ledger["reason"], "submission_approved")
        self.assertEqual(manager["balance"], 10)
        self.assertEqual(mgr_ledger["amount"], 10)
        self.assertEqual(mgr_ledger["reason"], "submission_approved")

    def test_second_approval_sets_returning(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        for slot in ("12:00", "18:00"):
            self.client.post(f"/leads/{lead_id}/submit",
                             data={"round_slot": slot, "screenshot": fake_image()},
                             content_type="multipart/form-data")
        self.client.get("/logout")
        self.login_admin()
        with self.app.app_context():
            sub_ids = [r["id"] for r in query_all("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))]
        for sid in sub_ids:
            self.client.post(f"/submissions/{sid}/review", data={"decision": "approved"})
        with self.app.app_context():
            lead = query_one("SELECT balance, status FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 20)
        self.assertEqual(lead["status"], "returning")

    def test_rejection_does_not_credit_balance(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        self.client.get("/logout")
        self.login_admin()
        with self.app.app_context():
            sub_id = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))["id"]
        self.client.post(f"/submissions/{sub_id}/review",
                         data={"decision": "rejected", "comment": "ID не виден"})
        with self.app.app_context():
            lead = query_one("SELECT balance FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 0)

    def test_duplicate_submission_same_round_rejected(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "round_date": "2026-01-01", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        r = self.client.post(f"/leads/{lead_id}/submit",
                             data={"round_slot": "12:00", "round_date": "2026-01-01", "screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("уже отправлена", r.get_data(as_text=True))

    def test_manager_cannot_submit_for_someone_elses_lead(self):
        mgr1, _ = self.make_manager()
        _, login2 = self.make_manager()
        lead_id = self.make_lead(mgr1)
        self.login_manager(login2)
        r = self.client.post(f"/leads/{lead_id}/submit",
                             data={"round_slot": "12:00", "screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("не найден или не ваш", r.get_data(as_text=True))

    def test_manager_cannot_review_submissions(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        with self.app.app_context():
            sub_id = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))["id"]
        r = self.client.post(f"/submissions/{sub_id}/review", data={"decision": "approved"})
        self.assertEqual(r.status_code, 403)

    def test_reviewing_twice_is_rejected(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        self.client.get("/logout")
        self.login_admin()
        with self.app.app_context():
            sub_id = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))["id"]
        self.client.post(f"/submissions/{sub_id}/review", data={"decision": "approved"})
        r = self.client.post(f"/submissions/{sub_id}/review", data={"decision": "rejected"}, follow_redirects=True)
        self.assertIn("уже рассмотрена", r.get_data(as_text=True))
        with self.app.app_context():
            lead = query_one("SELECT balance FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 10)


class TestListPriceMath(unittest.TestCase):
    def test_matches_operators_worked_example(self):
        price = compute_list_price(100, 20)
        self.assertGreaterEqual(price, 120)
        self.assertLess(price, 121)

    def test_random_cents_present(self):
        prices = {compute_list_price(50, 20) for _ in range(20)}
        self.assertGreater(len(prices), 1)


class TestWithdrawalFlow(Base):
    def _fund(self, manager_id, amount):
        with self.app.app_context():
            execute("UPDATE managers SET balance=? WHERE id=?", (amount, manager_id))

    def test_below_minimum_rejected(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        r = self.client.post("/withdrawals/request", data={"amount": "10"}, follow_redirects=True)
        self.assertIn(f"{MIN_WITHDRAWAL}G", r.get_data(as_text=True))
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
        self.assertEqual(manager["balance"], 100)

    def test_more_than_balance_rejected(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 40)
        self.login_manager(login)
        r = self.client.post("/withdrawals/request", data={"amount": "50"}, follow_redirects=True)
        self.assertIn("недостаточно", r.get_data(as_text=True))

    def test_request_deducts_balance_immediately_and_creates_instruction(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
            w = query_one("SELECT * FROM withdrawals WHERE manager_id=?", (mgr,))
            event = query_one("SELECT actor, message FROM withdrawal_events WHERE withdrawal_id=?", (w["id"],))
        self.assertEqual(manager["balance"], 50)
        self.assertEqual(w["status"], "awaiting_listing")
        self.assertEqual(w["requested_amount"], 50)
        self.assertEqual(event["actor"], "system")
        self.assertIn(f"{w['list_price']:.2f}", event["message"])

    def test_full_flow_to_completion(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            wid = query_one("SELECT id FROM withdrawals WHERE manager_id=?", (mgr,))["id"]

        r = self.client.post(f"/withdrawals/{wid}/proof", data={"screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            status = query_one("SELECT status FROM withdrawals WHERE id=?", (wid,))["status"]
        self.assertEqual(status, "proof_submitted")

        self.client.get("/logout")
        self.login_admin()
        r = self.client.post(f"/withdrawals/{wid}/complete",
                             data={"comment": "Куплено, всё чисто", "screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            status = query_one("SELECT status FROM withdrawals WHERE id=?", (wid,))["status"]
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
        self.assertEqual(status, "completed")
        self.assertEqual(manager["balance"], 50)

    def test_rejection_refunds_balance(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            wid = query_one("SELECT id FROM withdrawals WHERE manager_id=?", (mgr,))["id"]

        self.client.get("/logout")
        self.login_admin()
        self.client.post(f"/withdrawals/{wid}/reject", data={"comment": "Скин не продан"})
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
            status = query_one("SELECT status FROM withdrawals WHERE id=?", (wid,))["status"]
            refund = query_one(
                "SELECT amount, reason FROM manager_ledger WHERE manager_id=? AND reason='withdrawal_refund'",
                (mgr,))
        self.assertEqual(manager["balance"], 100)
        self.assertEqual(status, "rejected")
        self.assertEqual(refund["amount"], 50)

    def test_completed_withdrawal_cannot_be_rejected(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            wid = query_one("SELECT id FROM withdrawals WHERE manager_id=?", (mgr,))["id"]
        self.client.post(f"/withdrawals/{wid}/proof", data={"screenshot": fake_image()},
                         content_type="multipart/form-data")
        self.client.get("/logout")
        self.login_admin()
        self.client.post(f"/withdrawals/{wid}/complete", data={})
        r = self.client.post(f"/withdrawals/{wid}/reject", data={"comment": "too late"}, follow_redirects=True)
        self.assertIn("нельзя отклонить", r.get_data(as_text=True))

    def test_manager_cannot_complete_or_reject(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 100)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            wid = query_one("SELECT id FROM withdrawals WHERE manager_id=?", (mgr,))["id"]
        r1 = self.client.post(f"/withdrawals/{wid}/complete", data={})
        r2 = self.client.post(f"/withdrawals/{wid}/reject", data={})
        self.assertEqual(r1.status_code, 403)
        self.assertEqual(r2.status_code, 403)

    def test_manager_cannot_submit_proof_for_someone_elses_withdrawal(self):
        mgr1, login1 = self.make_manager()
        _, login2 = self.make_manager()
        self._fund(mgr1, 100)
        self.login_manager(login1)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            wid = query_one("SELECT id FROM withdrawals WHERE manager_id=?", (mgr1,))["id"]
        self.client.get("/logout")
        self.login_manager(login2)
        r = self.client.post(f"/withdrawals/{wid}/proof", data={"screenshot": fake_image()},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("не найдена или не ваша", r.get_data(as_text=True))

    def test_race_safe_double_withdrawal_does_not_overdraw(self):
        mgr, login = self.make_manager()
        self._fund(mgr, 60)
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        r2 = self.client.post("/withdrawals/request", data={"amount": "50"}, follow_redirects=True)
        self.assertIn("недостаточно", r2.get_data(as_text=True))
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
            count = query_one("SELECT COUNT(*) c FROM withdrawals WHERE manager_id=?", (mgr,))["c"]
        self.assertEqual(manager["balance"], 10)
        self.assertEqual(count, 1)
        self.assertGreaterEqual(manager["balance"], 0)


class TestCommissionSetting(Base):
    def test_admin_can_change_commission(self):
        self.login_admin()
        self.client.post("/settings/commission", data={"commission_pct": "30"})
        mgr, login = self.make_manager()
        with self.app.app_context():
            execute("UPDATE managers SET balance=100 WHERE id=?", (mgr,))
        self.client.get("/logout")
        self.login_manager(login)
        self.client.post("/withdrawals/request", data={"amount": "50"})
        with self.app.app_context():
            w = query_one("SELECT commission_pct, list_price FROM withdrawals WHERE manager_id=?", (mgr,))
        self.assertEqual(w["commission_pct"], 30)
        self.assertGreaterEqual(w["list_price"], 65)

    def test_manager_cannot_change_commission(self):
        _, login = self.make_manager()
        self.login_manager(login)
        r = self.client.post("/settings/commission", data={"commission_pct": "5"})
        self.assertEqual(r.status_code, 403)


class TestManagerBalanceAdjustment(Base):
    def test_admin_can_add_and_subtract(self):
        mgr, _ = self.make_manager()
        self.login_admin()
        self.client.post(f"/managers/{mgr}/adjust-balance", data={"amount": "25", "note": "бонус"})
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
        self.assertEqual(manager["balance"], 25)

        self.client.post(f"/managers/{mgr}/adjust-balance", data={"amount": "-10", "note": "коррекция"})
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
        self.assertEqual(manager["balance"], 15)

    def test_cannot_force_negative_balance(self):
        mgr, _ = self.make_manager()
        self.login_admin()
        r = self.client.post(f"/managers/{mgr}/adjust-balance", data={"amount": "-5"}, follow_redirects=True)
        self.assertIn("отрицательным", r.get_data(as_text=True))
        with self.app.app_context():
            manager = query_one("SELECT balance FROM managers WHERE id=?", (mgr,))
        self.assertEqual(manager["balance"], 0)

    def test_manager_cannot_adjust_own_balance(self):
        mgr, login = self.make_manager()
        self.login_manager(login)
        r = self.client.post(f"/managers/{mgr}/adjust-balance", data={"amount": "10"})
        self.assertEqual(r.status_code, 403)


class TestAdminBalanceAdjustment(Base):
    def test_admin_can_add_and_subtract(self):
        mgr, _ = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_admin()
        self.client.post(f"/leads/{lead_id}/adjust-balance", data={"amount": "25", "note": "бонус"})
        with self.app.app_context():
            lead = query_one("SELECT balance FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 25)

        self.client.post(f"/leads/{lead_id}/adjust-balance", data={"amount": "-10", "note": "коррекция"})
        with self.app.app_context():
            lead = query_one("SELECT balance FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 15)

    def test_cannot_force_negative_balance(self):
        mgr, _ = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_admin()
        r = self.client.post(f"/leads/{lead_id}/adjust-balance", data={"amount": "-5"}, follow_redirects=True)
        self.assertIn("отрицательным", r.get_data(as_text=True))
        with self.app.app_context():
            lead = query_one("SELECT balance FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["balance"], 0)

    def test_adjustment_is_logged_and_manager_notified(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_admin()
        self.client.post(f"/leads/{lead_id}/adjust-balance", data={"amount": "12", "note": "test note"})
        with self.app.app_context():
            ledger = query_one("SELECT amount, reason, note FROM balance_ledger WHERE lead_id=?", (lead_id,))
            notif = query_one("SELECT message FROM notifications WHERE manager_id=?", (mgr,))
        self.assertEqual(ledger["amount"], 12)
        self.assertEqual(ledger["reason"], "admin_adjustment")
        self.assertEqual(ledger["note"], "test note")
        self.assertIsNotNone(notif)

    def test_manager_cannot_adjust_balance(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        r = self.client.post(f"/leads/{lead_id}/adjust-balance", data={"amount": "10"})
        self.assertEqual(r.status_code, 403)


class TestNotifications(Base):
    def test_submission_notifies_admins(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        with self.app.app_context():
            admin_id = query_one("SELECT id FROM managers WHERE role='admin'")["id"]
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        with self.app.app_context():
            notif = query_one("SELECT message FROM notifications WHERE manager_id=?", (admin_id,))
        self.assertIsNotNone(notif)
        self.assertIn("проверку", notif["message"])

    def test_approval_notifies_manager_with_comment(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        self.client.get("/logout")
        self.login_admin()
        with self.app.app_context():
            sub_id = query_one("SELECT id FROM submissions WHERE lead_id=?", (lead_id,))["id"]
        self.client.post(f"/submissions/{sub_id}/review",
                         data={"decision": "approved", "comment": "Молодец"})
        with self.app.app_context():
            notif = query_one("SELECT message FROM notifications WHERE manager_id=? ORDER BY id DESC", (mgr,))
        self.assertIn("Молодец", notif["message"])


class TestScreenshotUpload(Base):
    def test_rejects_non_image_extension(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        bad_file = (io.BytesIO(b"not an image"), "proof.txt")
        r = self.client.post(f"/leads/{lead_id}/submit",
                             data={"round_slot": "12:00", "screenshot": bad_file},
                             content_type="multipart/form-data", follow_redirects=True)
        self.assertIn("Прикрепите скриншот", r.get_data(as_text=True))

    def test_missing_screenshot_rejected(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        r = self.client.post(f"/leads/{lead_id}/submit", data={"round_slot": "12:00"}, follow_redirects=True)
        self.assertIn("Прикрепите скриншот", r.get_data(as_text=True))

    def test_uploaded_screenshot_is_servable_only_when_logged_in(self):
        mgr, login = self.make_manager()
        lead_id = self.make_lead(mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/submit",
                         data={"round_slot": "12:00", "screenshot": fake_image()},
                         content_type="multipart/form-data")
        with self.app.app_context():
            filename = query_one("SELECT screenshot FROM submissions WHERE lead_id=?", (lead_id,))["screenshot"]
        r = self.client.get(f"/media/{filename}")
        self.assertEqual(r.status_code, 200)

        self.client.get("/logout")
        r2 = self.client.get(f"/media/{filename}", follow_redirects=False)
        self.assertEqual(r2.status_code, 302)

    def test_path_traversal_in_filename_rejected(self):
        self.login_admin()
        r = self.client.get("/media/..%2F..%2Fetc%2Fpasswd")
        self.assertIn(r.status_code, (400, 404))


if __name__ == "__main__":
    unittest.main()
