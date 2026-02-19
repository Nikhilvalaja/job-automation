"""Tests for email classification rules engine.

Tests all rule categories with realistic sample emails.
No Gmail credentials needed — tests the pure classification logic.
"""

from __future__ import annotations

import pytest

from src.gmail.rules import ClassificationResult, classify_email, DEFAULT_RULES
from src.models import JobStatus


class TestAppliedClassification:
    def test_thanks_for_applying(self):
        result = classify_email(
            subject="Thanks for applying to Software Engineer at Google",
            body="We received your application and will review it shortly.",
        )
        assert result is not None
        assert result.status == JobStatus.APPLIED

    def test_application_received(self):
        result = classify_email(
            subject="Application Confirmation",
            body="Thank you for applying. Your application has been received.",
        )
        assert result is not None
        assert result.status == JobStatus.APPLIED

    def test_successfully_submitted(self):
        result = classify_email(
            subject="Your application was successfully submitted",
            body="",
        )
        assert result is not None
        assert result.status == JobStatus.APPLIED


class TestInterviewClassification:
    def test_schedule_interview(self):
        result = classify_email(
            subject="Schedule an Interview — Software Engineer",
            body="We'd like to set up a phone screen with you.",
        )
        assert result is not None
        assert result.status == JobStatus.INTERVIEW

    def test_move_forward(self):
        result = classify_email(
            subject="Next Steps — Your Application",
            body="We'd like to move forward with your application and schedule a technical interview.",
        )
        assert result is not None
        assert result.status == JobStatus.INTERVIEW

    def test_phone_screen_in_body(self):
        result = classify_email(
            subject="Follow up on your application",
            body="The hiring manager would like to schedule a phone screen with you next week.",
        )
        assert result is not None
        assert result.status == JobStatus.INTERVIEW
        assert result.confidence == "medium"  # body match, not subject


class TestAssessmentClassification:
    def test_coding_challenge(self):
        result = classify_email(
            subject="Complete your Coding Challenge",
            body="Please complete the following HackerRank assessment.",
        )
        assert result is not None
        assert result.status == JobStatus.ASSESSMENT

    def test_online_assessment(self):
        result = classify_email(
            subject="Online Assessment Invitation",
            body="You have been invited to complete a skills assessment.",
        )
        assert result is not None
        assert result.status == JobStatus.ASSESSMENT

    def test_take_home(self):
        result = classify_email(
            subject="Take-home Assignment — SWE Position",
            body="",
        )
        assert result is not None
        assert result.status == JobStatus.ASSESSMENT


class TestRejectClassification:
    def test_unfortunately(self):
        result = classify_email(
            subject="Update on your application",
            body="Unfortunately, we have decided to pursue other candidates at this time.",
        )
        assert result is not None
        assert result.status == JobStatus.REJECT

    def test_not_moving_forward(self):
        result = classify_email(
            subject="Application Status — Not Moving Forward",
            body="After careful review, we will not be moving forward with your application.",
        )
        assert result is not None
        assert result.status == JobStatus.REJECT

    def test_position_filled(self):
        result = classify_email(
            subject="Position Update",
            body="We regret to inform you that the position has been filled.",
        )
        assert result is not None
        assert result.status == JobStatus.REJECT


class TestOfferClassification:
    def test_congratulations(self):
        result = classify_email(
            subject="Congratulations! Offer from Google",
            body="We are pleased to offer you the position of Software Engineer.",
        )
        assert result is not None
        assert result.status == JobStatus.OFFER

    def test_offer_letter(self):
        result = classify_email(
            subject="Your Offer Letter — Software Engineer",
            body="Please review the attached compensation package.",
        )
        assert result is not None
        assert result.status == JobStatus.OFFER

    def test_start_date_in_body(self):
        result = classify_email(
            subject="Next Steps",
            body="Congratulations! We'd like to discuss your start date and onboarding.",
        )
        assert result is not None
        assert result.status == JobStatus.OFFER


class TestNoMatch:
    def test_unrelated_email(self):
        result = classify_email(
            subject="Your Amazon order has shipped",
            body="Track your package here.",
        )
        assert result is None

    def test_newsletter(self):
        result = classify_email(
            subject="Weekly Tech Newsletter",
            body="Top 10 programming languages in 2026.",
        )
        assert result is None

    def test_empty(self):
        result = classify_email(subject="", body="")
        assert result is None


class TestPriorityConflicts:
    def test_offer_beats_applied(self):
        """Offer (priority 6) should beat Applied (priority 2)."""
        result = classify_email(
            subject="Congratulations! Thanks for applying — here's your offer",
            body="",
        )
        assert result is not None
        assert result.status == JobStatus.OFFER

    def test_interview_beats_reject(self):
        """Interview (priority 5) should beat Reject (priority 3)."""
        result = classify_email(
            subject="Schedule an Interview",
            body="Unfortunately the original date didn't work, but we'd like to reschedule.",
        )
        assert result is not None
        assert result.status == JobStatus.INTERVIEW


class TestConfidence:
    def test_subject_match_is_high_confidence(self):
        result = classify_email(
            subject="Thanks for applying to SWE at Meta",
            body="No relevant keywords here.",
        )
        assert result is not None
        assert result.confidence == "high"

    def test_body_match_is_medium_confidence(self):
        result = classify_email(
            subject="Update on your application",
            body="We regret to inform you that we will not be moving forward.",
        )
        assert result is not None
        assert result.confidence == "medium"


class TestCaseInsensitive:
    def test_uppercase_subject(self):
        result = classify_email(
            subject="THANKS FOR APPLYING",
            body="",
        )
        assert result is not None
        assert result.status == JobStatus.APPLIED

    def test_mixed_case(self):
        result = classify_email(
            subject="Schedule An Interview With Our Team",
            body="",
        )
        assert result is not None
        assert result.status == JobStatus.INTERVIEW
