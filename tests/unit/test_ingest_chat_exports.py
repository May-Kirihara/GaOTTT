"""Unit tests for OpenAI and Claude.ai web chat-export (.json) ingestion.

Covers shape sniff, turn-pair grouping, active-path tree walk (OpenAI),
linear walk (Claude.ai), filter rules (short turn / system / tool /
branch / hidden / thinking), and ``original_id``/``conversation_id``
propagation.
"""

from __future__ import annotations

import json
from pathlib import Path

from gaottt.ingest.loader import ingest_path

# Padding suffix to push fixture content past the 100-char user+assistant
# combined threshold. Substantial enough that any single pair clears it.
_PAD = "ここは内容を膨らませる為のパディングです。" * 4  # ~80 chars


# -----------------------------------------------------------------------
# OpenAI ChatGPT export
# -----------------------------------------------------------------------

def _openai_node(
    nid: str,
    role: str,
    content_text: str,
    parent: str | None,
    content_type: str = "text",
    hidden: bool = False,
    create_time: float = 1700000000.0,
    author_name: str | None = None,
) -> dict:
    parts: list = [content_text]
    msg: dict = {
        "id": nid,
        "author": {"role": role},
        "create_time": create_time,
        "content": {"content_type": content_type, "parts": parts},
        "metadata": {},
    }
    if hidden:
        msg["metadata"]["is_visually_hidden_from_conversation"] = True
    if author_name:
        msg["author"]["name"] = author_name
    return {"id": nid, "message": msg, "parent": parent}


def _openai_conv(nodes: list[dict], current_node: str, **extra) -> dict:
    mapping = {n["id"]: n for n in nodes}
    base = {
        "conversation_id": extra.get("conversation_id", "conv-1"),
        "title": extra.get("title", "テスト会話"),
        "create_time": 1700000000.0,
        "current_node": current_node,
        "default_model_slug": extra.get("model", "gpt-4"),
        "mapping": mapping,
    }
    base.update(extra)
    return base


def _write_json(tmp_path: Path, data, name: str = "export.json") -> Path:
    p = tmp_path / name
    p.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
    return p


def test_openai_basic_pair(tmp_path: Path) -> None:
    nodes = [
        _openai_node("r", "system", "hidden system prompt that should be dropped",
                     parent=None),
        _openai_node("u1", "user",
                     "下水道清掃のプロンプトを作ってほしいです。"
                     "stable diffusion 向けに細部まで描写したい。",
                     parent="r"),
        _openai_node("a1", "assistant",
                     "了解しました。下水道で作業する清掃員を詳細に描写するプロンプトを構成します。"
                     "服装、道具、環境の三要素を明示します。",
                     parent="u1"),
    ]
    conv = _openai_conv(nodes, current_node="a1")
    p = _write_json(tmp_path, [conv])

    docs = ingest_path(str(p))
    assert len(docs) == 1
    body = docs[0]["content"]
    assert "## User\n下水道清掃のプロンプト" in body
    assert "## Assistant" in body
    assert "清掃員を詳細に描写" in body

    meta = docs[0]["metadata"]
    assert meta["source"] == "openai"
    assert meta["conversation_id"] == "conv-1"
    assert meta["original_id"] == "conv-1"
    assert meta["turn_index"] == 0
    assert meta["title"] == "テスト会話"
    assert meta["model"] == "gpt-4"


def test_openai_dispatch_explicit_source_wins(tmp_path: Path) -> None:
    nodes = [
        _openai_node("u1", "user", "ping with quite a bit of text here " + _PAD,
                     parent=None),
        _openai_node("a1", "assistant", "pong reply that is long enough " + _PAD,
                     parent="u1"),
    ]
    p = _write_json(tmp_path, [_openai_conv(nodes, current_node="a1")])
    docs = ingest_path(str(p), source="custom-label")
    assert docs
    assert docs[0]["metadata"]["source"] == "custom-label"


def test_openai_drops_system_and_hidden(tmp_path: Path) -> None:
    nodes = [
        _openai_node("s1", "system", "あなたはアシスタントです" * 20, parent=None),
        _openai_node("u1", "user",
                     "ユーザーの質問です。ある程度長めの内容を書きます。" + _PAD,
                     parent="s1"),
        _openai_node("h1", "assistant", "hidden response that should drop " + _PAD,
                     parent="u1", hidden=True),
        _openai_node("a1", "assistant",
                     "本物の回答です。これも長めにします。" + _PAD, parent="h1"),
    ]
    conv = _openai_conv(nodes, current_node="a1")
    p = _write_json(tmp_path, [conv])

    docs = ingest_path(str(p))
    assert len(docs) == 1
    body = docs[0]["content"]
    assert "あなたはアシスタントです" not in body
    assert "hidden response" not in body
    assert "本物の回答" in body


def test_openai_drops_tool_unless_opted_in(tmp_path: Path) -> None:
    nodes = [
        _openai_node("u1", "user",
                     "What is in the file? Need a bit more text here. " + _PAD,
                     parent=None),
        _openai_node("t1", "tool",
                     "raw tool stdout that the user shouldn't normally see " + _PAD,
                     parent="u1", author_name="file_search"),
        _openai_node("a1", "assistant",
                     "Based on the search, the file contains X. " + _PAD,
                     parent="t1"),
    ]
    conv = _openai_conv(nodes, current_node="a1")
    p = _write_json(tmp_path, [conv])

    # Default — tool dropped.
    docs = ingest_path(str(p))
    assert len(docs) == 1
    assert "raw tool stdout" not in docs[0]["content"]
    assert "Based on the search" in docs[0]["content"]

    # Opt-in — tool kept with [tool_result:...] tag.
    docs2 = ingest_path(str(p), include_tool_results=True)
    assert len(docs2) == 1
    assert "[tool_result:file_search]" in docs2[0]["content"]
    assert "raw tool stdout" in docs2[0]["content"]


def test_openai_active_path_ignores_branches(tmp_path: Path) -> None:
    # Tree:  u1 -> a1 (current_node)
    #          \-> a1_branch (regen alternative — must be ignored)
    nodes = [
        _openai_node("u1", "user", "質問は何ですか? 少し長めに書いておきます。" + _PAD,
                     parent=None),
        _openai_node("a1", "assistant",
                     "メイン回答（採用されたバージョン）です。" + _PAD, parent="u1"),
        _openai_node("a1_branch", "assistant",
                     "別ブランチの捨てられた回答です。" + _PAD, parent="u1"),
    ]
    conv = _openai_conv(nodes, current_node="a1")
    p = _write_json(tmp_path, [conv])

    docs = ingest_path(str(p))
    assert len(docs) == 1
    body = docs[0]["content"]
    assert "メイン回答" in body
    assert "別ブランチ" not in body


def test_openai_short_turn_dropped(tmp_path: Path) -> None:
    nodes = [
        _openai_node("u1", "user", "yo", parent=None),
        _openai_node("a1", "assistant", "ok", parent="u1"),
    ]
    p = _write_json(tmp_path, [_openai_conv(nodes, current_node="a1")])
    docs = ingest_path(str(p))
    # user+asst combined < 100 chars → dropped.
    assert docs == []


def test_openai_multi_turn_distinct_original_id_within_conv(tmp_path: Path) -> None:
    """All turn-pairs in one conversation must share original_id (=conv_id)
    so Phase L's self-force filter recognises them as one orbit."""
    nodes = [
        _openai_node("u1", "user", "最初の質問。長さを稼ぐためにいろいろ書きます。" + _PAD,
                     parent=None),
        _openai_node("a1", "assistant",
                     "最初の回答。これもある程度長く書いておきます。" + _PAD,
                     parent="u1"),
        _openai_node("u2", "user",
                     "続きの質問。さらに詳しく聞きたいことがあります。" + _PAD,
                     parent="a1"),
        _openai_node("a2", "assistant",
                     "続きの回答です。詳細を補足していきます。" + _PAD, parent="u2"),
    ]
    p = _write_json(tmp_path, [_openai_conv(nodes, current_node="a2")])
    docs = ingest_path(str(p))
    assert len(docs) == 2
    ids = {d["metadata"]["original_id"] for d in docs}
    assert ids == {"conv-1"}
    turns = sorted(d["metadata"]["turn_index"] for d in docs)
    assert turns == [0, 1]


def test_openai_multimodal_dict_part(tmp_path: Path) -> None:
    """parts can contain {"text": "..."} dicts for multimodal messages."""
    nodes = [
        _openai_node("u1", "user",
                     "画像を見て答えてください。質問は十分に長くしておきます。" + _PAD,
                     parent=None),
    ]
    # Manually craft an assistant message with dict parts.
    nodes.append({
        "id": "a1",
        "message": {
            "id": "a1",
            "author": {"role": "assistant"},
            "content": {
                "content_type": "multimodal_text",
                "parts": [
                    {"content_type": "image_asset_pointer", "asset_pointer": "x"},
                    {"text": "画像にはネコが写っています。マルチモーダル返答です。" + _PAD},
                ],
            },
            "metadata": {},
        },
        "parent": "u1",
    })
    p = _write_json(tmp_path, [_openai_conv(nodes, current_node="a1")])
    docs = ingest_path(str(p))
    assert len(docs) == 1
    assert "ネコが写っています" in docs[0]["content"]


# -----------------------------------------------------------------------
# Claude.ai web export
# -----------------------------------------------------------------------

def _claude_web_msg(
    sender: str,
    text: str = "",
    content: list | None = None,
    attachments: list | None = None,
    files: list | None = None,
) -> dict:
    return {
        "uuid": "msg-" + sender,
        "text": text,
        "content": content or ([{"type": "text", "text": text}] if text else []),
        "sender": sender,
        "created_at": "2026-05-25T00:00:00Z",
        "attachments": attachments or [],
        "files": files or [],
    }


def _claude_web_conv(msgs: list[dict], **extra) -> dict:
    base = {
        "uuid": extra.get("uuid", "uuid-1"),
        "name": extra.get("name", "ある会話"),
        "summary": extra.get("summary", ""),
        "created_at": extra.get("created_at", "2026-05-25T00:00:00Z"),
        "updated_at": extra.get("updated_at", "2026-05-25T00:00:00Z"),
        "chat_messages": msgs,
    }
    return base


def test_claude_web_basic_pair(tmp_path: Path) -> None:
    msgs = [
        _claude_web_msg("human", "これは人間の質問です。長さを稼ぐために少し書きます。" + _PAD),
        _claude_web_msg(
            "assistant",
            content=[
                {"type": "thinking", "thinking": "考えています…これは隠す。" + _PAD},
                {"type": "text",
                 "text": "これがアシスタントの回答です。十分な長さがあります。" + _PAD},
            ],
        ),
    ]
    p = _write_json(tmp_path, [_claude_web_conv(msgs)])
    docs = ingest_path(str(p))
    assert len(docs) == 1
    body = docs[0]["content"]
    assert "人間の質問" in body
    assert "アシスタントの回答" in body
    # thinking is dropped
    assert "考えています" not in body

    meta = docs[0]["metadata"]
    assert meta["source"] == "claude-web"
    assert meta["conversation_id"] == "uuid-1"
    assert meta["original_id"] == "uuid-1"
    assert meta["title"] == "ある会話"
    assert meta["turn_index"] == 0


def test_claude_web_tool_use_summary_and_tool_result_opt_in(tmp_path: Path) -> None:
    msgs = [
        _claude_web_msg("human", "コマンドを実行してください。少し長めの依頼にします。" + _PAD),
        _claude_web_msg(
            "assistant",
            content=[
                {"type": "text", "text": "実行します。" + _PAD},
                {"type": "tool_use", "name": "Bash",
                 "input": {"command": "ls -la /tmp"}},
            ],
        ),
        _claude_web_msg(
            "human",  # In Claude.ai exports tool_results sometimes appear as human msgs
            content=[
                {"type": "tool_result", "content": "raw stdout that is noise by default"
                                                  + _PAD},
            ],
        ),
        _claude_web_msg(
            "assistant",
            content=[{"type": "text",
                      "text": "完了しました。後続の説明も少し書きます。" + _PAD}],
        ),
    ]
    p = _write_json(tmp_path, [_claude_web_conv(msgs)])

    docs = ingest_path(str(p))
    body = "\n---\n".join(d["content"] for d in docs)
    assert "[tool:Bash]" in body
    assert "ls -la /tmp" in body
    assert "raw stdout that is noise" not in body  # off by default

    docs2 = ingest_path(str(p), include_tool_results=True)
    body2 = "\n---\n".join(d["content"] for d in docs2)
    assert "raw stdout that is noise" in body2


def test_claude_web_attachments_in_metadata_only(tmp_path: Path) -> None:
    msgs = [
        _claude_web_msg(
            "human",
            "添付ファイルを見てください。質問本体は短くてもいいですが長さは稼ぎます。" + _PAD,
            attachments=[
                {"file_name": "kaiwa.txt", "file_size": 1024,
                 "extracted_content": "巨大なファイル本文をここに含めない。"},
            ],
        ),
        _claude_web_msg(
            "assistant",
            content=[{"type": "text",
                      "text": "確認しました。内容を要約します。" + _PAD}],
        ),
    ]
    p = _write_json(tmp_path, [_claude_web_conv(msgs)])
    docs = ingest_path(str(p))
    assert len(docs) == 1
    meta = docs[0]["metadata"]
    assert meta.get("attachments") == "kaiwa.txt"
    # The extracted_content must NOT have leaked into the body.
    assert "巨大なファイル本文" not in docs[0]["content"]


def test_claude_web_short_turn_dropped(tmp_path: Path) -> None:
    msgs = [
        _claude_web_msg("human", "yo"),
        _claude_web_msg("assistant", "ok"),
    ]
    p = _write_json(tmp_path, [_claude_web_conv(msgs)])
    assert ingest_path(str(p)) == []


def test_claude_web_multi_turn_share_original_id(tmp_path: Path) -> None:
    msgs = [
        _claude_web_msg("human", "1 つめの質問です。長さを稼ぎます。" + _PAD),
        _claude_web_msg("assistant", "1 つめの回答。これも長めに。" + _PAD),
        _claude_web_msg("human", "2 つめの質問。続きを聞きます。" + _PAD),
        _claude_web_msg("assistant", "2 つめの回答。詳しく説明します。" + _PAD),
    ]
    p = _write_json(tmp_path, [_claude_web_conv(msgs)])
    docs = ingest_path(str(p))
    assert len(docs) == 2
    ids = {d["metadata"]["original_id"] for d in docs}
    assert ids == {"uuid-1"}
    assert sorted(d["metadata"]["turn_index"] for d in docs) == [0, 1]


# -----------------------------------------------------------------------
# Dispatch / shape sniff
# -----------------------------------------------------------------------

def test_dispatch_handles_top_level_dict(tmp_path: Path) -> None:
    """A single exported conversation can appear as a top-level dict, not list."""
    nodes = [
        _openai_node("u1", "user", "単一会話の export。長さを稼いでおきます。" + _PAD,
                     parent=None),
        _openai_node("a1", "assistant",
                     "それに対する回答。これもある程度長くしておきます。" + _PAD,
                     parent="u1"),
    ]
    conv = _openai_conv(nodes, current_node="a1")
    # Write conv directly, not wrapped in a list
    p = _write_json(tmp_path, conv)
    docs = ingest_path(str(p))
    assert len(docs) == 1
    assert docs[0]["metadata"]["source"] == "openai"


def test_dispatch_unknown_shape_returns_empty(tmp_path: Path) -> None:
    """A .json that isn't a recognised chat export must return [] (not crash
    and not fall through to plaintext, which would chunk the JSON string)."""
    p = _write_json(tmp_path, {"random": "object", "with": ["arbitrary", "shape"]})
    assert ingest_path(str(p)) == []


def test_dispatch_invalid_json_returns_empty(tmp_path: Path) -> None:
    p = tmp_path / "broken.json"
    p.write_text("{not valid json", encoding="utf-8")
    assert ingest_path(str(p)) == []
