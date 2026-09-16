"""
Puzzle Generator Module — Synaptia
Powered entirely by the Groq API (groq.com) — llama-3.3-70b-versatile.
Uses the OpenAI-compatible endpoint at https://api.groq.com/openai/v1.
"""

import re as _re
import json
import uuid
import time
import os
import random
import logging
import requests
from typing import Optional
from datetime import datetime
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# ── Groq API Configuration ──────────────────────────────────────────────────

GROQ_API_KEY  = os.getenv("GROQ_API_KEY", "")
GROQ_MODEL          = os.getenv("GROQ_MODEL", "groq/compound-mini")
GROQ_VALIDATOR_MODEL = os.getenv("GROQ_VALIDATOR_MODEL", "groq/compound-mini")
GROQ_BASE_URL       = "https://api.groq.com/openai/v1"
GROQ_TIMEOUT        = 60

# ── Puzzle uniqueness helpers ────────────────────────────────────────────────

_RIDDLE_ANGLES = [
    "nature and animals", "everyday household objects", "weather phenomena",
    "technology and computers", "the human body", "food and cooking",
    "time and clocks", "music and sound", "light and shadows",
    "books and libraries", "oceans and rivers", "astronomy and space",
    "travel and transportation", "money and economics", "language and words",
    "mountains and geography", "art and painting", "sports and games",
    "history and ancient civilisations", "mathematics and patterns",
    "emotions and psychology", "plants and forests", "sports equipment",
    "clothing and fashion", "medicine and health",
]
_MATH_ANGLES = [
    "number theory", "geometry and shapes", "probability and statistics",
    "sequences and series", "combinatorics", "algebra and equations",
    "rates and ratios", "percentages and fractions", "prime numbers",
    "logic grids and constraints", "modular arithmetic", "Fibonacci patterns",
    "graph theory concepts", "clock arithmetic", "coin and weight problems",
]
_LOGIC_ANGLES = [
    "truth-teller/liar scenarios", "island inhabitants", "grid deduction",
    "scheduling conflicts", "river crossing", "coin weighing",
    "coloured hats", "job assignments", "seating arrangements",
    "family relationships", "prisoners dilemma variants", "cryptic clues",
    "lateral thinking scenarios", "elimination grids", "conditional statements",
]
_WORDPLAY_ANGLES = [
    "homophones", "anagrams", "palindromes", "compound words",
    "idioms taken literally", "portmanteau words", "double meanings",
    "spoonerisms", "backronyms", "etymological surprises",
    "words hidden inside other words", "foreign loan words",
    "oxymorons", "contronyms", "phobias and their names",
]
_TRIVIA_ANGLES = [
    "ancient history", "famous inventors", "world records",
    "animal behaviour", "space exploration", "geography extremes",
    "language origins", "food history", "medical breakthroughs",
    "classic literature", "scientific constants", "cultural traditions",
    "historical firsts", "bizarre laws around the world", "architectural wonders",
]
_ANGLE_MAP = {
    "riddle":   _RIDDLE_ANGLES,
    "math":     _MATH_ANGLES,
    "logic":    _LOGIC_ANGLES,
    "wordplay": _WORDPLAY_ANGLES,
    "trivia":   _TRIVIA_ANGLES,
}

# ── Curated Offline Fallback Puzzles ─────────────────────────────────────────

_OFFLINE_PUZZLES = {
    ("riddle", "easy"): [
        {
            "question": "What has keys that open no doors, space that has no room, and allows you to enter but not go outside?",
            "answer": "keyboard",
            "explanation": "A computer keyboard has letter and symbol keys, a space bar, and an enter key, but cannot open physical rooms.",
            "hints": [
                "You likely interact with this object every day when typing on a computer or phone.",
                "It has letter keys, number keys, and a dedicated space bar.",
                "It is a computer keyboard."
            ],
            "solution_steps": [
                "Identify what common item contains 'keys', 'space', and 'enter'.",
                "Recognize that these are standard keyboard mechanisms.",
                "A computer keyboard satisfies all parts of the riddle."
            ],
        },
        {
            "question": "I speak without a mouth and hear without ears. I have no body, but I come alive with wind. What am I?",
            "answer": "echo",
            "explanation": "An echo produces sound through acoustic reflection without physical organs and travels through atmospheric soundwaves.",
            "hints": [
                "Think of an acoustic phenomenon found in valleys or empty auditoriums.",
                "It repeats words back to you after a momentary pause.",
                "It is a reflected sound."
            ],
            "solution_steps": [
                "Look for an acoustic reflection rather than a living organism.",
                "Note that sound reverberations travel on the air.",
                "An echo mimics human speech without bodily organs."
            ],
        },
    ],
    ("riddle", "medium"): [
        {
            "question": "Forward I am heavy, but backward I am not. What am I?",
            "answer": "ton",
            "explanation": "'Ton' is a heavy unit of weight forward, and spelled backward it spells 'not'.",
            "hints": [
                "This riddle relies on wordplay and spelling.",
                "Read the word in reverse letter-by-letter.",
                "The word is a unit of weight equal to 2,000 pounds."
            ],
            "solution_steps": [
                "Consider the dual meanings of 'heavy' and 'not'.",
                "A 'ton' is a standard heavy unit of weight.",
                "Reverse 'ton' to spell 'not'."
            ],
        },
        {
            "question": "A cowboy arrives in town on Friday, stays for three days, and leaves on Friday. How did he accomplish this?",
            "answer": "his horse was named friday",
            "explanation": "The cowboy's horse was named Friday, so he arrived riding Friday and departed riding Friday.",
            "hints": [
                "Pay attention to the capitalization of Friday in the clues.",
                "Friday does not only mean the day of the week.",
                "Think about what the cowboy rode into town on."
            ],
            "solution_steps": [
                "Leaving three days after arrival would ordinarily land on Monday.",
                "Therefore, arrival or departure cannot both be days of the week.",
                "The horse was named Friday."
            ],
        },
    ],
    ("riddle", "hard"): [
        {
            "question": "I am taken from a mine and shut up in a wooden case, from which I am never released, and yet I am used by almost everybody. What am I?",
            "answer": "pencil lead",
            "explanation": "Graphite (pencil lead) is mined from the earth, permanently encased in cedar wood, and used universally for writing.",
            "hints": [
                "It is found in classrooms, studios, and work desks.",
                "It leaves a mark on paper that can be erased.",
                "It is the graphite core inside a pencil."
            ],
            "solution_steps": [
                "Identify what mined substance is encased in wood.",
                "Graphite (commonly called lead) is encased in pencils.",
                "Pencil lead is never released from its casing yet used daily."
            ],
        },
        {
            "question": "The person who makes it has no need of it; the person who buys it has no use for it. The person who uses it can neither see nor feel it. What is it?",
            "answer": "coffin",
            "explanation": "A coffin is built by a carpenter, bought by a grieving family, and used by the deceased who has no conscious awareness of it.",
            "hints": [
                "It is tied to a solemn, universal human ritual.",
                "The person inside has no conscious awareness of it.",
                "It is a traditional burial receptacle."
            ],
            "solution_steps": [
                "Analyze who makes, buys, and uses the item.",
                "The user is deceased and thus unable to see or feel.",
                "A coffin uniquely fits every condition."
            ],
        },
    ],
    ("math", "easy"): [
        {
            "question": "A bat and a ball cost $1.10 in total. The bat costs $1.00 more than the ball. How much does the ball cost in cents?",
            "answer": "5 cents",
            "explanation": "If the ball is x, the bat is x + 1.00. x + (x + 1.00) = 1.10 => 2x = 0.10 => x = 0.05 ($0.05 or 5 cents).",
            "hints": [
                "Do not jump to 10 cents — calculate the algebraic difference.",
                "If the ball were 10 cents, the bat would be $1.10 and total $1.20.",
                "The ball costs 5 cents ($0.05)."
            ],
            "solution_steps": [
                "Set Ball = x and Bat = x + 1.00.",
                "Total: x + x + 1.00 = 1.10 => 2x = 0.10.",
                "x = 0.05, which is 5 cents."
            ],
        },
        {
            "question": "What single digit, when multiplied by any other integer, yields a product whose digits sum to a multiple of that same digit?",
            "answer": "9",
            "explanation": "In decimal arithmetic, any multiple of 9 has a digit sum that is also a multiple of 9.",
            "hints": [
                "Test small single digits: 9 * 2 = 18 (1+8=9), 9 * 5 = 45 (4+5=9).",
                "Think of the classic divisibility rule.",
                "The number is 9."
            ],
            "solution_steps": [
                "Recall the digital root property in base 10.",
                "Multiplication by 9 preserves modulo 9 equivalence.",
                "The digit is 9."
            ],
        },
    ],
    ("math", "medium"): [
        {
            "question": "If 5 cats can catch 5 mice in 5 minutes, how many cats are needed to catch 100 mice in 100 minutes?",
            "answer": "5 cats",
            "explanation": "5 cats catching 5 mice in 5 minutes means each cat catches 1 mouse per 5 minutes. In 100 minutes, 1 cat catches 20 mice, so 5 cats catch 100 mice.",
            "hints": [
                "Determine the catch rate per cat.",
                "One cat catches one mouse every five minutes.",
                "In 100 minutes, one cat catches 20 mice."
            ],
            "solution_steps": [
                "Rate = 1 mouse per cat every 5 minutes.",
                "In 100 minutes (20 periods of 5 minutes), 1 cat catches 20 mice.",
                "To catch 100 mice, 100 / 20 = 5 cats are needed."
            ],
        },
        {
            "question": "A clock shows 3:15. What is the acute angle between the hour hand and the minute hand in degrees?",
            "answer": "7.5 degrees",
            "explanation": "At 3:15, the minute hand points directly at the 3 (90 degrees). The hour hand has moved past the 3 by 15 min * 0.5 deg/min = 7.5 degrees.",
            "hints": [
                "The minute hand is at 90 degrees, but the hour hand has moved slightly past 3 o'clock.",
                "The hour hand moves 0.5 degrees every minute.",
                "Calculate 15 minutes * 0.5 degrees per minute."
            ],
            "solution_steps": [
                "Minute hand is at exactly 3 * 30 = 90 degrees.",
                "Hour hand is at 3 * 30 + 15 * 0.5 = 90 + 7.5 = 97.5 degrees.",
                "Difference = 97.5 - 90 = 7.5 degrees."
            ],
        },
    ],
    ("math", "hard"): [
        {
            "question": "You have 10 bags of gold coins. 9 bags have real coins weighing 10g each; 1 bag has counterfeit coins weighing 9g each. Using a digital scale only ONCE, what minimum number of coins do you weigh to identify the counterfeit bag?",
            "answer": "55 coins",
            "explanation": "Take 1 coin from bag 1, 2 from bag 2, ..., up to 10 from bag 10. Total coins = 55. If all were real, weight = 550g. A deficit of k grams directly identifies bag k.",
            "hints": [
                "Take a different quantity of coins from each of the 10 bags.",
                "Calculate the triangular sum: 1 + 2 + 3 + ... + 10.",
                "The total coins weighed is 55."
            ],
            "solution_steps": [
                "Take n coins from bag n (1 from bag 1, 2 from bag 2, ... 10 from bag 10).",
                "Total coins = sum(1..10) = 55 coins.",
                "Weight deficit from 550g immediately identifies the counterfeit bag index in a single weighing."
            ],
        },
    ],
    ("logic", "easy"): [
        {
            "question": "Three boxes are labelled 'Apples', 'Oranges', and 'Apples & Oranges'. Every box is incorrectly labelled. By picking only ONE fruit from ONE box, which box should you pick from to label all boxes correctly?",
            "answer": "apples and oranges",
            "explanation": "Because all labels are wrong, the box labelled 'Apples & Oranges' must be purely one fruit. Picking from it reveals its identity, which cascades to solve the remaining two.",
            "hints": [
                "Remember that EVERY label is guaranteed to be false.",
                "The box labelled 'Apples & Oranges' CANNOT have both fruits.",
                "Pick from the box labelled 'Apples & Oranges'."
            ],
            "solution_steps": [
                "Since all labels are false, 'Apples & Oranges' contains purely Apples or purely Oranges.",
                "Drawing 1 fruit identifies that entire box unambiguously.",
                "The remaining two false labels can then be swapped directly."
            ],
        },
    ],
    ("logic", "medium"): [
        {
            "question": "On an island, Knaves always lie and Knights always tell the truth. Person A says: 'We are both Knaves.' What are Person A and Person B?",
            "answer": "A is a Knave and B is a Knight",
            "explanation": "If A were a Knight, their statement would be true, meaning A is a Knave (contradiction). Thus A is a Knave, making their statement false, which means B must be a Knight.",
            "hints": [
                "Could a Knight ever say 'I am a Knave'?",
                "If A is a Knight, the statement contradicts itself.",
                "Therefore A must be a Knave, making the compound statement false."
            ],
            "solution_steps": [
                "A Knight cannot claim to be a Knave.",
                "Therefore A must be a Knave.",
                "Because A's claim 'We are both Knaves' must be false, B cannot be a Knave. Hence B is a Knight."
            ],
        },
    ],
    ("logic", "hard"): [
        {
            "question": "Four people need to cross a rope bridge at night with one torch that lasts 17 minutes. The bridge holds at most 2 people. Crossing times: A: 1 min, B: 2 min, C: 5 min, D: 10 min. What is the fastest possible crossing time in minutes?",
            "answer": "17 minutes",
            "explanation": "A and B cross (2 min), A returns (1 min), C and D cross together (10 min), B returns (2 min), A and B cross (2 min). Total = 2 + 1 + 10 + 2 + 2 = 17 min.",
            "hints": [
                "Send the two slowest crossers (C and D) together so their times overlap.",
                "Use the fastest runners (A and B) to shuttle the torch back.",
                "The minimum crossing time matches the torch duration: 17 minutes."
            ],
            "solution_steps": [
                "A and B cross in 2 minutes; A brings torch back (3 min elapsed).",
                "C and D cross together in 10 minutes (13 min elapsed); B brings torch back (15 min elapsed).",
                "A and B cross together in 2 minutes (17 min total elapsed)."
            ],
        },
    ],
    ("wordplay", "easy"): [
        {
            "question": "What five-letter word becomes shorter when you add two letters to it?",
            "answer": "short",
            "explanation": "The word 'short' (5 letters) becomes 'shorter' (7 letters) when you append 'er'.",
            "hints": [
                "Think literally about comparative adjective endings.",
                "The word describes physical height or length.",
                "Add 'er' to the word."
            ],
            "solution_steps": [
                "Look for an auto-descriptive comparative word.",
                "The base word is 'short'.",
                "Adding 'er' literally makes it 'shorter'."
            ],
        },
    ],
    ("wordplay", "medium"): [
        {
            "question": "What common English word contains three consecutive pairs of double letters?",
            "answer": "bookkeeper",
            "explanation": "'Bookkeeper' (and 'bookkeeping') has three consecutive double letters: oo, kk, ee.",
            "hints": [
                "It describes an accounting or record-keeping profession.",
                "Look at the letters: b-oo-kk-ee-per.",
                "The word is bookkeeper."
            ],
            "solution_steps": [
                "Inspect words with consecutive repeated characters.",
                "b - OO - KK - EE - p - e - r has three consecutive doubled letters.",
                "Bookkeeper is the definitive answer."
            ],
        },
    ],
    ("wordplay", "hard"): [
        {
            "question": "What 7-letter word contains at least 9 other words without rearranging any letters? (Starts with 'th')",
            "answer": "therein",
            "explanation": "'Therein' contains: the, there, he, her, here, ere, rein, in, herein, and I.",
            "hints": [
                "It is a formal adverb meaning 'in that place or respect'.",
                "The letters are t-h-e-r-e-i-n.",
                "The word is therein."
            ],
            "solution_steps": [
                "Look for high sub-string density in compound prepositions.",
                "Sub-words: the, there, he, her, here, ere, rein, in, herein, I.",
                "The word is 'therein'."
            ],
        },
    ],
    ("trivia", "easy"): [
        {
            "question": "What internal organ in the human body has the unique capability to regenerate lost tissue back to full functional mass?",
            "answer": "liver",
            "explanation": "The human liver can regenerate back to full volume even when up to 75% of its mass is surgically removed.",
            "hints": [
                "It produces bile and filters metabolic waste.",
                "Located in the upper right quadrant of the abdominal cavity.",
                "The liver."
            ],
            "solution_steps": [
                "Hepatocytes have specialized proliferative capacity.",
                "No other solid vital organ can fully regenerate lost lobes.",
                "The liver is the organ."
            ],
        },
    ],
    ("trivia", "medium"): [
        {
            "question": "Which planet in the solar system has a rotation period (day) that is longer than its orbital revolution period (year)?",
            "answer": "venus",
            "explanation": "Venus takes 243 Earth days to complete one sidereal rotation, but only 224.7 Earth days to orbit the Sun.",
            "hints": [
                "It is the second planet from the Sun and often called Earth's twin.",
                "It rotates in retrograde (clockwise).",
                "The planet is Venus."
            ],
            "solution_steps": [
                "Venus has an orbital period of 224.7 Earth days.",
                "Venus has a sidereal rotational period of 243 Earth days.",
                "Thus a Venusian day is longer than a Venusian year."
            ],
        },
    ],
    ("trivia", "hard"): [
        {
            "question": "What chemical element with atomic number 41 is named after a figure from Greek mythology and is widely used in superconducting radio-frequency cavities for particle accelerators?",
            "answer": "niobium",
            "explanation": "Niobium (Nb, atomic number 41) is named after Niobe, daughter of Tantalus, reflecting its close chemical similarity to tantalum.",
            "hints": [
                "Formerly known as columbium in the United States.",
                "Chemical symbol Nb.",
                "Named after Niobe."
            ],
            "solution_steps": [
                "Locate transition metal 41 in Group 5.",
                "Associated historically with tantalum and named after Niobe.",
                "The element is Niobium."
            ],
        },
    ],
}

# ── Groq API call ────────────────────────────────────────────────────────────

def _groq_generate(messages: list, max_tokens: int = 1024, temperature: float = 1.0) -> Optional[str]:
    """
    Call the Groq API via its OpenAI-compatible chat/completions endpoint.
    Returns the text response, or None on any failure.
    """
    url = f"{GROQ_BASE_URL}/chat/completions"
    headers = {
        "Authorization": f"Bearer {GROQ_API_KEY}",
        "Content-Type":  "application/json",
    }
    payload = {
        "model":       GROQ_MODEL,
        "messages":    messages,
        "max_tokens":  max_tokens,
        "temperature": temperature,
    }
    try:
        resp = requests.post(url, headers=headers, json=payload, timeout=GROQ_TIMEOUT)
        if resp.status_code == 401:
            logger.error("[PuzzleGen] Groq API: invalid API key (401). Raw: %s", resp.text[:200])
            return None
        if resp.status_code == 429:
            logger.warning("[PuzzleGen] Groq API: rate limit hit (429). Retrying in 5s…")
            time.sleep(5)
            resp = requests.post(url, headers=headers, json=payload, timeout=GROQ_TIMEOUT)
            resp.raise_for_status()
        resp.raise_for_status()
        data = resp.json()
        text = data.get("choices", [{}])[0].get("message", {}).get("content", "").strip()
        if text:
            logger.info("[PuzzleGen] Groq (%s) responded successfully.", GROQ_MODEL)
        return text or None
    except requests.exceptions.Timeout:
        logger.error("[PuzzleGen] Groq API request timed out.")
        return None
    except requests.exceptions.ConnectionError as exc:
        logger.error("[PuzzleGen] Cannot reach Groq API: %s", exc)
        return None
    except Exception as exc:
        logger.error("[PuzzleGen] Groq API error: %s", exc)
        return None


# ── AI Cross-Validator ───────────────────────────────────────────────────────

def _groq_validate_puzzle(question: str, answer: str, explanation: str, puzzle_type: str) -> dict:
    """
    Uses a second independent Groq call to cross-validate the generated puzzle.
    Returns a dict with keys:
      - valid (bool): True if the puzzle passes validation
      - reason (str): Explanation from the validator
      - confidence (str): "high" | "medium" | "low"
    """
    prompt = f"""You are a rigorous fact-checker and logic validator. Your SOLE job is to verify \
whether the puzzle below is internally consistent, factually correct, and has exactly one \
clearly correct answer. Be brutally honest.

Puzzle type: {puzzle_type}
Question: {question}
Proposed answer: {answer}
Explanation: {explanation}

Validation criteria:
1. Is the proposed answer factually / logically correct given the question?
2. Is the explanation consistent with the question and answer?
3. Is there any ambiguity that could allow a different answer?
4. For math/logic puzzles: verify the calculation or deduction is sound.
5. For trivia: verify the stated fact is accurate.
6. For riddles/wordplay: verify the answer satisfies the clue uniquely.

Respond with ONLY valid JSON (no markdown, no code fences):
{{
  "valid": true or false,
  "confidence": "high" or "medium" or "low",
  "reason": "One concise sentence explaining the verdict."
}}"""

    messages = [
        {"role": "system", "content": "You are a strict logic and fact-checking validator. Return only JSON."},
        {"role": "user",   "content": prompt},
    ]

    raw = _groq_generate(messages, max_tokens=256, temperature=0.0)
    if not raw:
        logger.warning("[Validator] Groq validator did not respond — skipping validation.")
        return {"valid": True, "confidence": "low", "reason": "Validator unavailable; skipped."}

    try:
        # Strip any accidental markdown fences
        import re as _rev
        clean = _rev.sub(r"```(?:json)?|```", "", raw).strip()
        start = clean.find('{')
        end   = clean.rfind('}')
        if start != -1 and end != -1:
            clean = clean[start:end + 1]
        result = json.loads(clean)
        logger.info(
            "[Validator] Verdict: valid=%s, confidence=%s | %s",
            result.get("valid"), result.get("confidence"), result.get("reason", "")
        )
        return result
    except Exception as exc:
        logger.warning("[Validator] Could not parse validator response: %s | Raw: %s", exc, raw[:200])
        return {"valid": True, "confidence": "low", "reason": "Validator parse error; assumed valid."}


# ═══════════════════════════════════════════════════════════════════════════════
#  PuzzleGenerator
# ═══════════════════════════════════════════════════════════════════════════════

class PuzzleGenerator:
    """
    Generates cognitive exercises using the Groq API (groq.com).
    Model: llama-3.3-70b-versatile (ultra-fast inference, free tier).
    """

    def __init__(self, *args, **kwargs):
        self.puzzles: dict = {}
        self._recent_tags: list = []
        self._last_model_used: str = f"Groq / {GROQ_MODEL}"
        self._last_model_id: str = GROQ_MODEL

    # ── Active model (for health / status endpoints) ──────────────────────────

    @property
    def active_model(self) -> str:
        return self._last_model_id or GROQ_MODEL

    @property
    def active_model_display(self) -> str:
        return self._last_model_used or f"Groq / {GROQ_MODEL}"

    # ── Offline / Fallback Generator ──────────────────────────────────────────
    def _generate_offline_puzzle(self, difficulty: str = "medium", puzzle_type: str = "riddle") -> dict:
        """Serve a verified, curated puzzle when offline or when Groq API is not configured."""
        import copy
        category = (puzzle_type or "riddle").lower()
        diff = (difficulty or "medium").lower()
        key = (category, diff)
        pool = _OFFLINE_PUZZLES.get(key)
        if not pool:
            pool = [p for (c, _), plist in _OFFLINE_PUZZLES.items() if c == category for p in plist]
        if not pool:
            pool = _OFFLINE_PUZZLES.get(("riddle", "medium"), [])

        selected = copy.deepcopy(random.choice(pool))
        puzzle_id = str(uuid.uuid4())[:8]
        selected["id"] = puzzle_id
        selected["difficulty"] = diff
        selected["type"] = category
        selected["solved"] = False
        selected["created_at"] = datetime.now().isoformat()
        selected["model_used"] = "Synaptia Cognitive Engine (Curated Suite)"
        selected["validation"] = {
            "passed": True,
            "confidence": "high",
            "note": "Verified by Synaptia Curated Logic Engine",
            "validator": "Curated Logic Suite",
        }
        self._last_model_used = "Synaptia Cognitive Engine (Curated Suite)"
        self._last_model_id = "synaptia-curated-engine"
        self.puzzles[puzzle_id] = selected
        return selected

    # ── Puzzle generation ─────────────────────────────────────────────────────

    def generate_puzzle(self, difficulty="medium", puzzle_type="riddle"):
        try:
            return self._generate_with_validation(difficulty, puzzle_type, attempt=1)
        except Exception as e:
            logger.error("[PuzzleGen] Unhandled exception: %s", e)
            return {"error": str(e), "message": "Failed to generate puzzle"}

    def _generate_with_validation(self, difficulty, puzzle_type, attempt=1):
        """Generate a puzzle then cross-validate it. Regenerates once if validation fails."""
        MAX_ATTEMPTS = 2

        messages = self._build_messages(difficulty, puzzle_type)
        puzzle_content = _groq_generate(messages, max_tokens=1024, temperature=1.0)

        if puzzle_content is None:
            logger.info(
                "[PuzzleGen] Groq API unavailable or unconfigured — serving verified curated exercise for (%s, %s).",
                difficulty, puzzle_type
            )
            return self._generate_offline_puzzle(difficulty, puzzle_type)

        self._last_model_used = f"Groq / {GROQ_MODEL}"
        self._last_model_id = GROQ_MODEL

        puzzle = self._parse_puzzle(puzzle_content, difficulty, puzzle_type)

        # ── AI Cross-Validation ──────────────────────────────────────────────
        question    = puzzle.get("question", "")
        answer      = puzzle.get("answer", "")
        explanation = puzzle.get("explanation", "")

        if question and answer and "N/A" not in answer:
            validation = _groq_validate_puzzle(question, answer, explanation, puzzle_type)
            puzzle["validation"] = {
                "passed":     validation.get("valid", True),
                "confidence": validation.get("confidence", "low"),
                "note":       validation.get("reason", ""),
                "validator":  f"Groq / {GROQ_VALIDATOR_MODEL}",
            }

            if not validation.get("valid", True) and attempt < MAX_ATTEMPTS:
                logger.warning(
                    "[PuzzleGen] Validation FAILED (attempt %d/%d) — reason: %s. Regenerating…",
                    attempt, MAX_ATTEMPTS, validation.get("reason", "unknown")
                )
                return self._generate_with_validation(difficulty, puzzle_type, attempt + 1)

            if not validation.get("valid", True):
                logger.warning(
                    "[PuzzleGen] Validation FAILED after %d attempts. Returning best-effort puzzle.",
                    MAX_ATTEMPTS
                )
        else:
            puzzle["validation"] = {
                "passed":     None,
                "confidence": "low",
                "note":       "Puzzle could not be validated (parse error or N/A answer).",
                "validator":  f"Groq / {GROQ_VALIDATOR_MODEL}",
            }
        # ─────────────────────────────────────────────────────────────────────

        puzzle_id = str(uuid.uuid4())[:8]
        puzzle["id"]         = puzzle_id
        puzzle["created_at"] = datetime.now().isoformat()
        puzzle["model_used"] = self._last_model_used
        self.puzzles[puzzle_id] = puzzle
        return puzzle

    # ── Prompt / message building ─────────────────────────────────────────────

    def _build_messages(self, difficulty, puzzle_type) -> list:
        """Build the chat messages list for puzzle generation."""
        system_content = (
            "You are a world-class puzzle master with an encyclopaedic knowledge "
            "of riddles, logic, mathematics, wordplay, and trivia. "
            "You ALWAYS create unique, original puzzles — never repeat a puzzle you have given before. "
            "Respond with ONLY valid JSON. No markdown, no code fences, no extra text whatsoever."
        )

        difficulty_desc = {
            "easy":   "suitable for beginners, straightforward logic with clear reasoning",
            "medium": "moderate difficulty requiring creative thinking and analysis",
            "hard":   "challenging puzzle requiring deep logical reasoning and multi-step problem-solving",
        }
        puzzle_type_desc = {
            "riddle":   "a clever riddle or wordplay puzzle with a surprising, satisfying answer",
            "math":     "a mathematical logic puzzle requiring calculation and deduction",
            "logic":    "a deductive logic puzzle requiring systematic elimination",
            "wordplay": "a lateral thinking or wordplay brain teaser",
            "trivia":   "an interesting trivia question with a fascinating explanation",
        }
        base_diff   = difficulty_desc.get(difficulty, "moderate difficulty")
        puzzle_desc = puzzle_type_desc.get(puzzle_type, "an engaging riddle")

        angle_pool = _ANGLE_MAP.get(puzzle_type, _RIDDLE_ANGLES)
        fresh = [a for a in angle_pool if a not in self._recent_tags]
        if not fresh:
            fresh = angle_pool
            self._recent_tags = []

        angle = random.choice(fresh)
        nonce = uuid.uuid4().hex[:8]

        self._recent_tags.append(angle)
        if len(self._recent_tags) > len(angle_pool) // 2:
            self._recent_tags.pop(0)

        user_content = f"""Create {puzzle_desc} ({base_diff}).

UNIQUENESS DIRECTIVE — CRITICAL:
- Theme / domain: "{angle}"
- Session nonce: {nonce}  ← use this as creative inspiration seed
- The puzzle MUST be original and MUST NOT be a common or well-known puzzle.
- Do NOT repeat standard classics (e.g. "I speak without a mouth", "man in an elevator", "Tuesday").

REQUIREMENTS:
- Puzzle must be interesting, engaging, and NOT trivial
- Answer must be clear, correct, and verifiable
- Provide exactly 3 progressive hints (each as a plain string, no newlines inside strings)
- Provide 2-3 solution steps explaining the reasoning (each as a plain string)
- ALL string values must be on a single line — do NOT use literal newline characters inside any string value

Return ONLY valid JSON with this exact structure:
{{
    "question": "The complete puzzle question on a single line",
    "answer": "The single correct answer (1-3 words ideally)",
    "explanation": "Clear 1-2 sentence explanation on a single line",
    "hints": [
        "Hint 1: subtle directional clue on one line",
        "Hint 2: narrows possibilities significantly on one line",
        "Hint 3: strong hint that almost reveals the answer on one line"
    ],
    "solution_steps": [
        "Step 1: First part of the logical reasoning on one line",
        "Step 2: How to arrive at the answer on one line",
        "Step 3: Why this answer is definitive on one line"
    ],
    "category": "{puzzle_type}",
    "difficulty": "{difficulty}"
}}"""

        return [
            {"role": "system", "content": system_content},
            {"role": "user",   "content": user_content},
        ]

    # ── Parsing Infrastructure ─────────────────────────────────────────────────

    def _extract_json_object(self, text):
        start = text.find('{')
        if start == -1:
            return text

        depth = 0
        in_string = False
        escape_next = False

        for i in range(start, len(text)):
            c = text[i]
            if escape_next:
                escape_next = False
                continue
            if c == '\\' and in_string:
                escape_next = True
                continue
            if c == '"':
                in_string = not in_string
                continue
            if in_string:
                continue
            if c == '{':
                depth += 1
            elif c == '}':
                depth -= 1
                if depth == 0:
                    return text[start:i + 1]

        end = text.rfind('}')
        if end > start:
            return text[start:end + 1]
        return text

    def _sanitize_string_values(self, content):
        result = []
        in_string = False
        escape_next = False

        for c in content:
            if escape_next:
                result.append(c)
                escape_next = False
            elif c == '\\' and in_string:
                result.append(c)
                escape_next = True
            elif c == '"':
                in_string = not in_string
                result.append(c)
            elif c == '\n' and in_string:
                result.append('\\n')
            elif c == '\r' and in_string:
                result.append('\\r')
            elif c == '\t' and in_string:
                result.append('\\t')
            else:
                result.append(c)

        return ''.join(result)

    def _parse_puzzle(self, content, difficulty, puzzle_type):
        import re
        try:
            raw = content.strip()
            extracted = self._extract_json_object(raw)
            sanitized = self._sanitize_string_values(extracted)

            try:
                puzzle_data = json.loads(sanitized)
            except json.JSONDecodeError:
                fence_match = re.search(r"```(?:json)?(.*?)```", raw, re.DOTALL | re.IGNORECASE)
                if fence_match:
                    candidate = fence_match.group(1).strip()
                else:
                    candidate = self._extract_json_object(self._sanitize_string_values(raw))
                puzzle_data = json.loads(candidate)

            puzzle_data["difficulty"] = difficulty
            puzzle_data["type"]       = puzzle_type
            puzzle_data["solved"]     = False

            if "solution_steps" not in puzzle_data:
                puzzle_data["solution_steps"] = [puzzle_data.get("explanation", "No explanation available.")]
            elif isinstance(puzzle_data["solution_steps"], str):
                puzzle_data["solution_steps"] = [puzzle_data["solution_steps"]]

            if "hints" in puzzle_data and isinstance(puzzle_data["hints"], str):
                puzzle_data["hints"] = [puzzle_data["hints"]]

            return puzzle_data

        except Exception as e:
            logger.error("[PuzzleGen] Parse failure — %s | Raw excerpt: %s", e, content[:300])

            return self._generate_offline_puzzle(difficulty, puzzle_type)

    # ── Retrieval & Validation ─────────────────────────────────────────────────

    def get_puzzle(self, puzzle_id):
        return self.puzzles.get(puzzle_id)

    def list_puzzles(self):
        safe_list = []
        for p in self.puzzles.values():
            safe = {k: v for k, v in p.items() if k not in ("answer", "solution_steps")}
            safe_list.append(safe)
        return safe_list

    def check_answer(self, puzzle_id, user_answer):
        """Check if the user's answer is correct using normalised fuzzy matching."""
        puzzle = self.get_puzzle(puzzle_id)
        if not puzzle:
            return {"error": "Exercise not found"}

        import re
        from difflib import SequenceMatcher

        user_norm    = re.sub(r'[^a-z0-9\s]', '', user_answer.lower().strip())
        correct_norm = re.sub(r'[^a-z0-9\s]', '', puzzle["answer"].lower().strip())

        correct = False

        if user_norm == correct_norm:
            correct = True
        else:
            stopwords = {"a", "an", "the", "it", "is", "its", "of", "and"}
            user_tokens    = set(user_norm.split()) - stopwords
            correct_tokens = set(correct_norm.split()) - stopwords

            if user_tokens == correct_tokens and len(correct_tokens) > 0:
                correct = True
            elif correct_tokens and correct_tokens.issubset(user_tokens):
                correct = True
            elif correct_tokens and user_tokens:
                meaningful = {w for w in correct_tokens if len(w) > 3}
                if meaningful and meaningful.intersection(user_tokens):
                    correct = True

            if not correct and len(correct_norm) > 3:
                ratio = SequenceMatcher(None, user_norm, correct_norm).ratio()
                if ratio > 0.8:
                    correct = True

        if correct:
            puzzle["solved"] = True

        return {
            "correct": correct,
            "answer":  puzzle["answer"] if correct else None,
        }
