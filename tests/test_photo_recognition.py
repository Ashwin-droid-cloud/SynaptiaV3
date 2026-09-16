"""
Unit tests for Static Photo Multi-Face Recognition and Last Conversation Recall.
"""

import sys
import os
import json
import pytest

root_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, root_dir)

from vision_memory import VisionMemoryEngine, format_relative_time
from app import app


class TestPhotoMemoryRecognition:

    @pytest.fixture
    def engine(self):
        return VisionMemoryEngine(seed_defaults=True)

    @pytest.fixture
    def client(self):
        app.config["TESTING"] = True
        with app.test_client() as client:
            yield client

    def test_get_last_conversation_enrolled(self, engine):
        """Verify retrieving the most recent conversation for Sarah Jenkins."""
        conv = engine.get_last_conversation("person_001")
        assert conv["has_conversation"] is True
        assert conv["person_name"] == "Sarah Jenkins"
        assert conv["relationship"] == "Daughter"
        assert "soccer" in conv["summary"].lower() or "brunch" in conv["summary"].lower() or "architecture" in conv["summary"].lower()
        assert conv["sentiment"] is not None
        assert len(conv["recall_cues"]) >= 1
        assert conv["total_interactions"] >= 1

    def test_get_last_conversation_not_enrolled(self, engine):
        """Verify handling of unfamiliar person without records."""
        conv = engine.get_last_conversation("non_existent_id")
        assert conv["has_conversation"] is False
        assert conv["timestamp"] is None

    def test_recognize_photo_faces_met_and_unmet(self, engine):
        """Verify multi-person photo analysis returns both met and unmet individuals."""
        faces_payload = [
            {
                "box": {"x": 50, "y": 50, "width": 120, "height": 120},
                "hint_name": "Dr. Aris Thorne",
                "crop": "data:image/jpeg;base64,mock"
            },
            {
                "box": {"x": 300, "y": 50, "width": 120, "height": 120},
                "descriptor": [0.42] * 128,
                "crop": "data:image/jpeg;base64,mock2"
            }
        ]

        report = engine.recognize_photo_faces(faces_payload, threshold=0.55)
        assert report["total_faces"] == 2
        assert report["met_count"] == 1
        assert report["unmet_count"] == 1

        res_met = report["results"][0]
        assert res_met["met_in_past"] is True
        assert res_met["person"]["name"] == "Dr. Aris Thorne"
        assert res_met["last_conversation"]["has_conversation"] is True
        assert "metrics" in res_met["last_conversation"]["summary"].lower() or "puzzle" in res_met["last_conversation"]["summary"].lower()

        res_unmet = report["results"][1]
        assert res_unmet["met_in_past"] is False
        assert res_unmet["person"] is None
        assert "not met this person" in res_unmet["status_message"].lower()

    def test_api_sample_photos(self, client):
        """Verify sample photos endpoint returns presets with proper metadata."""
        resp = client.get("/api/v2/sample-photos")
        assert resp.status_code == 200
        data = resp.get_json()
        assert "samples" in data
        assert len(data["samples"]) >= 5
        sample_ids = [s["id"] for s in data["samples"]]
        assert "sample_sarah" in sample_ids
        assert "sample_group" in sample_ids
        assert "sample_unknown" in sample_ids

    def test_api_recognize_photo_endpoint(self, client):
        """Verify POST /api/v2/recognize-photo returns structured recognition results."""
        from app import vision_memory
        p = vision_memory.enroll_person(
            name="Marcus Vance",
            relationship="Research Partner",
            description="Discussed edge AI memory indexing."
        )
        vision_memory.record_interaction(
            p["id"],
            summary="Discussed edge AI memory indexing.",
            transcript="We went through the end-to-end latency benchmarks for face matching on edge devices."
        )
        payload = {
            "faces": [
                {
                    "box": {"x": 10, "y": 10, "width": 80, "height": 80},
                    "hint_name": "Marcus Vance",
                    "crop": "data:image/jpeg;base64,mock"
                }
            ],
            "threshold": 0.55
        }
        resp = client.post(
            "/api/v2/recognize-photo",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert resp.status_code == 200
        data = resp.get_json()
        assert data["total_faces"] == 1
        assert data["met_count"] == 1
        assert data["results"][0]["person"]["name"] == "Marcus Vance"
        assert data["results"][0]["last_conversation"]["has_conversation"] is True
        vision_memory.delete_person(p["id"])

    def test_api_photo_enroll_flow(self, client, engine):
        """Verify enrolling an unfamiliar face from photo adds person and initial conversation."""
        dummy_name = "Test Visitor Alice"
        payload = {
            "name": dummy_name,
            "relationship": "Friend",
            "description": "Met at coffee shop",
            "descriptor": [0.123] * 128,
            "initial_note": "Discussed shared interest in classical music."
        }
        resp = client.post(
            "/api/v2/photo/enroll",
            data=json.dumps(payload),
            content_type="application/json"
        )
        assert resp.status_code == 201
        data = resp.get_json()
        assert data["status"] == "success"
        assert data["profile"]["name"] == dummy_name
        assert data["last_conversation"]["has_conversation"] is True
        assert "classical music" in data["last_conversation"]["summary"]

        # Clean up
        person_id = data["profile"]["id"]
        client.delete(f"/api/v2/people/{person_id}")
