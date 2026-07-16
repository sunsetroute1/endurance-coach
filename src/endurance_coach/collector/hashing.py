"""Content hashing for raw payload deduplication."""

import hashlib
import json
from typing import Any


def payload_content_hash(payload: dict[str, Any]) -> str:
    canonical = json.dumps(payload, sort_keys=True, separators=(",", ":"), default=str)
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()
