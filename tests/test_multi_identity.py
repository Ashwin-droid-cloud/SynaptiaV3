"""
Tests for multi-individual face identity management, relationships,
and acoustic voice verification / candidate disambiguation.
"""

import sys
import os
import pytest

# Add paths for both root and inference modules
root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
inference_dir = os.path.join(root_dir, "SynaptiaV2-main", "inference")
sys.path.insert(0, root_dir)
sys.path.insert(0, inference_dir)

from database import upsert_face_identity, list_face_identities, upsert_voice_identity, get_voice_identity
from voice_verifier import cosine_similarity, verify_speaker_voice


class TestMultiIndividualDistinction:

    def test_upsert_and_list_multiple_identities(self):
        """Test enrolling multiple distinct individuals with their respective relationships."""
        desc1 = [0.1] * 128
        desc2 = [0.9] * 128

        person1 = upsert_face_identity("Alice", desc1, relationship="Daughter", description="Visits every Sunday")
        person2 = upsert_face_identity("Dr. Bob", desc2, relationship="Primary Neurologist", description="Cognitive health checkups")

        assert person1["name"] == "Alice"
        assert person1["relationship"] == "Daughter"
        assert person2["name"] == "Dr. Bob"
        assert person2["relationship"] == "Primary Neurologist"

        identities = list_face_identities()
        names = [id["name"] for id in identities]
        assert "Alice" in names
        assert "Dr. Bob" in names

        # Verify distinct identities preserve relationships
        alice_rec = next(id for id in identities if id["name"] == "Alice")
        bob_rec = next(id for id in identities if id["name"] == "Dr. Bob")
        assert alice_rec["relationship"] == "Daughter"
        assert bob_rec["relationship"] == "Primary Neurologist"

    def test_acoustic_candidate_voice_distinction(self):
        """Test disambiguating between multiple speaker voiceprints."""
        voice_alice = [1.0, 0.9, 0.85, 0.7, 0.1, 0.05, 0.0, 0.0]
        voice_bob   = [0.0, 0.05, 0.1, 0.2, 0.7, 0.85, 0.9, 1.0]
        voice_bystander = [-0.5, -0.4, -0.6, -0.3, -0.7, -0.2, -0.5, -0.6]

        upsert_voice_identity("Alice", voice_alice)
        upsert_voice_identity("Bob", voice_bob)

        # Incoming utterance closely matching Alice's voice
        candidate_sample = [0.95, 0.88, 0.82, 0.68, 0.12, 0.04, 0.0, 0.0]

        alice_match, alice_sim = verify_speaker_voice(candidate_sample, voice_alice, threshold=0.6)
        bob_match, bob_sim = verify_speaker_voice(candidate_sample, voice_bob, threshold=0.6)

        assert alice_match is True
        assert alice_sim > 0.95
        assert bob_match is False
        assert bob_sim < 0.35

        # Test bystander rejection
        bystander_match, bystander_sim = verify_speaker_voice(voice_bystander, voice_alice, threshold=0.6)
        assert bystander_match is False
        assert bystander_sim < 0.3

    def test_identify_best_speaker_among_enrolled(self):
        """Test identifying best matching speaker from candidates."""
        from voice_verifier import identify_best_speaker
        profiles = {
            "Alice": [1.0, 0.9, 0.85, 0.7, 0.1, 0.05, 0.0, 0.0],
            "Bob":   [0.0, 0.05, 0.1, 0.2, 0.7, 0.85, 0.9, 1.0],
        }
        candidate_alice = [0.95, 0.88, 0.82, 0.68, 0.12, 0.04, 0.0, 0.0]
        candidate_bob = [0.02, 0.08, 0.15, 0.22, 0.65, 0.82, 0.88, 0.95]

        best_name, sim = identify_best_speaker(candidate_alice, profiles, threshold=0.55)
        assert best_name == "Alice"
        assert sim > 0.9

        best_name, sim = identify_best_speaker(candidate_bob, profiles, threshold=0.55)
        assert best_name == "Bob"
        assert sim > 0.9

    def test_distinct_conversation_store_isolation(self):
        """Verify conversation utterances are strictly isolated per individual without cross-contamination."""
        from database import record_distinct_conversation, get_distinct_conversations, clear_person_conversations

        clear_person_conversations("Alice")
        clear_person_conversations("Bob")

        record_distinct_conversation("Alice", "Remember to take your medicine at 2pm", summary="Take medicine 2pm")
        record_distinct_conversation("Bob", "Your appointment is scheduled for Friday", summary="Appointment Friday")

        alice_convs = get_distinct_conversations("Alice")
        bob_convs = get_distinct_conversations("Bob")

        assert len(alice_convs) == 1
        assert len(bob_convs) == 1

        assert alice_convs[0]["text"] == "Remember to take your medicine at 2pm"
        assert alice_convs[0]["summary"] == "Take medicine 2pm"

        assert bob_convs[0]["text"] == "Your appointment is scheduled for Friday"
        assert bob_convs[0]["summary"] == "Appointment Friday"

        # Verify no cross-talk in Alice's store
        assert not any("Friday" in c["text"] for c in alice_convs)
        # Verify no cross-talk in Bob's store
        assert not any("medicine" in c["text"] for c in bob_convs)
