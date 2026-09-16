"""MongoDB database operations for person data with resilient local fallback."""

import logging
import os
from datetime import datetime
from typing import Any, Optional

from dotenv import load_dotenv
from pymongo import MongoClient
from pymongo.collection import Collection
from pymongo.database import Database

import json
import time
import uuid
from pathlib import Path

# Load environment variables
load_dotenv()

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("database")

# Persistent storage fallback path
STORAGE_DIR = Path(__file__).parent / "data"
STORAGE_DIR.mkdir(parents=True, exist_ok=True)
IDENTITIES_FILE = STORAGE_DIR / "face_identities.json"
MEMORIES_FILE = STORAGE_DIR / "person_memories.json"
PEOPLE_FILE = STORAGE_DIR / "people.json"
CONVERSATIONS_FILE = STORAGE_DIR / "conversations.json"

# In-memory storage fallbacks with disk persistence
_mem_identities: dict[str, dict[str, Any]] = {}
_mem_observations: list[dict[str, Any]] = []
_mem_transcripts: list[dict[str, Any]] = []
_mem_person_memories: dict[str, dict[str, Any]] = {}
_mem_people: dict[str, dict[str, Any]] = {}
# Distinct conversations mapped by normalized person_name -> list of conversation entries
_mem_conversations: dict[str, list[dict[str, Any]]] = {}

def _load_persisted_data():
    global _mem_identities, _mem_person_memories, _mem_people, _mem_conversations
    try:
        if IDENTITIES_FILE.exists():
            with open(IDENTITIES_FILE, "r", encoding="utf-8") as f:
                _mem_identities = json.load(f)
                logger.info("Loaded %d enrolled face identities from persistent storage", len(_mem_identities))
    except Exception as exc:
        logger.warning("Could not load face_identities.json: %s", exc)

    try:
        if MEMORIES_FILE.exists():
            with open(MEMORIES_FILE, "r", encoding="utf-8") as f:
                _mem_person_memories = json.load(f)
    except Exception as exc:
        logger.warning("Could not load person_memories.json: %s", exc)

    try:
        if PEOPLE_FILE.exists():
            with open(PEOPLE_FILE, "r", encoding="utf-8") as f:
                _mem_people = json.load(f)
    except Exception as exc:
        logger.warning("Could not load people.json: %s", exc)

    try:
        if CONVERSATIONS_FILE.exists():
            with open(CONVERSATIONS_FILE, "r", encoding="utf-8") as f:
                _mem_conversations = json.load(f)
                logger.info("Loaded distinct conversations for %d individuals", len(_mem_conversations))
    except Exception as exc:
        logger.warning("Could not load conversations.json: %s", exc)

_load_persisted_data()

def _save_identities():
    try:
        with open(IDENTITIES_FILE, "w", encoding="utf-8") as f:
            json.dump(_mem_identities, f, default=str, indent=2)
    except Exception as exc:
        logger.warning("Could not persist face identities: %s", exc)

def _save_memories():
    try:
        with open(MEMORIES_FILE, "w", encoding="utf-8") as f:
            json.dump(_mem_person_memories, f, default=str, indent=2)
    except Exception as exc:
        logger.warning("Could not persist person memories: %s", exc)

def _save_people():
    try:
        with open(PEOPLE_FILE, "w", encoding="utf-8") as f:
            json.dump(_mem_people, f, default=str, indent=2)
    except Exception as exc:
        logger.warning("Could not persist people: %s", exc)

def _save_conversations():
    try:
        with open(CONVERSATIONS_FILE, "w", encoding="utf-8") as f:
            json.dump(_mem_conversations, f, default=str, indent=2)
    except Exception as exc:
        logger.warning("Could not persist conversations: %s", exc)

# MongoDB configuration
MONGODB_URI = os.getenv("MONGODB_URI")
MONGODB_DATABASE = os.getenv("MONGODB_DATABASE", "dementia_care_db")

# Global MongoDB client and database
_client: Optional[MongoClient] = None
_db: Optional[Database] = None
_db_disabled: bool = False


def get_database() -> Optional[Database]:
    """Get MongoDB database instance with resilient fallback handling."""
    global _client, _db, _db_disabled

    if _db_disabled:
        return None

    if _db is None:
        if not MONGODB_URI:
            logger.warning("MONGODB_URI not set; using local in-memory database fallback.")
            _db_disabled = True
            return None

        logger.info("Connecting to MongoDB Atlas...")
        import certifi
        try:
            client = MongoClient(MONGODB_URI, tlsCAFile=certifi.where(), serverSelectionTimeoutMS=2000)
            client.admin.command("ping")
            _client = client
            _db = _client[MONGODB_DATABASE]
            logger.info("Connected to MongoDB database: %s", MONGODB_DATABASE)
        except Exception as exc:  # noqa: BLE001
            logger.warning("MongoDB Atlas SSL/connection failed (%s). Using local in-memory database fallback.", exc)
            _db_disabled = True
            return None

    return _db


def list_face_identities() -> list[dict[str, Any]]:
    """Return the enrolled descriptor records used by the local browser matcher."""
    identities: list[dict[str, Any]] = []
    try:
        db = get_database()
        if db is not None:
            projection = {"_id": 0, "name": 1, "descriptor": 1, "relationship": 1, "description": 1, "updated_at": 1}
            identities = list(db["face_identities"].find({}, projection))
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB list_face_identities failed (%s); using in-memory fallback.", exc)

    if not identities:
        identities = list(_mem_identities.values())

    # Enrich with relationship/description from people collection if missing
    for identity in identities:
        id_name = identity.get("name", "").lower()
        if not identity.get("relationship") or not identity.get("description"):
            for person in _mem_people.values():
                if person.get("name", "").lower() == id_name:
                    if not identity.get("relationship"):
                        identity["relationship"] = person.get("relationship", "")
                    if not identity.get("description"):
                        identity["description"] = person.get("cached_description", "")
                    break

    return identities


def upsert_face_identity(
    name: str,
    descriptor: list[float],
    relationship: str | None = None,
    description: str | None = None,
) -> dict[str, Any]:
    """Store a user-enrolled face descriptor with relationship and context metadata without storing camera images."""
    now = datetime.utcnow()
    existing = _mem_identities.get(name, {})
    record = {
        **existing,
        "name": name,
        "descriptor": descriptor,
        "updated_at": now,
    }

    # Set relationship if supplied or inherit from existing/people records
    if relationship is not None and relationship.strip():
        record["relationship"] = relationship.strip()
    elif not record.get("relationship"):
        for person in _mem_people.values():
            if person.get("name", "").lower() == name.lower():
                record["relationship"] = person.get("relationship", "")
                break

    # Set description if supplied or inherit from existing/people records
    if description is not None and description.strip():
        record["description"] = description.strip()
    elif not record.get("description"):
        for person in _mem_people.values():
            if person.get("name", "").lower() == name.lower():
                record["description"] = person.get("cached_description", "")
                break

    _mem_identities[name] = record
    _save_identities()

    try:
        db = get_database()
        if db is not None:
            db["face_identities"].update_one(
                {"name": name},
                {"$set": record, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            logger.info("Enrolled local face identity %s (relationship=%s) in MongoDB Atlas", name, record.get("relationship"))
            return record
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB upsert_face_identity failed (%s); stored in-memory + persistent disk.", exc)

    logger.info("Enrolled local face identity %s (relationship=%s, saved to disk)", name, record.get("relationship"))
    return record


def upsert_voice_identity(name: str, voice_descriptor: list[float]) -> dict[str, Any]:
    """Store a user-enrolled acoustic voice descriptor."""
    now = datetime.utcnow()
    # Find case-insensitive existing record
    clean_name = name.strip()
    target_key = clean_name
    for k in _mem_identities:
        if k.lower() == clean_name.lower():
            target_key = k
            break

    existing = _mem_identities.get(target_key, {})
    record = {**existing, "name": target_key, "voice_descriptor": voice_descriptor, "voice_updated_at": now}
    _mem_identities[target_key] = record
    _save_identities()

    try:
        db = get_database()
        if db is not None:
            db["face_identities"].update_one(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"$set": record, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            logger.info("Enrolled voice identity for %s in MongoDB Atlas", target_key)
            return record
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB upsert_voice_identity failed (%s); stored in-memory + persistent disk.", exc)

    logger.info("Enrolled voice identity for %s (saved to disk)", target_key)
    return record


def get_voice_identity(name: str) -> Optional[list[float]]:
    """Retrieve enrolled voice descriptor for a person if available."""
    clean_name = name.strip()
    try:
        db = get_database()
        if db is not None:
            doc = db["face_identities"].find_one(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"_id": 0, "voice_descriptor": 1}
            )
            if doc and "voice_descriptor" in doc:
                return doc["voice_descriptor"]
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB get_voice_identity failed (%s); checking in-memory.", exc)

    for k, v in _mem_identities.items():
        if k.lower() == clean_name.lower() and v.get("voice_descriptor"):
            return v["voice_descriptor"]
    return None


def get_all_voice_identities() -> dict[str, list[float]]:
    """Return all enrolled voiceprints as a dict of {name: descriptor}."""
    profiles: dict[str, list[float]] = {}
    for name, rec in _mem_identities.items():
        if rec.get("voice_descriptor"):
            profiles[name] = rec["voice_descriptor"]
    return profiles


def delete_voice_identity(name: str) -> bool:
    """Clear voiceprint for a specific person to allow re-calibration."""
    clean_name = name.strip()
    for k in list(_mem_identities.keys()):
        if k.lower() == clean_name.lower():
            _mem_identities[k].pop("voice_descriptor", None)
            _mem_identities[k].pop("voice_updated_at", None)
    _save_identities()

    try:
        db = get_database()
        if db is not None:
            db["face_identities"].update_many(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"$unset": {"voice_descriptor": "", "voice_updated_at": ""}}
            )
    except Exception:
        pass
    return True


# ── Distinct Conversation Store ─────────────────────────────────────────────

def record_distinct_conversation(
    person_name: str,
    text: str,
    summary: str | None = None,
    voice_verified: bool = True,
) -> dict[str, Any]:
    """Store a speech utterance strictly in the specified individual's conversation history."""
    now = datetime.utcnow()
    norm_name = person_name.strip().lower()
    entry = {
        "id": f"conv_{int(time.time() * 1000)}_{uuid.uuid4().hex[:6]}",
        "person_name": person_name.strip(),
        "speaker": person_name.strip(),
        "text": text.strip(),
        "summary": summary,
        "voice_verified": voice_verified,
        "timestamp": now.isoformat(),
    }

    if norm_name not in _mem_conversations:
        _mem_conversations[norm_name] = []
    _mem_conversations[norm_name].append(entry)
    _save_conversations()

    # Also record in general observations
    record = {
        "person_name": person_name.strip(),
        "text": text.strip(),
        "created_at": now,
    }
    _mem_transcripts.append(record)

    try:
        db = get_database()
        if db is not None:
            db["conversation_observations"].insert_one({**entry, "created_at": now})
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB record_distinct_conversation failed (%s).", exc)

    return entry


def get_distinct_conversations(person_name: str, limit: int = 30) -> list[dict[str, Any]]:
    """Retrieve distinct conversation logs exclusively for the named individual."""
    norm_name = person_name.strip().lower()
    try:
        db = get_database()
        if db is not None:
            cursor = db["conversation_observations"].find(
                {"person_name": {"$regex": f"^{re.escape(norm_name)}$", "$options": "i"}},
                {"_id": 0}
            ).sort("created_at", -1).limit(limit)
            items = list(reversed(list(cursor)))
            if items:
                return items
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB get_distinct_conversations failed (%s); checking in-memory.", exc)

    entries = _mem_conversations.get(norm_name, [])
    return entries[-limit:]


def list_all_conversations() -> dict[str, list[dict[str, Any]]]:
    """Retrieve conversations grouped by individual."""
    return {k: v[-20:] for k, v in _mem_conversations.items()}


def clear_person_conversations(person_name: str) -> bool:
    """Clear conversation history for a specific individual."""
    norm_name = person_name.strip().lower()
    if norm_name in _mem_conversations:
        _mem_conversations[norm_name].clear()
        _save_conversations()
    try:
        db = get_database()
        if db is not None:
            db["conversation_observations"].delete_many(
                {"person_name": {"$regex": f"^{re.escape(norm_name)}$", "$options": "i"}}
            )
    except Exception:
        pass
    return True


def record_transcript(person_name: str | None, text: str) -> dict[str, Any]:
    """Persist a speech-recognition result into the distinct conversation store."""
    if person_name:
        return record_distinct_conversation(person_name, text)

    record = {
        "person_name": person_name,
        "text": text,
        "created_at": datetime.utcnow(),
    }
    _mem_transcripts.append(record)

    try:
        db = get_database()
        if db is not None:
            db["conversation_observations"].insert_one({**record})
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB record_transcript failed (%s); saved in-memory.", exc)

    return record


def get_person_memory(name: str) -> Optional[dict[str, Any]]:
    """Return the latest saved AI memory for an explicitly enrolled person (case-insensitive)."""
    clean_name = name.strip()
    try:
        db = get_database()
        if db is not None:
            doc = db["person_memories"].find_one(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"_id": 0}
            )
            if doc:
                return doc
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB get_person_memory failed (%s); checking in-memory.", exc)

    for k, v in _mem_person_memories.items():
        if k.lower() == clean_name.lower():
            return v
    return None


def upsert_person_memory(name: str, summary: str) -> dict[str, Any]:
    """Persist a grounded rolling summary for a named, enrolled person."""
    now = datetime.utcnow()
    clean_name = name.strip()
    record = {"name": clean_name, "summary": summary, "updated_at": now}
    _mem_person_memories[clean_name] = record
    _save_memories()

    try:
        db = get_database()
        if db is not None:
            db["person_memories"].update_one(
                {"name": {"$regex": f"^{re.escape(clean_name)}$", "$options": "i"}},
                {"$set": record, "$setOnInsert": {"created_at": now}},
                upsert=True,
            )
            return record
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB upsert_person_memory failed (%s); saved in-memory.", exc)

    return record


def get_recent_transcripts(person_name: str, limit: int = 12) -> list[str]:
    """Return stored speech segments in chronological order exclusively for the requested person."""
    norm_name = person_name.strip().lower()

    # Query distinct conversation store first
    if norm_name in _mem_conversations:
        transcripts = [c["text"] for c in _mem_conversations[norm_name] if c.get("text")]
        if transcripts:
            return transcripts[-limit:]

    try:
        db = get_database()
        if db is not None:
            cursor = (
                db["conversation_observations"]
                .find(
                    {"person_name": {"$regex": f"^{re.escape(norm_name)}$", "$options": "i"}},
                    {"_id": 0, "text": 1}
                )
                .sort("created_at", -1)
                .limit(limit)
            )
            res = [item["text"] for item in reversed(list(cursor)) if item.get("text")]
            if res:
                return res
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB get_recent_transcripts failed (%s); checking in-memory.", exc)

    matching = [
        t["text"] for t in _mem_transcripts
        if (t.get("person_name") or "").lower() == norm_name and t.get("text")
    ]
    return matching[-limit:]


def record_face_observation(
    session_id: str,
    face_id: str,
    confidence: float,
    bounding_box: dict[str, float],
    image_data_url: str | None = None,
) -> dict[str, Any]:
    """Persist face observation evidence."""
    now = datetime.utcnow()
    key = {"session_id": session_id, "face_id": face_id}
    record = {**key, "confidence": confidence, "bounding_box": bounding_box, "last_seen": now}
    _mem_observations.append(record)

    try:
        db = get_database()
        if db is not None:
            set_values: dict[str, Any] = {
                "last_seen": now,
                "last_confidence": confidence,
                "last_bounding_box": bounding_box,
            }
            set_on_insert: dict[str, Any] = {
                "session_id": session_id,
                "face_id": face_id,
                "first_seen": now,
            }
            if image_data_url:
                set_on_insert["image_data_url"] = image_data_url

            db["face_observations"].update_one(
                key,
                {
                    "$set": set_values,
                    "$setOnInsert": set_on_insert,
                    "$inc": {"detection_count": 1},
                },
                upsert=True,
            )
            logger.info("Recorded face observation %s/%s in MongoDB Atlas", session_id, face_id)
            return {**key, **set_values}
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB record_face_observation failed (%s); saved in-memory.", exc)

    return record


def get_person_by_id(person_id: str) -> Optional[dict]:
    """Retrieve a person document by person_id."""
    try:
        db = get_database()
        if db is not None:
            person_doc = db["people"].find_one({"person_id": person_id})
            if person_doc:
                return person_doc
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB get_person_by_id failed (%s); checking in-memory.", exc)

    return _mem_people.get(person_id)


def create_person(
    person_id: str,
    name: str,
    relationship: str,
    aggregated_context: str = "",
    cached_description: str = "No previous interactions",
) -> dict:
    """Create a new person document."""
    person_doc = {
        "person_id": person_id,
        "name": name,
        "relationship": relationship,
        "aggregated_context": aggregated_context,
        "cached_description": cached_description,
        "last_updated": datetime.utcnow(),
    }
    _mem_people[person_id] = person_doc

    try:
        db = get_database()
        if db is not None:
            db["people"].update_one(
                {"person_id": person_id},
                {"$setOnInsert": person_doc},
                upsert=True,
            )
            return person_doc
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB create_person failed (%s); saved in-memory.", exc)

    return person_doc


def update_person_context(
    person_id: str,
    aggregated_context: str,
    cached_description: str,
) -> bool:
    """Update a person's aggregated context and cached description."""
    if person_id in _mem_people:
        _mem_people[person_id]["aggregated_context"] = aggregated_context
        _mem_people[person_id]["cached_description"] = cached_description
        _mem_people[person_id]["last_updated"] = datetime.utcnow()

    try:
        db = get_database()
        if db is not None:
            res = db["people"].update_one(
                {"person_id": person_id},
                {
                    "$set": {
                        "aggregated_context": aggregated_context,
                        "cached_description": cached_description,
                        "last_updated": datetime.utcnow(),
                    }
                },
            )
            return res.matched_count > 0
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB update_person_context failed (%s).", exc)

    return person_id in _mem_people


def list_all_people() -> list[dict]:
    """List all people in the database."""
    try:
        db = get_database()
        if db is not None:
            return list(db["people"].find())
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB list_all_people failed (%s); using in-memory.", exc)

    return list(_mem_people.values())


def delete_all_people() -> int:
    """Delete all people from the database."""
    count = len(_mem_people)
    _mem_people.clear()
    try:
        db = get_database()
        if db is not None:
            res = db["people"].delete_many({})
            return res.deleted_count
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB delete_all_people failed (%s).", exc)

    return count


def clear_all_data() -> dict[str, Any]:
    """Completely wipe all enrolled face identities, voiceprints, memories, and transcripts."""
    _mem_identities.clear()
    _mem_observations.clear()
    _mem_transcripts.clear()
    _mem_person_memories.clear()
    _mem_people.clear()
    _mem_conversations.clear()

    _save_identities()
    _save_memories()
    _save_people()
    _save_conversations()

    try:
        db = get_database()
        if db is not None:
            db["face_identities"].delete_many({})
            db["person_memories"].delete_many({})
            db["people"].delete_many({})
            db["conversation_observations"].delete_many({})
            db["face_observations"].delete_many({})
    except Exception as exc:  # noqa: BLE001
        logger.warning("MongoDB clear_all_data failed (%s).", exc)

    logger.info("All face identities, voiceprints, distinct conversations, and person memories have been wiped clean.")
    return {"cleared": True}


def close_connection():
    """Close MongoDB connection."""
    global _client, _db
    if _client:
        _client.close()
        _client = None
        _db = None
        logger.info("MongoDB connection closed")

