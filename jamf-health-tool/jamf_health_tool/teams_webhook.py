"""
Teams webhook sender.
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional

import requests


def post_teams_summary(webhook_url: str, title: str, summary: str, data: Dict[str, Any], logger: Optional[logging.Logger] = None) -> None:
    """
    Post a simple summary to a Teams incoming webhook.
    """
    log = logger or logging.getLogger(__name__)
    payload = {
        "@type": "MessageCard",
        "@context": "http://schema.org/extensions",
        "summary": summary,
        "themeColor": "0076D7",
        "title": title,
        "text": summary,
        "sections": [
            {
                "facts": [{"name": k, "value": str(v)} for k, v in data.items()],
            }
        ],
    }
    try:
        resp = requests.post(webhook_url, json=payload, timeout=10)
        if resp.status_code >= 400:
            log.warning("Teams webhook returned HTTP %s: %s", resp.status_code, resp.text[:200])
    except Exception as exc:
        log.warning("Failed to post Teams webhook: %s", exc)
