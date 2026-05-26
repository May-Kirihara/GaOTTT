"""Observation Apparatus Refinement Stage 4 — bucket classifier.

Pin the source → bucket mapping. The classifier is force-blind and
mass-blind by construction; it only routes display rows. These tests
also document the rule for future readers.
"""

from __future__ import annotations

from gaottt.services.reflection import _connection_bucket


def test_two_personas_become_persona_bucket() -> None:
    assert _connection_bucket("value", "intention") == "persona"
    assert _connection_bucket("commitment", "value") == "persona"


def test_file_endpoint_routes_to_ingest_bucket() -> None:
    assert _connection_bucket("file", "agent") == "ingest"
    assert _connection_bucket("agent", "file") == "ingest"
    assert _connection_bucket("file", "file") == "ingest"


def test_tweet_or_csv_endpoint_also_ingest() -> None:
    assert _connection_bucket("tweet", "agent") == "ingest"
    assert _connection_bucket("csv", "user") == "ingest"
    assert _connection_bucket("claude-code", "agent") == "ingest"


def test_chat_export_endpoints_route_to_ingest() -> None:
    """Fix #2 — ChatGPT and Claude.ai web export sources (loader.py L109/L119)
    must land in the ingest bucket so same-conversation chunk co-occurrence
    does not crowd out cross-domain pairs in the dialogue bucket."""
    assert _connection_bucket("openai", "openai") == "ingest"
    assert _connection_bucket("openai", "agent") == "ingest"
    assert _connection_bucket("claude-web", "claude-web") == "ingest"
    assert _connection_bucket("claude-web", "agent") == "ingest"
    assert _connection_bucket("chat-export", "agent") == "ingest"


def test_agent_user_is_default_for_dialogue() -> None:
    assert _connection_bucket("agent", "agent") == "agent_user"
    assert _connection_bucket("user", "agent") == "agent_user"
    assert _connection_bucket("hypothesis", "note") == "agent_user"


def test_persona_plus_dialogue_is_agent_user() -> None:
    """A persona endpoint paired with a dialogue endpoint does NOT count as
    persona — the bucket is reserved for value↔value/intention pairs."""
    assert _connection_bucket("value", "agent") == "agent_user"
    assert _connection_bucket("intention", "note") == "agent_user"


def test_none_endpoint_falls_through_to_dialogue() -> None:
    """An unknown source is treated as dialogue, not as ingest."""
    assert _connection_bucket(None, None) == "agent_user"
    assert _connection_bucket("agent", None) == "agent_user"
