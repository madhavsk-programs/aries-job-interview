"""Observation-only integrity monitor.

No observation produced here is a cheating, fraud, honesty, or intent verdict.
"""

from __future__ import annotations

from typing import Any


def build_observations(delivery: dict[str, Any]) -> list[dict[str, Any]]:
    observations: list[dict[str, Any]] = []
    longest = int(delivery.get("longest_pause_ms", 0) or 0)
    if longest >= 5000:
        observations.append(
            {
                "type": "long_pause",
                "severity": "info",
                "value_ms": longest,
                "message": f"A pause of approximately {longest / 1000:.1f} seconds was observed.",
                "interpretation": "Observation only; no cause or intent is inferred.",
            }
        )

    if int(delivery.get("word_count", 0) or 0) < 25:
        observations.append(
            {
                "type": "limited_audio_sample",
                "severity": "info",
                "message": "The interview contains too little candidate speech for stable delivery metrics.",
                "interpretation": "Delivery labels should be treated as low-confidence measurements.",
            }
        )

    return observations

