"""Instruction Surface Hygiene Stage 2a — ambient slot content truncation.

Pure unit tests: construct AmbientRecallResponse models and call
format_ambient with/without config to verify truncation behaviour.
"""
from __future__ import annotations

from dataclasses import dataclass

from gaottt.core.types import (
    AmbientMemory,
    AmbientPersona,
    AmbientRecallResponse,
)
from gaottt.services import formatters


def _ambient_mem(content: str, *, mid: str = "abc12345") -> AmbientMemory:
    return AmbientMemory(id=mid, content=content, source="agent")


def _response(
    *,
    direct: list[AmbientMemory] | None = None,
    lensing: list[AmbientMemory] | None = None,
    dormant: list[AmbientMemory] | None = None,
    persona: AmbientPersona | None = None,
) -> AmbientRecallResponse:
    d = direct or []
    l = lensing or []
    dm = dormant or []
    total = len(d) + len(l) + len(dm) + (1 if persona else 0)
    return AmbientRecallResponse(direct=d, lensing=l, dormant=dm, persona=persona, count=total)


@dataclass
class _FakeConfig:
    ambient_direct_max_chars: int = 0
    ambient_lensing_max_chars: int = 0


def test_no_config_means_no_truncation():
    long = "x" * 500
    resp = _response(direct=[_ambient_mem(long)])
    rendered = formatters.format_ambient(resp)
    assert long in rendered


def test_config_none_means_no_truncation():
    long = "x" * 500
    resp = _response(direct=[_ambient_mem(long)])
    rendered = formatters.format_ambient(resp, config=None)
    assert long in rendered


def test_direct_slot_truncated_with_config():
    long = "a" * 400
    cfg = _FakeConfig(ambient_direct_max_chars=50, ambient_lensing_max_chars=0)
    resp = _response(direct=[_ambient_mem(long)])
    rendered = formatters.format_ambient(resp, config=cfg)
    assert "a" * 400 not in rendered
    assert "…(400 chars)" in rendered
    assert rendered.count("a" * 50) >= 1


def test_direct_slot_zero_limit_means_unlimited():
    long = "b" * 600
    cfg = _FakeConfig(ambient_direct_max_chars=0, ambient_lensing_max_chars=0)
    resp = _response(direct=[_ambient_mem(long)])
    rendered = formatters.format_ambient(resp, config=cfg)
    assert long in rendered


def test_lensing_slot_truncated():
    long = "c" * 400
    cfg = _FakeConfig(ambient_direct_max_chars=0, ambient_lensing_max_chars=100)
    resp = _response(lensing=[_ambient_mem(long, mid="lens1")])
    rendered = formatters.format_ambient(resp, config=cfg)
    assert "c" * 400 not in rendered
    assert "…(400 chars)" in rendered


def test_dormant_slot_truncated_with_lensing_limit():
    long = "d" * 500
    cfg = _FakeConfig(ambient_direct_max_chars=0, ambient_lensing_max_chars=80)
    resp = _response(dormant=[_ambient_mem(long, mid="dorm1")])
    rendered = formatters.format_ambient(resp, config=cfg)
    assert "d" * 500 not in rendered
    assert "…(500 chars)" in rendered


def test_persona_slot_not_truncated():
    long = "p" * 500
    cfg = _FakeConfig(ambient_direct_max_chars=10, ambient_lensing_max_chars=10)
    persona = AmbientPersona(id="persp1", kind="value", content=long)
    resp = _response(persona=persona)
    rendered = formatters.format_ambient(resp, config=cfg)
    assert long in rendered


def test_truncate_helper_passthrough():
    assert formatters._truncate("hello", 0) == "hello"
    assert formatters._truncate("hello", -1) == "hello"
    assert formatters._truncate("hi", 10) == "hi"


def test_truncate_helper_shortens():
    out = formatters._truncate("abcdefghij", 5)
    assert out == "abcde…(10 chars)"
