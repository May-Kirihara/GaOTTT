"""Lateral Association Stage 1 — formatter id-manifest contract.

``services.formatters.format_ambient`` appends a
``<!-- ambient-ids ... -->`` HTML comment at the end of every non-empty
ambient block so the ``UserPromptSubmit`` hook can parse it without server
round-trips. These tests pin the contract: the manifest must include every
slot's id and omit keys whose slot is empty.

See Plans-Ambient-Recall-Lateral-Association.md Stage 1 sub-step 1.
"""
from __future__ import annotations

from gaottt.core.types import (
    AmbientMemory,
    AmbientPersona,
    AmbientRecallResponse,
)
from gaottt.services.formatters import format_ambient


def _mem(id_: str, content: str = "stub content") -> AmbientMemory:
    return AmbientMemory(id=id_, content=content, source="agent")


def test_manifest_lists_every_slot_when_all_populated():
    resp = AmbientRecallResponse(
        direct=[_mem("aaa11111"), _mem("bbb22222")],
        lensing=[_mem("ccc33333")],
        persona=AmbientPersona(id="ddd44444", kind="value", content="me"),
        count=3,
    )
    out = format_ambient(resp)
    assert "<!-- ambient-ids" in out
    assert "direct=aaa11111,bbb22222" in out
    assert "lensing=ccc33333" in out
    assert "persona=ddd44444" in out


def test_manifest_lists_topk_lensing_comma_separated():
    """Stage 3 — manifest carries every top-K lensing id, comma-separated.
    The hook parser already splits on commas within slot=... chunks, so no
    parser change is required — the test pins the wire shape that drives
    the hook's ``recently_surfaced`` map."""
    resp = AmbientRecallResponse(
        direct=[_mem("aaa11111")],
        lensing=[_mem("lns01111"), _mem("lns02222"), _mem("lns03333")],
        count=4,
    )
    out = format_ambient(resp)
    assert "lensing=lns01111,lns02222,lns03333" in out
    # Visible heading includes the count when N > 1 so the reader knows.
    assert "▼ 重力レンズ（3 件" in out


def test_manifest_omits_empty_slot_keys():
    resp = AmbientRecallResponse(
        direct=[_mem("only_direct")],
        count=1,
    )
    out = format_ambient(resp)
    assert "direct=only_direct" in out
    assert "lensing=" not in out
    assert "persona=" not in out


def test_manifest_skipped_when_no_slots():
    # Persona-only payload — manifest still emitted but only with persona key.
    resp = AmbientRecallResponse(
        persona=AmbientPersona(id="solo_persona", kind="intention", content="x"),
        count=1,
    )
    out = format_ambient(resp)
    assert "persona=solo_persona" in out
    assert "direct=" not in out
    assert "lensing=" not in out


def test_no_manifest_on_empty_block():
    # Relevance gate killed everything — the non-block sentinel doesn't carry
    # a manifest (there is nothing for the hook to remember).
    resp = AmbientRecallResponse(count=0)
    out = format_ambient(resp)
    assert "<!-- ambient-ids" not in out
    assert "<gaottt-ambient-recall>" not in out


def test_manifest_placement_inside_closing_tag():
    """The manifest must sit *before* ``</gaottt-ambient-recall>`` so the
    block stays a single coherent chunk that hook regex parses without
    needing to look outside the tags."""
    resp = AmbientRecallResponse(
        direct=[_mem("first")],
        persona=AmbientPersona(id="p", kind="value", content="me"),
        count=2,
    )
    out = format_ambient(resp)
    manifest_idx = out.find("<!-- ambient-ids")
    closing_idx = out.find("</gaottt-ambient-recall>")
    assert 0 < manifest_idx < closing_idx, (
        "manifest must be enclosed inside the ambient block tags"
    )
