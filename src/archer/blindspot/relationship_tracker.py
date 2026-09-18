"""
Relationship Tracker for ARCHER Blindspot Agent.
Tracks social interactions, commitments, and relationship health.

Rewired 2026-09-16: every method here used to be a stub (logger.info/debug
or a hardcoded mock return) even though the social_contacts/
social_interactions/social_commitments SQLite tables it references have
existed since before this session. sqlite_store.py now has real accessor
methods for those tables (upsert_contact, log_interaction, track_commitment,
find_neglected_contacts, find_unfulfilled_commitments) -- this class is now
a thin, real wrapper over them, kept mainly so BlindspotAgent's existing
call sites don't need to change.
"""

from __future__ import annotations
from datetime import datetime
from typing import Any, Dict, List, Optional
from loguru import logger


class RelationshipTracker:
    """Tracks social relationships and interaction patterns."""

    def __init__(self, db_store: Any):
        self.db = db_store

    def add_contact(self, name: str, relationship: str, metadata: Optional[Dict] = None):
        """Register or update a contact."""
        self.db.upsert_contact(name=name, relationship=relationship, metadata=metadata)
        logger.debug(f"Social contact added/updated: {name} ({relationship})")

    def log_interaction(self, person: str, interaction_type: str, notes: Optional[str] = None):
        """Record an interaction with a person."""
        self.db.log_interaction(contact_name=person, interaction_type=interaction_type, notes=notes)
        logger.info(f"Interaction with {person} logged: {interaction_type}")

    def track_commitment(self, person: str, promise: str, due_date: Optional[datetime] = None):
        """Record a promise made to someone."""
        due_str = due_date.isoformat() if due_date else None
        self.db.track_commitment(contact_name=person, promise=promise, due_date=due_str)
        logger.info(f"Commitment to {person} tracked: '{promise}'")

    def identify_neglected_relationships(self) -> List[Dict[str, Any]]:
        """Find relationships that haven't been maintained (last_interaction_at
        older than the contact's own typical_interval_days)."""
        return self.db.find_neglected_contacts()

    def find_unfulfilled_commitments(self, grace_period_days: int = 3) -> List[Dict[str, Any]]:
        """Find promises that haven't been kept."""
        return self.db.find_unfulfilled_commitments(grace_period_days=grace_period_days)

    def analyze_relationship_health(self, person: str) -> Dict[str, Any]:
        """Overall relationship health assessment, derived from real
        interaction/commitment history rather than a fixed mock score."""
        contact = self.db.get_contact_by_name(person)
        if not contact:
            return {"health_score": None, "status": "unknown", "issues": [], "suggestions": []}

        interactions = self.db.get_interactions(contact_name=person, limit=20)
        unfulfilled = [
            c for c in self.db.find_unfulfilled_commitments(grace_period_days=3)
            if c.get("contact_name", "").lower() == person.lower()
        ]

        issues: List[str] = []
        score = 1.0
        if contact.get("typical_interval_days") and contact.get("last_interaction_at") is None:
            issues.append("No logged interaction yet")
            score -= 0.2
        neglected = any(
            n["id"] == contact["id"] for n in self.db.find_neglected_contacts()
        )
        if neglected:
            issues.append("Overdue for contact based on your usual cadence")
            score -= 0.3
        if unfulfilled:
            issues.append(f"{len(unfulfilled)} unfulfilled commitment(s)")
            score -= 0.2 * min(len(unfulfilled), 2)

        score = max(0.0, min(1.0, score))
        status = "stable" if score >= 0.7 else ("attention_needed" if score >= 0.4 else "neglected")
        suggestions = []
        if unfulfilled:
            suggestions.append(f"Follow up on: {unfulfilled[0]['promise']}")
        if neglected:
            suggestions.append(f"Reach out to {person} -- it's been a while")

        return {
            "health_score": round(score, 2),
            "status": status,
            "issues": issues,
            "suggestions": suggestions,
            "interaction_count": len(interactions),
        }
