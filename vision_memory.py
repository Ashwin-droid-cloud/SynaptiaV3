"""
Synaptia V2 — Vision & Multimodal Memory Engine
Provides real-time person context management, face recognition tracking store,
interaction logging, and AI-assisted conversational memory summarization.
"""

import os
import time
import math
import json
import logging
from datetime import datetime
from typing import Dict, List, Optional, Any, Tuple

import requests

logger = logging.getLogger(__name__)

# Sample palette for avatars
AVATAR_COLORS = [
    "#6366f1", "#06b6d4", "#10b981", "#f59e0b",
    "#ec4899", "#8b5cf6", "#14b8a6", "#f43f5e"
]

DEFAULT_PROFILES = [
    {
        "id": "person_001",
        "name": "Sarah Jenkins",
        "relationship": "Daughter",
        "description": "Last spoke 2 days ago about her promotion to Lead Architect and the grandchildren visiting this weekend for soccer practice.",
        "avatar_color": "#6366f1",
        "sample_photo": "/static/samples/sarah_jenkins.jpg",
        "created_at": "2026-03-01T10:00:00",
        "last_seen": "2026-03-08T16:45:00",
        "confidence": 0.96,
        "tags": ["Family", "Frequent", "Priority"],
        "interactions": [
            {
                "ts": "2026-03-08T16:45:00",
                "summary": "Shared news regarding the architecture team expansion. Reminded about Sunday brunch at 11:00 AM.",
                "transcript": "Mom, I got selected to lead the architecture division expansion! Let's celebrate at Sunday brunch at 11:00 AM.",
                "sentiment": "Positive / Joyful"
            },
            {
                "ts": "2026-03-05T19:20:00",
                "summary": "Discussed travel arrangements for upcoming spring break visit.",
                "transcript": "We talked about booking train tickets for the kids over spring break.",
                "sentiment": "Warm"
            }
        ]
    },
    {
        "id": "person_002",
        "name": "Dr. Aris Thorne",
        "relationship": "Neurologist & Physician",
        "description": "Primary cognitive wellness physician. Recommended daily Synaptia logical puzzles and tracking working memory retention.",
        "avatar_color": "#06b6d4",
        "sample_photo": "/static/samples/dr_thorne.jpg",
        "created_at": "2026-02-15T09:30:00",
        "last_seen": "2026-03-06T14:10:00",
        "confidence": 0.94,
        "tags": ["Medical", "Wellness", "Advisor"],
        "interactions": [
            {
                "ts": "2026-03-06T14:10:00",
                "summary": "Reviewed 30-day cognitive puzzle metrics. Noted a 14% improvement in pattern decomposition speed.",
                "transcript": "The memory recall tests showed very steady progress. Keep up with the daily logic exercises.",
                "sentiment": "Encouraging"
            }
        ]
    },
    {
        "id": "person_003",
        "name": "Marcus Vance",
        "relationship": "Research Partner",
        "description": "Collaborating on multimodal perceptual systems, real-time speaker diarization, and edge AI memory indexing.",
        "avatar_color": "#10b981",
        "sample_photo": "/static/samples/marcus_vance.jpg",
        "created_at": "2026-02-20T11:15:00",
        "last_seen": "2026-03-09T18:00:00",
        "confidence": 0.91,
        "tags": ["Work", "AI Research", "Active"],
        "interactions": [
            {
                "ts": "2026-03-09T18:00:00",
                "summary": "Brainstormed low-latency WebRTC pipelines and Ray-Ban smart glass HUD overlays for instant memory recall.",
                "transcript": "We went through the end-to-end latency benchmarks for face matching on edge devices.",
                "sentiment": "Focused / Collaborative"
            }
        ]
    }
]


def format_relative_time(iso_str: Optional[str]) -> str:
    """Format an ISO timestamp into a warm, human-readable relative time string."""
    if not iso_str:
        return "Not available"
    try:
        clean_iso = iso_str.replace("Z", "+00:00")
        dt = datetime.fromisoformat(clean_iso)
        dt_naive = dt.replace(tzinfo=None) if dt.tzinfo else dt
        now = datetime.now()
        diff = now - dt_naive
        seconds = int(diff.total_seconds())

        if seconds < 0:
            return dt_naive.strftime("%b %d, %Y at %I:%M %p")
        if seconds < 60:
            return "Just now"
        minutes = seconds // 60
        if minutes < 60:
            return f"{minutes} minute{'s' if minutes != 1 else ''} ago"
        hours = minutes // 60
        if hours < 24:
            return f"{hours} hour{'s' if hours != 1 else ''} ago"
        days = hours // 24
        if days == 1:
            return f"Yesterday at {dt_naive.strftime('%I:%M %p')}"
        if days < 7:
            return f"{days} days ago ({dt_naive.strftime('%a, %I:%M %p')})"
        return dt_naive.strftime("%b %d, %Y at %I:%M %p")
    except Exception:
        return iso_str


class VisionMemoryEngine:
    """Manages multimodal perceptual memory, contact identities, and conversation summarization."""

    def __init__(self, groq_api_key: Optional[str] = None, seed_defaults: bool = False):
        self.groq_api_key = groq_api_key or os.getenv("GROQ_API_KEY", "")

        # Storage path for persistent profiles
        primary_dir = os.path.join(os.path.dirname(os.path.abspath(__file__)), "static", "data")
        try:
            os.makedirs(primary_dir, exist_ok=True)
            self.storage_path = os.path.join(primary_dir, "vision_profiles.json")
        except Exception:
            self.storage_path = "/tmp/vision_profiles.json"

        # In-memory dictionary for profiles
        self.people: Dict[str, Dict[str, Any]] = {}
        self.events_log: List[Dict[str, Any]] = []

        # Load default profiles only if explicitly requested (e.g. test suites)
        if seed_defaults:
            for p in DEFAULT_PROFILES:
                self.people[p["id"]] = dict(p)

        self._load_from_disk()
        self._sync_with_inference_backend()

    def _save_to_disk(self):
        """Persist people profiles to disk."""
        try:
            with open(self.storage_path, "w", encoding="utf-8") as f:
                json.dump(self.people, f, indent=2)
        except Exception as e:
            logger.warning(f"Failed to persist vision profiles to disk: {e}")

    def _load_from_disk(self):
        """Load stored profiles from disk."""
        if os.path.exists(self.storage_path):
            try:
                with open(self.storage_path, "r", encoding="utf-8") as f:
                    data = json.load(f)
                    if isinstance(data, dict):
                        self.people.update(data)
            except Exception as e:
                logger.warning(f"Failed to load vision profiles from disk: {e}")

    def _sync_with_inference_backend(self):
        """Sync with SynaptiaV2 inference face_identities.json and conversations.json if present."""
        try:
            inference_data_dir = os.path.join(
                os.path.dirname(os.path.abspath(__file__)),
                "SynaptiaV2-main", "inference", "data"
            )
            faces_file = os.path.join(inference_data_dir, "face_identities.json")
            convs_file = os.path.join(inference_data_dir, "conversations.json")

            conv_map: Dict[str, List[Dict[str, Any]]] = {}
            if os.path.exists(convs_file):
                with open(convs_file, "r", encoding="utf-8") as f:
                    conv_map = json.load(f)

            if os.path.exists(faces_file):
                with open(faces_file, "r", encoding="utf-8") as f:
                    face_identities = json.load(f)
                    if isinstance(face_identities, dict):
                        for raw_name, record in face_identities.items():
                            name = record.get("name") or raw_name
                            desc = record.get("descriptor")
                            existing = self.find_person_by_name(name)
                            if existing:
                                if desc and not existing.get("descriptor"):
                                    existing["descriptor"] = desc
                                if record.get("relationship") and not existing.get("relationship"):
                                    existing["relationship"] = record["relationship"]
                            else:
                                p_id = f"person_inf_{len(self.people) + 1:03d}"
                                color_idx = len(self.people) % len(AVATAR_COLORS)
                                interactions = []
                                norm_name = name.strip().lower()
                                if norm_name in conv_map:
                                    for c in conv_map[norm_name]:
                                        interactions.append({
                                            "ts": c.get("timestamp", datetime.now().isoformat()),
                                            "summary": c.get("summary") or c.get("text", ""),
                                            "transcript": c.get("text", ""),
                                            "sentiment": "Engaged"
                                        })
                                self.people[p_id] = {
                                    "id": p_id,
                                    "name": name,
                                    "relationship": record.get("relationship", "Acquaintance"),
                                    "description": record.get("description", f"Identity registered in system."),
                                    "avatar_color": AVATAR_COLORS[color_idx],
                                    "descriptor": desc,
                                    "created_at": datetime.now().isoformat(),
                                    "last_seen": datetime.now().isoformat(),
                                    "confidence": 0.95,
                                    "tags": ["Enrolled", "AR Face"],
                                    "interactions": interactions
                                }
        except Exception as e:
            logger.debug(f"Inference backend store sync skipped: {e}")

    def list_people(self) -> List[Dict[str, Any]]:
        """Return list of all registered person profiles."""
        return list(self.people.values())

    def get_person(self, person_id: str) -> Optional[Dict[str, Any]]:
        """Retrieve a specific profile by ID."""
        return self.people.get(person_id)

    def find_person_by_name(self, name: str) -> Optional[Dict[str, Any]]:
        """Find person by case-insensitive name match."""
        name_clean = name.strip().lower()
        for p in self.people.values():
            if p.get("name", "").strip().lower() == name_clean:
                return p
        return None

    def enroll_person(
        self,
        name: str,
        relationship: str = "Acquaintance",
        description: str = "",
        face_crop: Optional[str] = None,
        tags: Optional[List[str]] = None,
        descriptor: Optional[List[float]] = None,
    ) -> Dict[str, Any]:
        """Enroll a new identity or update an existing one."""
        name = name.strip()
        if not name:
            raise ValueError("Person name cannot be empty")

        existing = self.find_person_by_name(name)
        if existing:
            person_id = existing["id"]
            if relationship:
                existing["relationship"] = relationship
            if description:
                existing["description"] = description
            if face_crop:
                existing["face_thumbnail"] = face_crop
            if tags:
                existing["tags"] = tags
            if descriptor:
                existing["descriptor"] = descriptor
            existing["last_seen"] = datetime.now().isoformat()
            self._log_event("person_updated", {"person_id": person_id, "name": name})
            self._save_to_disk()
            return existing

        person_id = f"person_{int(time.time() * 1000) % 1000000:06d}"
        color_idx = len(self.people) % len(AVATAR_COLORS)
        new_profile = {
            "id": person_id,
            "name": name,
            "relationship": relationship or "Contact",
            "description": description or f"Enrolled on {datetime.now().strftime('%b %d, %Y')}.",
            "avatar_color": AVATAR_COLORS[color_idx],
            "face_thumbnail": face_crop,
            "descriptor": descriptor,
            "created_at": datetime.now().isoformat(),
            "last_seen": datetime.now().isoformat(),
            "confidence": 0.95,
            "tags": tags or ["Enrolled"],
            "interactions": []
        }
        self.people[person_id] = new_profile
        self._log_event("person_enrolled", {"person_id": person_id, "name": name})
        self._save_to_disk()
        return new_profile

    def delete_person(self, person_id: str) -> bool:
        """Remove a person from the store."""
        if person_id in self.people:
            deleted = self.people.pop(person_id)
            self._log_event("person_deleted", {"person_id": person_id, "name": deleted.get("name")})
            self._save_to_disk()
            return True
        return False

    def get_last_conversation(self, person_id_or_name: str) -> Dict[str, Any]:
        """
        Retrieve comprehensive last conversation details for a recognized individual.
        Returns timestamp, relative time, summary, transcript, sentiment, recall cues, and history.
        """
        person = self.get_person(person_id_or_name) or self.find_person_by_name(person_id_or_name)
        if not person:
            return {
                "has_conversation": False,
                "timestamp": None,
                "relative_time": "No past records",
                "summary": "This person is not currently in memory.",
                "transcript": "",
                "sentiment": "Unknown",
                "recall_cues": [],
                "key_points": [],
                "total_interactions": 0,
                "history": []
            }

        interactions = person.get("interactions", [])
        if not interactions:
            return {
                "has_conversation": False,
                "person_name": person.get("name"),
                "relationship": person.get("relationship", "Contact"),
                "timestamp": person.get("created_at"),
                "relative_time": format_relative_time(person.get("created_at")),
                "summary": f"You are connected with {person.get('name')} ({person.get('relationship', 'Contact')}), but no spoken conversations have been recorded yet.",
                "transcript": "",
                "sentiment": "Neutral",
                "recall_cues": [
                    f"Ask {person.get('name')} how their day is going.",
                    f"Introduce yourself warmly and discuss current plans."
                ],
                "key_points": ["Profile registered in memory"],
                "total_interactions": 0,
                "history": []
            }

        last_int = interactions[0]
        ts = last_int.get("ts")
        summary = last_int.get("summary", "Conversation recorded.")
        transcript = last_int.get("transcript", "")
        sentiment = last_int.get("sentiment", "Positive")

        p_name = person.get("name", "them")
        recall_cues = [
            f"Follow up with {p_name} on: \"{summary[:65]}...\"" if len(summary) > 65 else f"Follow up on: \"{summary}\"",
            f"Ask about their latest updates since you last spoke {format_relative_time(ts)}."
        ]

        history_items = []
        for item in interactions[:6]:
            history_items.append({
                "ts": item.get("ts"),
                "relative_time": format_relative_time(item.get("ts")),
                "summary": item.get("summary", ""),
                "transcript": item.get("transcript", ""),
                "sentiment": item.get("sentiment", "Engaged")
            })

        return {
            "has_conversation": True,
            "person_name": person.get("name"),
            "relationship": person.get("relationship", "Contact"),
            "timestamp": ts,
            "relative_time": format_relative_time(ts),
            "summary": summary,
            "transcript": transcript,
            "sentiment": sentiment,
            "recall_cues": recall_cues,
            "key_points": [
                f"Spoke {format_relative_time(ts)}",
                f"Tone: {sentiment}",
                f"Relationship: {person.get('relationship', 'Contact')}"
            ],
            "total_interactions": len(interactions),
            "history": history_items
        }

    def match_face_descriptor(
        self,
        candidate_descriptor: List[float],
        threshold: float = 0.55
    ) -> Tuple[Optional[Dict[str, Any]], float, float]:
        """
        Compare a 128D face descriptor against all enrolled profiles using Euclidean distance.
        Returns: (matched_person_or_None, min_distance, confidence_score)
        """
        if not candidate_descriptor or len(candidate_descriptor) != 128:
            return None, 999.0, 0.0

        best_person = None
        min_dist = 999.0

        for p in self.people.values():
            desc = p.get("descriptor")
            if not desc or len(desc) != 128:
                continue

            # Compute Euclidean distance
            dist = math.sqrt(sum((a - b) ** 2 for a, b in zip(candidate_descriptor, desc)))
            if dist < min_dist:
                min_dist = dist
                best_person = p

        if best_person and min_dist <= threshold:
            conf = round(max(50.0, min(99.5, (1.0 - (min_dist / 0.8)) * 100)), 1)
            return best_person, min_dist, conf

        return None, min_dist, 0.0

    def recognize_photo_faces(
        self,
        detected_faces: List[Dict[str, Any]],
        threshold: float = 0.55
    ) -> Dict[str, Any]:
        """
        Analyze all detected faces from an uploaded static photo.
        Returns whether each person has been met in the past, their identity details,
        and their last conversation history.
        """
        results = []

        for idx, face in enumerate(detected_faces):
            descriptor = face.get("descriptor")
            box = face.get("box", {})
            face_crop = face.get("crop")
            hint_name = face.get("hint_name")

            matched_person = None
            dist = 999.0
            conf = 0.0

            # 1. Try vector descriptor matching
            if descriptor and len(descriptor) == 128:
                matched_person, dist, conf = self.match_face_descriptor(descriptor, threshold=threshold)

            # 2. Fallback to name hint match if explicitly provided (e.g. sample photos)
            if not matched_person and hint_name:
                matched_person = self.find_person_by_name(hint_name)
                if matched_person:
                    dist = 0.22
                    conf = 94.5
                    if descriptor and len(descriptor) == 128 and not matched_person.get("descriptor"):
                        matched_person["descriptor"] = descriptor
                        self._save_to_disk()

            if matched_person:
                last_conv = self.get_last_conversation(matched_person["id"])
                results.append({
                    "face_index": idx,
                    "box": box,
                    "face_crop": face_crop or matched_person.get("face_thumbnail") or matched_person.get("sample_photo"),
                    "met_in_past": True,
                    "status": "met",
                    "status_label": "Met in Past",
                    "match_distance": round(dist, 4) if dist < 900 else 0.25,
                    "confidence": conf or 95.0,
                    "person": {
                        "id": matched_person["id"],
                        "name": matched_person["name"],
                        "relationship": matched_person.get("relationship", "Contact"),
                        "avatar_color": matched_person.get("avatar_color", "#6366f1"),
                        "description": matched_person.get("description", ""),
                        "last_seen": matched_person.get("last_seen"),
                        "last_seen_relative": format_relative_time(matched_person.get("last_seen")),
                        "tags": matched_person.get("tags", ["Recognized"])
                    },
                    "last_conversation": last_conv
                })
            else:
                results.append({
                    "face_index": idx,
                    "box": box,
                    "face_crop": face_crop,
                    "met_in_past": False,
                    "status": "new",
                    "status_label": "Not Met in Past",
                    "match_distance": round(dist, 4) if dist < 900 else None,
                    "confidence": 0.0,
                    "person": None,
                    "status_message": "You have not met this person before — no prior interaction records found in memory.",
                    "suggested_action": "You can enroll this individual into memory so they are recognized in future photos and live AR.",
                    "descriptor": descriptor,
                    "last_conversation": None
                })

        met_count = sum(1 for r in results if r["met_in_past"])
        unmet_count = len(results) - met_count

        return {
            "total_faces": len(results),
            "met_count": met_count,
            "unmet_count": unmet_count,
            "results": results,
            "timestamp": datetime.now().isoformat()
        }

    def record_interaction(
        self,
        person_id: str,
        transcript: str,
        summary: Optional[str] = None,
        sentiment: Optional[str] = None
    ) -> Dict[str, Any]:
        """Log a conversation interaction for an identified person."""
        person = self.people.get(person_id)
        if not person:
            raise ValueError(f"Person ID '{person_id}' not found")

        if not summary:
            summary = self.generate_memory_summary(person.get("name", "Unknown"), transcript)["summary"]

        interaction = {
            "ts": datetime.now().isoformat(),
            "transcript": transcript,
            "summary": summary,
            "sentiment": sentiment or "Engaged"
        }

        if "interactions" not in person:
            person["interactions"] = []
        person["interactions"].insert(0, interaction)
        person["last_seen"] = datetime.now().isoformat()
        person["description"] = summary  # Update latest context

        self._log_event("interaction_recorded", {"person_id": person_id, "summary": summary})
        self._save_to_disk()
        return interaction

    def generate_memory_summary(self, person_name: str, transcript: str) -> Dict[str, Any]:
        """
        Use Groq LLM (or robust heuristic fallback) to distill spoken transcripts
        into actionable cognitive memory summaries and talking point recall cues.
        """
        transcript = transcript.strip()
        if not transcript:
            return {
                "summary": "Brief observation with no extended conversation recorded.",
                "key_points": ["Visual presence confirmed"],
                "sentiment": "Neutral",
                "recall_cues": [f"Ask {person_name} how their day is going."]
            }

        # Try Groq AI generation first
        if self.groq_api_key:
            try:
                system_prompt = (
                    "You are Synaptia V2's Multimodal Perceptual Memory Engine. "
                    "Analyze spoken conversation transcripts between the user and a recognized person. "
                    "Provide a clear, high-signal 1-2 sentence memory summary, 2-3 key bullet points, "
                    "perceived emotional sentiment, and 2 proactive conversational recall cues for future interactions.\n"
                    "Respond STRICTLY in JSON format with keys:\n"
                    '{"summary": "...", "key_points": ["...", "..."], "sentiment": "...", "recall_cues": ["...", "..."]}'
                )
                user_content = f"Person Name: {person_name}\nSpoken Transcript:\n\"{transcript}\""

                resp = requests.post(
                    "https://api.groq.com/openai/v1/chat/completions",
                    headers={"Authorization": f"Bearer {self.groq_api_key}"},
                    json={
                        "model": os.getenv("GROQ_MODEL", "llama-3.3-70b-versatile"),
                        "messages": [
                            {"role": "system", "content": system_prompt},
                            {"role": "user", "content": user_content}
                        ],
                        "temperature": 0.3,
                        "response_format": {"type": "json_object"}
                    },
                    timeout=20
                )
                if resp.status_code == 200:
                    data = resp.json()["choices"][0]["message"]["content"]
                    parsed = json.loads(data)
                    return {
                        "summary": parsed.get("summary", transcript[:120] + "..."),
                        "key_points": parsed.get("key_points", ["Conversation registered"]),
                        "sentiment": parsed.get("sentiment", "Positive"),
                        "recall_cues": parsed.get("recall_cues", [f"Follow up with {person_name}."])
                    }
            except Exception as e:
                logger.warning(f"Groq memory summarization error, falling back to heuristic: {e}")

        # Heuristic Rule-Based Fallback
        words = transcript.split()
        summary_text = (
            f"Discussed {len(words)} words covering key topics with {person_name}. "
            f"Last point noted: '{words[-10:] if len(words) > 10 else transcript}'"
        )
        if len(transcript) > 140:
            summary_text = transcript[:140] + "..."

        return {
            "summary": summary_text,
            "key_points": [
                f"Engaged in active dialogue ({len(words)} words)",
                f"Recorded at {datetime.now().strftime('%H:%M:%S')}"
            ],
            "sentiment": "Neutral / Positive",
            "recall_cues": [
                f"Mention the recent discussion regarding '{words[0] if words else 'topics'}'",
                f"Check in on next scheduled milestone with {person_name}"
            ]
        }

    def simulate_event(self, person_id: Optional[str] = None) -> Dict[str, Any]:
        """Generate a simulated detection event for interactive testing & demo."""
        if not self.people:
            return {"type": "idle", "message": "No profiles enrolled"}

        if person_id and person_id in self.people:
            target = self.people[person_id]
        else:
            # Pick first available or rotate
            target = list(self.people.values())[0]

        event = {
            "type": "person_detected",
            "person_id": target["id"],
            "name": target["name"],
            "relationship": target["relationship"],
            "description": target["description"],
            "confidence": target.get("confidence", 0.95),
            "timestamp": datetime.now().isoformat(),
            "avatar_color": target.get("avatar_color", "#6366f1")
        }
        self._log_event("simulation_event", event)
        return event

    def _log_event(self, event_type: str, data: Dict[str, Any]):
        """Append internal event log."""
        self.events_log.insert(0, {
            "type": event_type,
            "data": data,
            "ts": datetime.now().isoformat()
        })
        if len(self.events_log) > 100:
            self.events_log = self.events_log[:100]

    def get_status(self) -> Dict[str, Any]:
        """Return system status for V2 module."""
        return {
            "status": "operational",
            "version": "2.0.0",
            "module": "Synaptia Multimodal Perception & Memory",
            "enrolled_count": len(self.people),
            "ai_summarizer": "groq-llama-3.3-70b" if self.groq_api_key else "heuristic-engine",
            "timestamp": datetime.now().isoformat()
        }
