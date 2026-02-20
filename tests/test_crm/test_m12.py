"""M12 tests — CRM database, dedup, cooldown."""

from __future__ import annotations

import pytest
from pathlib import Path
from datetime import datetime, timedelta


@pytest.fixture
def tmp_db(tmp_path):
    return tmp_path / "test_crm.db"


# ---------------------------------------------------------------------------
# database
# ---------------------------------------------------------------------------

class TestCRMDatabase:
    def test_upsert_new_contact(self, tmp_db):
        from src.crm.database import upsert_contact, get_contact_by_email
        c = upsert_contact("alice@stripe.com", name="Alice", company="Stripe", db_path=tmp_db)
        assert c["id"]
        assert c["email"] == "alice@stripe.com"
        assert c["company"] == "Stripe"

    def test_upsert_updates_existing(self, tmp_db):
        from src.crm.database import upsert_contact
        upsert_contact("bob@google.com", name="Bob", db_path=tmp_db)
        updated = upsert_contact("bob@google.com", company="Google", db_path=tmp_db)
        assert updated["company"] == "Google"
        assert updated["name"] == "Bob"  # Name preserved

    def test_list_contacts_filter_status(self, tmp_db):
        from src.crm.database import upsert_contact, update_contact_status, list_contacts
        c = upsert_contact("cold@test.com", db_path=tmp_db)
        update_contact_status(c["id"], "cold", db_path=tmp_db)
        cold = list_contacts(status="cold", db_path=tmp_db)
        assert any(x["email"] == "cold@test.com" for x in cold)

    def test_create_conversation(self, tmp_db):
        from src.crm.database import upsert_contact, create_conversation
        c = upsert_contact("cv@test.com", db_path=tmp_db)
        conv = create_conversation(c["id"], subject="Eng Role", db_path=tmp_db)
        assert conv["id"]
        assert conv["stage"] == "initial"
        assert conv["contact_id"] == c["id"]

    def test_log_touchpoint_updates_contact(self, tmp_db):
        from src.crm.database import upsert_contact, log_touchpoint, get_contact
        c = upsert_contact("tp@test.com", db_path=tmp_db)
        log_touchpoint(c["id"], type="email_sent", subject="Hello", direction="outbound", db_path=tmp_db)
        updated = get_contact(c["id"], db_path=tmp_db)
        assert updated["total_touchpoints"] == 1
        assert updated["last_contacted_at"] is not None

    def test_log_inbound_updates_stage(self, tmp_db):
        from src.crm.database import upsert_contact, create_conversation, log_touchpoint, get_conversations
        c = upsert_contact("inb@test.com", db_path=tmp_db)
        conv = create_conversation(c["id"], db_path=tmp_db)
        log_touchpoint(
            c["id"], type="email_received", direction="inbound",
            conversation_id=conv["id"], db_path=tmp_db,
        )
        convs = get_conversations(contact_id=c["id"], db_path=tmp_db)
        assert convs[0]["stage"] == "replied"

    def test_get_todays_actions_respects_cooldown(self, tmp_db):
        from src.crm.database import upsert_contact, create_conversation, update_conversation_stage, get_todays_actions
        c = upsert_contact("act@test.com", db_path=tmp_db)
        conv = create_conversation(c["id"], db_path=tmp_db)
        # Set next_follow_up to today
        today = datetime.utcnow().date().isoformat()
        update_conversation_stage(conv["id"], "initial", next_follow_up=today, db_path=tmp_db)

        # Set cooldown to future (should NOT appear)
        from src.crm.database import _get_conn, init_crm_db
        init_crm_db(tmp_db)
        conn = _get_conn(tmp_db)
        future = (datetime.utcnow() + timedelta(days=5)).isoformat()
        conn.execute("UPDATE conversations SET cooldown_until = ? WHERE id = ?", (future, conv["id"]))
        conn.commit()
        conn.close()

        actions = get_todays_actions(db_path=tmp_db)
        assert not any(a["conv_id"] == conv["id"] for a in actions)

    def test_crm_stats(self, tmp_db):
        from src.crm.database import upsert_contact, get_crm_stats
        upsert_contact("stat1@test.com", db_path=tmp_db)
        upsert_contact("stat2@test.com", db_path=tmp_db)
        stats = get_crm_stats(db_path=tmp_db)
        assert stats["total_contacts"] >= 2
        assert "reply_rate" in stats
        assert "follow_ups_due" in stats


# ---------------------------------------------------------------------------
# dedup
# ---------------------------------------------------------------------------

class TestDedup:
    def test_normalize_email_gmail_dots(self):
        from src.crm.dedup import normalize_email
        assert normalize_email("john.doe@gmail.com") == normalize_email("johndoe@gmail.com")

    def test_normalize_email_alias(self):
        from src.crm.dedup import normalize_email
        assert normalize_email("alice+work@gmail.com") == normalize_email("alice@gmail.com")

    def test_emails_same_person(self):
        from src.crm.dedup import emails_are_same_person
        assert emails_are_same_person("alice+recruiter@gmail.com", "alice@gmail.com")

    def test_emails_different_person(self):
        from src.crm.dedup import emails_are_same_person
        assert not emails_are_same_person("alice@stripe.com", "bob@stripe.com")

    def test_name_similarity_high(self):
        from src.crm.dedup import name_similarity
        assert name_similarity("John Smith", "John Smith") >= 0.99

    def test_name_similarity_low(self):
        from src.crm.dedup import name_similarity
        assert name_similarity("Alice Brown", "Bob Jones") < 0.5

    def test_find_duplicates_email_match(self, tmp_db):
        from src.crm.database import upsert_contact
        from src.crm.dedup import find_duplicates
        c1 = upsert_contact("test.user@gmail.com", name="Test User", db_path=tmp_db)
        c2 = upsert_contact("testuser@gmail.com", name="Test User", db_path=tmp_db)
        dupes = find_duplicates(c1["id"], db_path=tmp_db)
        assert any(d["contact_id"] == c2["id"] for d in dupes)
        assert any(d["confidence"] >= 0.9 for d in dupes)

    def test_merge_contacts(self, tmp_db):
        from src.crm.database import upsert_contact, get_contact, log_touchpoint
        from src.crm.dedup import merge_contacts
        primary = upsert_contact("primary@test.com", name="Alice", company="Stripe", db_path=tmp_db)
        secondary = upsert_contact("secondary@test.com", name="", company="Stripe", db_path=tmp_db)
        log_touchpoint(secondary["id"], type="email_sent", db_path=tmp_db)

        merged = merge_contacts(primary["id"], secondary["id"], db_path=tmp_db)

        assert merged["total_touchpoints"] >= 1
        archived = get_contact(secondary["id"], db_path=tmp_db)
        assert archived["status"] == "archived"

    def test_merge_reraises_on_same_id(self, tmp_db):
        from src.crm.database import upsert_contact
        from src.crm.dedup import merge_contacts
        c = upsert_contact("same@test.com", db_path=tmp_db)
        with pytest.raises(ValueError, match="itself"):
            merge_contacts(c["id"], c["id"], db_path=tmp_db)


# ---------------------------------------------------------------------------
# cooldown
# ---------------------------------------------------------------------------

class TestCooldown:
    def test_can_contact_new_contact(self, tmp_db):
        from src.crm.database import upsert_contact
        from src.crm.cooldown import can_contact
        c = upsert_contact("new@test.com", db_path=tmp_db)
        allowed, reason = can_contact(c["id"], db_path=tmp_db)
        assert allowed
        assert reason == "ok"

    def test_blocked_contact_denied(self, tmp_db):
        from src.crm.database import upsert_contact, update_contact_status
        from src.crm.cooldown import can_contact
        c = upsert_contact("blocked@test.com", db_path=tmp_db)
        update_contact_status(c["id"], "blocked", db_path=tmp_db)
        allowed, reason = can_contact(c["id"], db_path=tmp_db)
        assert not allowed
        assert reason == "contact_blocked"

    def test_cooldown_after_recent_touch(self, tmp_db):
        from src.crm.database import upsert_contact, log_touchpoint, _get_conn, init_crm_db
        from src.crm.cooldown import can_contact
        c = upsert_contact("recent@test.com", db_path=tmp_db)
        # Set last_contacted to just now (within cooldown window)
        init_crm_db(tmp_db)
        conn = _get_conn(tmp_db)
        conn.execute(
            "UPDATE contacts SET last_contacted_at = ? WHERE id = ?",
            (datetime.utcnow().isoformat(), c["id"]),
        )
        conn.commit()
        conn.close()
        allowed, reason = can_contact(c["id"], db_path=tmp_db)
        assert not allowed
        assert "cooldown" in reason

    def test_suggest_next_followup_initial(self):
        from src.crm.cooldown import suggest_next_followup
        date = suggest_next_followup("initial")
        assert date > datetime.utcnow().date().isoformat()

    def test_next_stage_chain(self):
        from src.crm.cooldown import next_stage
        assert next_stage("initial") == "follow_up_1"
        assert next_stage("follow_up_1") == "follow_up_2"
        assert next_stage("follow_up_2") is None

    def test_apply_and_clear_cooldown(self, tmp_db):
        from src.crm.database import upsert_contact, create_conversation
        from src.crm.cooldown import apply_cooldown, clear_cooldown, can_contact
        c = upsert_contact("cd@test.com", db_path=tmp_db)
        conv = create_conversation(c["id"], db_path=tmp_db)
        apply_cooldown(conv["id"], days=5, db_path=tmp_db)
        # Clear it
        clear_cooldown(conv["id"], db_path=tmp_db)
        # Conversation-level check passes after clear
        allowed, reason = can_contact(c["id"], conv["id"], db_path=tmp_db)
        # Should be ok for conversation (contact-level may still block depending on state)
        assert "conversation_cooldown" not in reason
