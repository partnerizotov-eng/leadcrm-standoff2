"""Lead CRM test suite. Runs with the standard library only:
python -m unittest
"""
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
from app.security import reset_rate_limits, hash_password  # noqa: E402
from app.leads import normalize_vk_id, add_lead, next_manager_id, bulk_import  # noqa: E402


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


class TestAdminBootstrap(Base):
    def test_admin_created_on_startup(self):
        with self.app.app_context():
            row = query_one("SELECT role FROM managers WHERE login='admin'")
        self.assertEqual(row["role"], "admin")

    def test_bootstrap_idempotent(self):
        with self.app.app_context():
            from app.db import ensure_admin
            ensure_admin()
            ensure_admin()
            count = query_one("SELECT COUNT(*) c FROM managers WHERE role='admin'")["c"]
        self.assertEqual(count, 1)


class TestVkIdNormalization(unittest.TestCase):
    def test_full_url(self):
        self.assertEqual(normalize_vk_id("https://vk.com/id12345"), "id12345")

    def test_bare_domain(self):
        self.assertEqual(normalize_vk_id("vk.com/durov"), "durov")

    def test_with_at_sign(self):
        self.assertEqual(normalize_vk_id("@durov"), "durov")

    def test_bare_username(self):
        self.assertEqual(normalize_vk_id("durov"), "durov")

    def test_mixed_case_and_slash(self):
        self.assertEqual(normalize_vk_id("VK.COM/Durov/"), "durov")

    def test_query_string_stripped(self):
        self.assertEqual(normalize_vk_id("vk.com/id1?ref=abc"), "id1")

    def test_www_and_m_subdomains(self):
        self.assertEqual(normalize_vk_id("https://m.vk.com/id1"), "id1")
        self.assertEqual(normalize_vk_id("https://www.vk.com/id1"), "id1")


class TestDeduplication(Base):
    def test_same_lead_added_twice_is_not_duplicated(self):
        mgr_id, _ = self.make_manager()
        with self.app.app_context():
            id1, created1, _ = add_lead("vk.com/id999", "Group A", mgr_id)
            id2, created2, _ = add_lead("https://vk.com/id999", "Group B", mgr_id)
        self.assertTrue(created1)
        self.assertFalse(created2)
        self.assertEqual(id1, id2)

    def test_second_finder_does_not_steal_ownership(self):
        mgr1, _ = self.make_manager("First")
        mgr2, _ = self.make_manager("Second")
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/shared_target", "Group A", mgr1)
            add_lead("vk.com/shared_target", "Group B", mgr2)  # mgr2 tries to claim it too
            owner = query_one("SELECT assigned_manager_id FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(owner["assigned_manager_id"], mgr1)

    def test_route_warns_about_existing_owner(self):
        mgr1, login1 = self.make_manager("Owner One")
        mgr2, login2 = self.make_manager("Owner Two")
        with self.app.app_context():
            add_lead("vk.com/taken_lead", "Group A", mgr1)

        self.login_manager(login2)
        r = self.client.post("/leads/add", data={"vk_url": "vk.com/taken_lead"}, follow_redirects=True)
        body = r.get_data(as_text=True)
        self.assertIn("уже существует", body)
        self.assertIn("Owner One", body)


class TestRoundRobinAssignment(Base):
    def test_bulk_import_balances_across_managers(self):
        m1, _ = self.make_manager("A")
        m2, _ = self.make_manager("B")
        with self.app.app_context():
            added, dup, _ = bulk_import([f"vk.com/bulk{i}" for i in range(10)], "Bulk Group")
            counts = query_all_helper(self.app, "SELECT assigned_manager_id, COUNT(*) c FROM leads "
                                      "WHERE assigned_manager_id IN (?,?) GROUP BY assigned_manager_id",
                                      (m1, m2))
        self.assertEqual(added, 10)
        self.assertEqual(dup, 0)
        # Roughly balanced — neither manager should have gotten everything.
        counts_map = {r["assigned_manager_id"]: r["c"] for r in counts}
        self.assertIn(m1, counts_map)
        self.assertIn(m2, counts_map)
        self.assertLessEqual(abs(counts_map[m1] - counts_map[m2]), 1)

    def test_inactive_manager_gets_no_new_leads(self):
        active, _ = self.make_manager("Active")
        inactive, _ = self.make_manager("Inactive")
        with self.app.app_context():
            execute("UPDATE managers SET is_active=0 WHERE id=?", (inactive,))
            for i in range(5):
                add_lead(f"vk.com/rr{i}", "G", None, assign_to_finder=False)
            row = query_one("SELECT COUNT(*) c FROM leads WHERE assigned_manager_id=?", (inactive,))
        self.assertEqual(row["c"], 0)

    def test_next_manager_prefers_least_loaded(self):
        light, _ = self.make_manager("Light")
        heavy, _ = self.make_manager("Heavy")
        with self.app.app_context():
            for i in range(5):
                add_lead(f"vk.com/heavyload{i}", "G", heavy, assign_to_finder=True)
            picked = next_manager_id()
        self.assertEqual(picked, light)


class TestOutreachAndFunnel(Base):
    def test_marking_contacted_moves_status_and_logs(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/contactme", "G", mgr)
        self.login_manager(login)
        r = self.client.post(f"/leads/{lead_id}/contact", data={}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            lead = query_one("SELECT status, first_contacted_at FROM leads WHERE id=?", (lead_id,))
            log_count = query_one("SELECT COUNT(*) c FROM outreach_log WHERE lead_id=?", (lead_id,))["c"]
        self.assertEqual(lead["status"], "contacted")
        self.assertIsNotNone(lead["first_contacted_at"])
        self.assertEqual(log_count, 1)

    def test_manager_cannot_touch_someone_elses_lead(self):
        owner, _ = self.make_manager("Owner")
        _, other_login = self.make_manager("Other")
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/notyours", "G", owner)
        self.login_manager(other_login)
        r = self.client.post(f"/leads/{lead_id}/contact", data={}, follow_redirects=True)
        self.assertIn("не найден или не ваш", r.get_data(as_text=True))
        with self.app.app_context():
            lead = query_one("SELECT status FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["status"], "new")  # untouched

    def test_admin_can_touch_any_lead(self):
        mgr, _ = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/adminaccess", "G", mgr)
        self.login_admin()
        r = self.client.post(f"/leads/{lead_id}/status", data={"status": "declined"}, follow_redirects=True)
        self.assertEqual(r.status_code, 200)
        with self.app.app_context():
            lead = query_one("SELECT status FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["status"], "declined")


class TestParticipationTracking(Base):
    def test_first_participation_sets_participated(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/player1", "G", mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/participate", data={"round_slot": "12:00"})
        with self.app.app_context():
            lead = query_one("SELECT status, participation_count FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["status"], "participated")
        self.assertEqual(lead["participation_count"], 1)

    def test_second_participation_sets_returning(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/player2", "G", mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/participate", data={"round_slot": "12:00", "round_date": "2026-01-01"})
        self.client.post(f"/leads/{lead_id}/participate", data={"round_slot": "18:00", "round_date": "2026-01-01"})
        with self.app.app_context():
            lead = query_one("SELECT status, participation_count FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["status"], "returning")
        self.assertEqual(lead["participation_count"], 2)

    def test_same_round_twice_is_not_double_counted(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            lead_id, _, _ = add_lead("vk.com/player3", "G", mgr)
        self.login_manager(login)
        self.client.post(f"/leads/{lead_id}/participate", data={"round_slot": "12:00", "round_date": "2026-01-01"})
        r = self.client.post(f"/leads/{lead_id}/participate",
                             data={"round_slot": "12:00", "round_date": "2026-01-01"}, follow_redirects=True)
        self.assertIn("Уже отмечено", r.get_data(as_text=True))
        with self.app.app_context():
            lead = query_one("SELECT participation_count FROM leads WHERE id=?", (lead_id,))
        self.assertEqual(lead["participation_count"], 1)


class TestScripts(Base):
    def test_reply_rate_calculated(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            script_id = execute("INSERT INTO scripts (label, body, created_by) VALUES (?,?,?)",
                                ("Test Script", "Hello!", mgr))
            l1, _, _ = add_lead("vk.com/s1", "G", mgr)
            l2, _, _ = add_lead("vk.com/s2", "G", mgr)
            execute("INSERT INTO outreach_log (lead_id, manager_id, script_id, response) VALUES (?,?,?,'replied')",
                    (l1, mgr, script_id))
            execute("INSERT INTO outreach_log (lead_id, manager_id, script_id, response) VALUES (?,?,?,'no_reply')",
                    (l2, mgr, script_id))
        self.login_manager(login)
        r = self.client.get("/scripts")
        self.assertIn("50%", r.get_data(as_text=True))


class TestRBAC(Base):
    def test_manager_only_sees_own_leads(self):
        m1, login1 = self.make_manager("M1")
        m2, _ = self.make_manager("M2")
        with self.app.app_context():
            add_lead("vk.com/mine", "G", m1, name="MyLead")
            add_lead("vk.com/theirs", "G", m2, name="TheirLead")
        self.login_manager(login1)
        r = self.client.get("/leads")
        body = r.get_data(as_text=True)
        self.assertIn("MyLead", body)
        self.assertNotIn("TheirLead", body)

    def test_admin_sees_all_leads(self):
        m1, _ = self.make_manager("M1")
        m2, _ = self.make_manager("M2")
        with self.app.app_context():
            add_lead("vk.com/one", "G", m1, name="LeadOne")
            add_lead("vk.com/two", "G", m2, name="LeadTwo")
        self.login_admin()
        r = self.client.get("/leads")
        body = r.get_data(as_text=True)
        self.assertIn("LeadOne", body)
        self.assertIn("LeadTwo", body)

    def test_manager_cannot_create_managers(self):
        _, login = self.make_manager()
        self.login_manager(login)
        r = self.client.post("/managers/create", data={"login": "x", "password": "xxxxxx", "name": "X"})
        self.assertEqual(r.status_code, 403)

    def test_manager_cannot_bulk_import(self):
        _, login = self.make_manager()
        self.login_manager(login)
        r = self.client.post("/leads/bulk-import", data={"profiles": "vk.com/x"})
        self.assertEqual(r.status_code, 403)

    def test_unauthenticated_redirected_to_login(self):
        r = self.client.get("/leads", follow_redirects=False)
        self.assertEqual(r.status_code, 302)
        self.assertIn("/login", r.headers["Location"])


class TestSecurity(Base):
    def test_login_rate_limited(self):
        for _ in range(10):
            self.client.post("/login", data={"login": "admin", "password": "wrong"})
        r = self.client.post("/login", data={"login": "admin", "password": "wrong"})
        self.assertEqual(r.status_code, 429)

    def test_wrong_password_rejected(self):
        r = self.client.post("/login", data={"login": "admin", "password": "wrong"}, follow_redirects=True)
        self.assertIn("Неверный логин", r.get_data(as_text=True))

    def test_inactive_manager_cannot_log_in(self):
        mgr, login = self.make_manager()
        with self.app.app_context():
            execute("UPDATE managers SET is_active=0 WHERE id=?", (mgr,))
        r = self.client.post("/login", data={"login": login, "password": "mgrpass"}, follow_redirects=True)
        self.assertIn("Неверный логин", r.get_data(as_text=True))

    def test_csrf_enforced_outside_testing_mode(self):
        self.app.config["TESTING"] = False
        try:
            r = self.client.post("/login", data={"login": "admin", "password": "adminpass123"})
            self.assertEqual(r.status_code, 400)
        finally:
            self.app.config["TESTING"] = True


def query_all_helper(app, sql, params):
    from app.db import query_all
    with app.app_context():
        return query_all(sql, params)


if __name__ == "__main__":
    unittest.main()
