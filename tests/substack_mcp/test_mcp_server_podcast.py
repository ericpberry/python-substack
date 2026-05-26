"""Tests for the podcast MCP tools.

Like tests/substack/test_audio_upload.py, these tests deliberately depart
from the codebase's no-mock convention (STYLE.md section 5): MCP tool
composition is HTTP integration logic that can only be exercised by
mocking the Api layer.

Mocks target `substack_mcp.mcp_server.get_api` (replacing the entire Api
factory) and configure a MagicMock client whose methods return canned
responses. We let the real PodcastPost class run so assertions can read
the actual payload built into `pod.get_draft()`.
"""

import asyncio
import json
from unittest.mock import MagicMock, patch

import pytest

from substack_mcp.mcp_server import (
    post_podcast_draft_from_markdown,
    upload_podcast_audio,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_mock_api():
    """Construct a MagicMock Api whose draft / upload / publish methods
    return shape-faithful canned responses."""
    api = MagicMock()
    api.get_user_id.return_value = 253249334
    api.post_draft.return_value = {
        "id": 199290000,
        "type": "podcast",
        "draft_updated_at": "2026-05-26T10:00:00.000Z",
        "draft_title": "",
    }
    api.put_draft.return_value = {
        "id": 199290000,
        "type": "podcast",
        "draft_updated_at": "2026-05-26T10:00:05.000Z",
        "draft_podcast_upload_id": "uuid-attached",
    }
    api.upload_podcast_audio.return_value = {
        "id": "uuid-attached",
        "state": "transcoded",
        "duration": 600.0,
        "primary_file_size": 7000000,
    }
    api.add_tags_to_post.return_value = {"tags_added": [{"id": 1, "name": "x"}]}
    api.prepublish_draft.return_value = {"errors": [], "suggestions": []}
    api.publish_draft.return_value = {
        "id": 199290000,
        "is_published": True,
        "type": "podcast",
        "draft_podcast_upload_id": "uuid-attached",
    }
    return api


def run(coro):
    """Synchronously run an async tool function."""
    return asyncio.run(coro)


# ===========================================================================
# upload_podcast_audio (MCP wrapper)
# ===========================================================================


class TestUploadPodcastAudioTool:
    """Thin wrapper around Api.upload_podcast_audio."""

    def test_calls_api_with_passed_args(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(upload_podcast_audio(file_path="/tmp/test.mp3", draft_id=12345))
        api.upload_podcast_audio.assert_called_once_with(
            file_path="/tmp/test.mp3", draft_id=12345
        )

    def test_returns_api_result_verbatim(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(upload_podcast_audio(file_path="/tmp/test.mp3", draft_id=12345))
        assert result == api.upload_podcast_audio.return_value
        assert result["state"] == "transcoded"
        assert result["id"] == "uuid-attached"


# ===========================================================================
# post_podcast_draft_from_markdown -- PodcastPost construction
# ===========================================================================


class TestPodcastPostConstruction:
    """The tool builds a PodcastPost from kwargs and calls api.post_draft."""

    def test_post_draft_called_with_podcast_type(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="My Episode"))
        body = api.post_draft.call_args[0][0]
        assert body["type"] == "podcast"
        assert body["draft_title"] == "My Episode"

    def test_passes_subtitle_and_audience(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    subtitle="A subtitle",
                    audience="only_paid",
                )
            )
        body = api.post_draft.call_args[0][0]
        assert body["draft_subtitle"] == "A subtitle"
        assert body["audience"] == "only_paid"

    def test_write_comment_permissions_defaults_to_audience(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audience="founding",
                )
            )
        body = api.post_draft.call_args[0][0]
        assert body["write_comment_permissions"] == "founding"

    def test_write_comment_permissions_respects_explicit_value(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audience="founding",
                    write_comment_permissions="everyone",
                )
            )
        body = api.post_draft.call_args[0][0]
        assert body["write_comment_permissions"] == "everyone"

    def test_user_id_from_api(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        body = api.post_draft.call_args[0][0]
        assert body["draft_bylines"] == [{"id": 253249334, "is_guest": False}]

    def test_draft_section_id_passed_through(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep", draft_section_id=42))
        body = api.post_draft.call_args[0][0]
        assert body["draft_section_id"] == 42


# ===========================================================================
# post_podcast_draft_from_markdown -- two ProseMirror docs
# ===========================================================================


class TestTwoProseMirrorDocs:
    """Both show_notes_markdown and post_body_markdown are independently optional."""

    def test_both_omitted_yields_empty_docs(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        body = api.post_draft.call_args[0][0]
        assert json.loads(body["draft_body"]) == {"type": "doc", "content": []}
        assert json.loads(body["podcast_description"]) == {"type": "doc", "content": []}

    def test_show_notes_populates_podcast_description(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    show_notes_markdown="# Show notes\n\nA paragraph.",
                )
            )
        body = api.post_draft.call_args[0][0]
        desc = json.loads(body["podcast_description"])
        assert "Show notes" in json.dumps(desc)
        # And the body stays empty.
        assert json.loads(body["draft_body"]) == {"type": "doc", "content": []}

    def test_body_populates_draft_body(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    post_body_markdown="Body text here.",
                )
            )
        body = api.post_draft.call_args[0][0]
        draft_body = json.loads(body["draft_body"])
        assert "Body text here." in json.dumps(draft_body)
        # And the show notes stay empty.
        assert json.loads(body["podcast_description"]) == {"type": "doc", "content": []}

    def test_both_populated_independently(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    show_notes_markdown="show notes paragraph",
                    post_body_markdown="body paragraph",
                )
            )
        body = api.post_draft.call_args[0][0]
        desc = json.dumps(json.loads(body["podcast_description"]))
        body_doc = json.dumps(json.loads(body["draft_body"]))
        assert "show notes paragraph" in desc
        assert "body paragraph" in body_doc


# ===========================================================================
# post_podcast_draft_from_markdown -- audio attach flow
# ===========================================================================


class TestAudioAttach:
    """When audio_file_path is provided, the tool uploads + attaches via PUT."""

    def test_skips_audio_when_no_path(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        api.upload_podcast_audio.assert_not_called()
        api.put_draft.assert_not_called()

    def test_uploads_audio_with_created_draft_id(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        api.upload_podcast_audio.assert_called_once_with(
            file_path="/tmp/sample.mp3", draft_id=199290000
        )

    def test_put_draft_carries_audio_upload_id(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        put_kwargs = api.put_draft.call_args.kwargs
        assert put_kwargs["draft_podcast_upload_id"] == "uuid-attached"

    def test_put_draft_threads_last_updated_at_from_create(self):
        """Proof the optimistic-concurrency token from POST flows into PUT."""
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        put_kwargs = api.put_draft.call_args.kwargs
        assert put_kwargs["last_updated_at"] == "2026-05-26T10:00:00.000Z"

    def test_put_draft_targets_created_draft_id(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        # First positional arg is the draft id.
        assert api.put_draft.call_args.args[0] == 199290000


# ===========================================================================
# post_podcast_draft_from_markdown -- tags
# ===========================================================================


class TestTagsHandling:
    """Tags reuse the existing _normalize_tags helper + Api.add_tags_to_post."""

    def test_skips_tags_when_none(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        api.add_tags_to_post.assert_not_called()

    def test_string_tag_normalized_to_list(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep", tags="tech"))
        api.add_tags_to_post.assert_called_once_with(199290000, ["tech"])

    def test_list_tags_passed_through(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep", tags=["a", "b"]))
        api.add_tags_to_post.assert_called_once_with(199290000, ["a", "b"])


# ===========================================================================
# post_podcast_draft_from_markdown -- prepublish / publish gating
# ===========================================================================


class TestPrepublishAndPublishGating:
    """Both prepublish and publish are off by default; opt-in via flags."""

    def test_skips_prepublish_when_false(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        api.prepublish_draft.assert_not_called()

    def test_calls_prepublish_when_true(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep", prepublish=True))
        api.prepublish_draft.assert_called_once_with(199290000)

    def test_skips_publish_when_false(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep"))
        api.publish_draft.assert_not_called()

    def test_calls_publish_with_send_and_share_automatically(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    publish=True,
                    send=False,
                    share_automatically=True,
                )
            )
        api.publish_draft.assert_called_once_with(
            199290000, send=False, share_automatically=True
        )

    def test_publish_defaults_send_true_share_false(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(post_podcast_draft_from_markdown(title="Ep", publish=True))
        api.publish_draft.assert_called_once_with(
            199290000, send=True, share_automatically=False
        )


# ===========================================================================
# post_podcast_draft_from_markdown -- return shape
# ===========================================================================


class TestReturnShape:
    """Return dict surfaces each composed step so callers can inspect results."""

    def test_returns_dict_with_expected_keys(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(post_podcast_draft_from_markdown(title="Ep"))
        for key in ("draft", "upload", "tags", "prepublish", "publish"):
            assert key in result, f"missing key {key!r} in {result!r}"

    def test_no_audio_yields_upload_none(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(post_podcast_draft_from_markdown(title="Ep"))
        assert result["upload"] is None

    def test_with_audio_returns_transcoded_media(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        assert result["upload"]["state"] == "transcoded"
        assert result["upload"]["id"] == "uuid-attached"

    def test_no_tags_yields_tags_none(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(post_podcast_draft_from_markdown(title="Ep"))
        assert result["tags"] is None

    def test_with_tags_returns_tag_result(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(post_podcast_draft_from_markdown(title="Ep", tags=["x"]))
        assert result["tags"] == api.add_tags_to_post.return_value

    def test_draft_field_reflects_latest_state_after_audio_attach(self):
        """After PUT-attaching audio, the 'draft' key should hold the PUT result,
        not the original POST result."""
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/sample.mp3",
                )
            )
        # The PUT response has draft_podcast_upload_id; the POST response did not.
        assert result["draft"]["draft_podcast_upload_id"] == "uuid-attached"

    def test_prepublish_and_publish_results_in_return(self):
        api = make_mock_api()
        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            result = run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    prepublish=True,
                    publish=True,
                )
            )
        assert result["prepublish"] == {"errors": [], "suggestions": []}
        assert result["publish"]["is_published"] is True


# ===========================================================================
# post_podcast_draft_from_markdown -- call order
# ===========================================================================


class TestCallOrder:
    """The composition must follow create -> upload -> attach -> tags ->
    prepublish -> publish. Order matters because each step needs the previous
    step's id / token."""

    def test_full_flow_order(self):
        api = make_mock_api()
        # Record the sequence of method names called on api.
        order = []

        def record(name):
            orig = getattr(api, name)
            def wrapper(*a, **kw):
                order.append(name)
                return orig.return_value
            return wrapper

        api.post_draft.side_effect = lambda *a, **kw: (
            order.append("post_draft"), api.post_draft.return_value
        )[1]
        api.upload_podcast_audio.side_effect = lambda *a, **kw: (
            order.append("upload_podcast_audio"), api.upload_podcast_audio.return_value
        )[1]
        api.put_draft.side_effect = lambda *a, **kw: (
            order.append("put_draft"), api.put_draft.return_value
        )[1]
        api.add_tags_to_post.side_effect = lambda *a, **kw: (
            order.append("add_tags_to_post"), api.add_tags_to_post.return_value
        )[1]
        api.prepublish_draft.side_effect = lambda *a, **kw: (
            order.append("prepublish_draft"), api.prepublish_draft.return_value
        )[1]
        api.publish_draft.side_effect = lambda *a, **kw: (
            order.append("publish_draft"), api.publish_draft.return_value
        )[1]

        with patch("substack_mcp.mcp_server.get_api", return_value=api):
            run(
                post_podcast_draft_from_markdown(
                    title="Ep",
                    audio_file_path="/tmp/x.mp3",
                    tags=["t1"],
                    prepublish=True,
                    publish=True,
                )
            )

        assert order == [
            "post_draft",
            "upload_podcast_audio",
            "put_draft",
            "add_tags_to_post",
            "prepublish_draft",
            "publish_draft",
        ]
