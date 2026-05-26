"""Tests for PodcastPost.

Pure unit tests -- no HTTP, no mocks. Mirrors the style of test_post.py:
pytest classes, scenario-named methods, bare assert, section banners.
Helpers at the top.
"""

import json

import pytest

from substack.exceptions import SectionNotExistsException
from substack.podcast import PodcastPost


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def make_podcast(**overrides):
    """Construct a PodcastPost with sensible defaults; overrides win."""
    kwargs = {"title": "Test Episode", "subtitle": "Test Sub", "user_id": 1}
    kwargs.update(overrides)
    return PodcastPost(**kwargs)


def get_draft_dict(podcast):
    """get_draft() with both ProseMirror fields decoded back to dicts."""
    out = podcast.get_draft()
    if isinstance(out.get("draft_body"), str):
        out["draft_body"] = json.loads(out["draft_body"])
    if isinstance(out.get("podcast_description"), str):
        out["podcast_description"] = json.loads(out["podcast_description"])
    return out


# ---------------------------------------------------------------------------
# TestPodcastPostConstruction
# ---------------------------------------------------------------------------


class TestPodcastPostConstruction:
    def test_stores_title_and_subtitle(self):
        pod = make_podcast(title="Episode 1", subtitle="The pilot")
        assert pod.draft_title == "Episode 1"
        assert pod.draft_subtitle == "The pilot"

    def test_coerces_user_id_to_int_in_bylines(self):
        pod = make_podcast(user_id="42")
        assert pod.draft_bylines == [{"id": 42, "is_guest": False}]

    def test_defaults_audience_to_everyone(self):
        pod = make_podcast()
        assert pod.audience == "everyone"

    def test_respects_explicit_audience(self):
        pod = make_podcast(audience="only_paid")
        assert pod.audience == "only_paid"

    def test_write_comment_permissions_defaults_to_audience(self):
        pod = make_podcast(audience="only_paid")
        assert pod.write_comment_permissions == "only_paid"

    def test_write_comment_permissions_respects_override(self):
        pod = make_podcast(audience="only_paid", write_comment_permissions="everyone")
        assert pod.write_comment_permissions == "everyone"

    def test_type_is_podcast(self):
        pod = make_podcast()
        assert pod.type == "podcast"

    def test_section_chosen_defaults_true(self):
        pod = make_podcast()
        assert pod.section_chosen is True

    def test_draft_section_id_starts_none(self):
        pod = make_podcast()
        assert pod.draft_section_id is None

    def test_draft_body_starts_empty_prosemirror_doc(self):
        pod = make_podcast()
        assert pod.draft_body == {"type": "doc", "content": []}

    def test_podcast_description_starts_empty_prosemirror_doc(self):
        pod = make_podcast()
        assert pod.podcast_description == {"type": "doc", "content": []}

    def test_draft_body_and_podcast_description_are_distinct_objects(self):
        """Mutating one must not affect the other."""
        pod = make_podcast()
        pod.draft_body["content"].append({"type": "paragraph"})
        assert pod.podcast_description == {"type": "doc", "content": []}

    def test_audio_fields_start_none(self):
        pod = make_podcast()
        assert pod.draft_podcast_upload_id is None
        assert pod.draft_podcast_url is None
        assert pod.draft_podcast_duration is None

    def test_last_updated_at_starts_none(self):
        pod = make_podcast()
        assert pod.last_updated_at is None


# ---------------------------------------------------------------------------
# TestGetDraftSerialization
# ---------------------------------------------------------------------------


class TestGetDraftSerialization:
    def test_draft_body_serialized_as_json_string(self):
        pod = make_podcast()
        out = pod.get_draft()
        assert isinstance(out["draft_body"], str)
        # Parses back to the empty doc shape.
        assert json.loads(out["draft_body"]) == {"type": "doc", "content": []}

    def test_podcast_description_serialized_as_json_string(self):
        pod = make_podcast()
        out = pod.get_draft()
        assert isinstance(out["podcast_description"], str)
        assert json.loads(out["podcast_description"]) == {"type": "doc", "content": []}

    def test_includes_type_podcast(self):
        out = make_podcast().get_draft()
        assert out["type"] == "podcast"

    def test_includes_title_subtitle_audience(self):
        pod = make_podcast(title="X", subtitle="Y", audience="founding")
        out = pod.get_draft()
        assert out["draft_title"] == "X"
        assert out["draft_subtitle"] == "Y"
        assert out["audience"] == "founding"

    def test_includes_bylines(self):
        out = make_podcast(user_id=99).get_draft()
        assert out["draft_bylines"] == [{"id": 99, "is_guest": False}]

    def test_includes_section_chosen_and_section_id(self):
        pod = make_podcast()
        pod.draft_section_id = 12345
        out = pod.get_draft()
        assert out["section_chosen"] is True
        assert out["draft_section_id"] == 12345

    def test_includes_podcast_audio_fields(self):
        pod = make_podcast()
        pod.draft_podcast_upload_id = "uuid-1"
        pod.draft_podcast_duration = 123.45
        out = pod.get_draft()
        assert out["draft_podcast_upload_id"] == "uuid-1"
        assert out["draft_podcast_duration"] == 123.45
        # draft_podcast_url starts None and the field should still be present.
        assert "draft_podcast_url" in out
        assert out["draft_podcast_url"] is None

    def test_omits_last_updated_at_when_none(self):
        pod = make_podcast()
        out = pod.get_draft()
        assert "last_updated_at" not in out

    def test_includes_last_updated_at_when_set(self):
        pod = make_podcast()
        pod.last_updated_at = "2026-05-26T04:52:01.886Z"
        out = pod.get_draft()
        assert out["last_updated_at"] == "2026-05-26T04:52:01.886Z"

    def test_get_draft_is_non_destructive(self):
        """Calling get_draft must not mutate self.

        Post has a known footgun where get_draft replaces self.draft_body with
        a JSON string in place. PodcastPost is designed for multi-step flows
        (create -> PUT updates) and must support repeated get_draft calls.
        """
        pod = make_podcast()
        first = pod.get_draft()
        second = pod.get_draft()
        # Both calls yield the same shape.
        assert isinstance(first["draft_body"], str)
        assert isinstance(second["draft_body"], str)
        # And self.draft_body remains a dict (not a string).
        assert isinstance(pod.draft_body, dict)
        assert pod.draft_body == {"type": "doc", "content": []}
        assert isinstance(pod.podcast_description, dict)


# ---------------------------------------------------------------------------
# TestSetBodyFromMarkdown
# ---------------------------------------------------------------------------


class TestSetBodyFromMarkdown:
    def test_returns_self_for_chaining(self):
        pod = make_podcast()
        assert pod.set_body_from_markdown("hello") is pod

    def test_populates_draft_body_with_prosemirror_paragraph(self):
        pod = make_podcast()
        pod.set_body_from_markdown("hello world")
        # First content node should be a paragraph carrying the text.
        body = pod.draft_body
        assert body["type"] == "doc"
        assert body["content"][0]["type"] == "paragraph"
        # Text node carries the literal.
        assert body["content"][0]["content"][0]["text"] == "hello world"

    def test_supports_inline_formatting_via_post_parser(self):
        pod = make_podcast()
        pod.set_body_from_markdown("This is **bold**.")
        body = pod.draft_body
        marks = [
            mark
            for node in body["content"][0].get("content", [])
            for mark in node.get("marks", [])
        ]
        assert {"type": "strong"} in marks

    def test_does_not_modify_podcast_description(self):
        pod = make_podcast()
        pod.set_body_from_markdown("body text")
        assert pod.podcast_description == {"type": "doc", "content": []}

    def test_replaces_prior_body(self):
        """Calling twice replaces, not appends."""
        pod = make_podcast()
        pod.set_body_from_markdown("first")
        pod.set_body_from_markdown("second")
        # Only one paragraph remains; it contains 'second'.
        paragraphs = [
            n for n in pod.draft_body["content"] if n["type"] == "paragraph"
        ]
        assert len(paragraphs) == 1
        assert paragraphs[0]["content"][0]["text"] == "second"


# ---------------------------------------------------------------------------
# TestSetShowNotesFromMarkdown
# ---------------------------------------------------------------------------


class TestSetShowNotesFromMarkdown:
    def test_returns_self_for_chaining(self):
        pod = make_podcast()
        assert pod.set_show_notes_from_markdown("notes") is pod

    def test_populates_podcast_description_with_prosemirror(self):
        pod = make_podcast()
        pod.set_show_notes_from_markdown("show notes paragraph")
        desc = pod.podcast_description
        assert desc["type"] == "doc"
        assert desc["content"][0]["type"] == "paragraph"
        assert desc["content"][0]["content"][0]["text"] == "show notes paragraph"

    def test_does_not_modify_draft_body(self):
        pod = make_podcast()
        pod.set_show_notes_from_markdown("notes only")
        assert pod.draft_body == {"type": "doc", "content": []}

    def test_show_notes_supports_links_and_headings(self):
        pod = make_podcast()
        pod.set_show_notes_from_markdown(
            "# Topics\n\nSee [example](https://example.com)"
        )
        desc = pod.podcast_description
        types = [n["type"] for n in desc["content"]]
        assert "heading" in types
        # The link mark surfaces somewhere in the doc.
        link_marks = [
            m
            for n in desc["content"]
            for child in n.get("content", []) or []
            for m in (child.get("marks") or [] if isinstance(child, dict) else [])
            if m.get("type") == "link"
        ]
        assert link_marks, "expected at least one link mark in show notes"

    def test_both_docs_serialized_independently(self):
        pod = make_podcast()
        pod.set_body_from_markdown("body text")
        pod.set_show_notes_from_markdown("show notes")
        out = pod.get_draft()
        body = json.loads(out["draft_body"])
        desc = json.loads(out["podcast_description"])
        assert body["content"][0]["content"][0]["text"] == "body text"
        assert desc["content"][0]["content"][0]["text"] == "show notes"


# ---------------------------------------------------------------------------
# TestSetAudio
# ---------------------------------------------------------------------------


class TestSetAudio:
    def test_returns_self_for_chaining(self):
        pod = make_podcast()
        assert pod.set_audio("uuid-x") is pod

    def test_sets_upload_id(self):
        pod = make_podcast()
        pod.set_audio("uuid-x")
        assert pod.draft_podcast_upload_id == "uuid-x"

    def test_sets_duration_when_provided(self):
        pod = make_podcast()
        pod.set_audio("uuid-x", duration_seconds=42.5)
        assert pod.draft_podcast_duration == 42.5

    def test_omitting_duration_leaves_it_none(self):
        pod = make_podcast()
        pod.set_audio("uuid-x")
        assert pod.draft_podcast_duration is None

    def test_upload_id_round_trips_through_get_draft(self):
        pod = make_podcast()
        pod.set_audio("uuid-x", duration_seconds=60)
        out = pod.get_draft()
        assert out["draft_podcast_upload_id"] == "uuid-x"
        assert out["draft_podcast_duration"] == 60


# ---------------------------------------------------------------------------
# TestSetSection
# ---------------------------------------------------------------------------


class TestSetSection:
    SECTIONS = [
        {"id": 100, "name": "Interviews"},
        {"id": 200, "name": "Solo"},
    ]

    def test_sets_draft_section_id(self):
        pod = make_podcast()
        pod.set_section("Solo", self.SECTIONS)
        assert pod.draft_section_id == 200

    def test_returns_self_for_chaining(self):
        pod = make_podcast()
        assert pod.set_section("Solo", self.SECTIONS) is pod

    def test_raises_section_not_exists_on_unknown(self):
        pod = make_podcast()
        with pytest.raises(SectionNotExistsException):
            pod.set_section("Nonexistent", self.SECTIONS)


# ---------------------------------------------------------------------------
# TestLastUpdatedAtThreading
# ---------------------------------------------------------------------------


class TestLastUpdatedAtThreading:
    """The field exists so callers can echo the server's draft_updated_at on
    subsequent PUTs. See docs/PODCAST_ARCHITECTURE.md section 7."""

    def test_initially_omitted_from_get_draft(self):
        out = make_podcast().get_draft()
        assert "last_updated_at" not in out

    def test_appears_in_get_draft_once_set(self):
        pod = make_podcast()
        pod.last_updated_at = "2026-05-26T04:52:01.886Z"
        out = pod.get_draft()
        assert out["last_updated_at"] == "2026-05-26T04:52:01.886Z"

    def test_can_be_cleared_back_to_none(self):
        pod = make_podcast()
        pod.last_updated_at = "2026-05-26T04:52:01.886Z"
        pod.last_updated_at = None
        out = pod.get_draft()
        assert "last_updated_at" not in out

    def test_repeated_get_drafts_remain_consistent(self):
        pod = make_podcast()
        pod.last_updated_at = "2026-05-26T04:52:01.886Z"
        first = pod.get_draft()
        second = pod.get_draft()
        assert first["last_updated_at"] == second["last_updated_at"]
        assert first["draft_body"] == second["draft_body"]


# ---------------------------------------------------------------------------
# TestFluentChaining
# ---------------------------------------------------------------------------


class TestFluentChaining:
    def test_chain_body_show_notes_audio(self):
        pod = (
            make_podcast()
            .set_body_from_markdown("body")
            .set_show_notes_from_markdown("notes")
            .set_audio("uuid-x", duration_seconds=10)
        )
        out = get_draft_dict(pod)
        assert out["draft_body"]["content"][0]["content"][0]["text"] == "body"
        assert out["podcast_description"]["content"][0]["content"][0]["text"] == "notes"
        assert out["draft_podcast_upload_id"] == "uuid-x"
        assert out["draft_podcast_duration"] == 10
