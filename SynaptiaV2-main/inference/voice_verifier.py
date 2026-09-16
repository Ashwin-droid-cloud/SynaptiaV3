"""Speaker Voice Verification & Identification module.

Extracts and compares acoustic voiceprint descriptors using zero-mean normalized
correlation (spectral Pearson correlation) to distinguish different individuals
from each other, bystanders, and background chatter.
"""

import math
import logging
from typing import Optional

logger = logging.getLogger("voice_verifier")

DEFAULT_SIMILARITY_THRESHOLD = 0.58


def normalize_and_center(vec: list[float]) -> list[float]:
    """Zero-mean center and normalize vector to eliminate microphone baseline and room noise.
    
    This computes the pure spectral variance shape of the vocal tract, ensuring that
    different voices have distinct positive and negative spectral peaks, while background
    hum produces near-zero correlation.
    """
    if not vec:
        return []
    mean = sum(vec) / len(vec)
    centered = [v - mean for v in vec]
    norm = math.sqrt(sum(v * v for v in centered))
    if norm == 0.0:
        return [0.0] * len(vec)
    return [v / norm for v in centered]


def cosine_similarity(vec_a: list[float], vec_b: list[float]) -> float:
    """Compute normalized zero-mean correlation between two acoustic embedding vectors."""
    if not vec_a or not vec_b:
        return 0.0
    min_len = min(len(vec_a), len(vec_b))
    a = normalize_and_center(vec_a[:min_len])
    b = normalize_and_center(vec_b[:min_len])

    dot_product = sum(x * y for x, y in zip(a, b))
    return max(-1.0, min(1.0, dot_product))


def verify_speaker_voice(
    candidate_descriptor: Optional[list[float]],
    enrolled_descriptor: Optional[list[float]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[bool, float]:
    """Verify if candidate utterance voice matches an enrolled user profile.
    
    Returns (is_verified, similarity_score).
    If no enrolled descriptor exists yet, returns (True, 1.0) to allow baseline operation.
    """
    if not enrolled_descriptor:
        return True, 1.0

    if not candidate_descriptor:
        return True, 1.0

    similarity = cosine_similarity(candidate_descriptor, enrolled_descriptor)
    is_match = similarity >= threshold

    logger.info(
        "Speaker verification: similarity=%.4f, threshold=%.2f, match=%s",
        similarity,
        threshold,
        is_match,
    )
    return is_match, similarity


def identify_best_speaker(
    candidate_descriptor: Optional[list[float]],
    enrolled_profiles: dict[str, list[float]],
    threshold: float = DEFAULT_SIMILARITY_THRESHOLD,
) -> tuple[Optional[str], float]:
    """Identify which enrolled individual is speaking based on acoustic voiceprints.
    
    Args:
        candidate_descriptor: 128D acoustic spectral vector from speech utterance
        enrolled_profiles: dict mapping person name -> enrolled voice descriptor
        threshold: minimum similarity required to confirm identity
        
    Returns:
        (best_speaker_name, highest_similarity)
        Returns (None, best_similarity) if no profile meets the threshold.
    """
    if not candidate_descriptor or not enrolled_profiles:
        return None, 0.0

    best_name: Optional[str] = None
    best_similarity = -1.0

    for name, enrolled_vec in enrolled_profiles.items():
        if not enrolled_vec:
            continue
        sim = cosine_similarity(candidate_descriptor, enrolled_vec)
        logger.debug("Testing candidate voice vs %s: similarity=%.4f", name, sim)
        if sim > best_similarity:
            best_similarity = sim
            if sim >= threshold:
                best_name = name

    if best_name:
        logger.info("Identified speaker: '%s' with similarity %.4f (threshold=%.2f)", best_name, best_similarity, threshold)
    else:
        logger.info("No speaker matched above threshold %.2f (highest=%.4f)", threshold, best_similarity)

    return best_name, best_similarity
