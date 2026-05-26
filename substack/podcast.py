"""

Podcast Post Utilities

"""

import json

__all__ = ["PodcastPost"]

from substack.exceptions import SectionNotExistsException
from substack.post import Post


class PodcastPost:
    """

    In-memory state for a Substack podcast draft.

    A podcast draft carries two distinct ProseMirror documents:

      * ``draft_body`` -- the post-page body (same field a newsletter Post uses).
      * ``podcast_description`` -- the show notes shown alongside the audio
        player.

    Both are kept as Python dicts internally and JSON-encoded by
    :meth:`get_draft`. Both are independently optional.

    Like :class:`substack.post.Post`, ``vars(self)`` is the serialization
    layer: every public attribute name matches the Substack API field name
    exactly. Unlike ``Post``, :meth:`get_draft` is non-destructive (it
    shallow-copies the instance dict before encoding) so the same instance
    can be reused across the create / PUT-updates / publish lifecycle.

    """

    def __init__(
        self,
        title: str,
        subtitle: str,
        user_id,
        audience: str = None,
        write_comment_permissions: str = None,
    ):
        """

        Args:
            title:
            subtitle:
            user_id:
            audience: possible values: everyone, only_paid, founding, only_free
            write_comment_permissions: none, only_paid, everyone
        """
        # Fields shared with a newsletter draft.
        self.draft_title = title
        self.draft_subtitle = subtitle
        self.draft_body = {"type": "doc", "content": []}
        self.draft_bylines = [{"id": int(user_id), "is_guest": False}]
        self.audience = audience if audience is not None else "everyone"
        self.draft_section_id = None
        self.section_chosen = True

        if write_comment_permissions is not None:
            self.write_comment_permissions = write_comment_permissions
        else:
            self.write_comment_permissions = self.audience

        # Podcast-only fields. Names match the Substack API exactly.
        self.type = "podcast"
        self.draft_podcast_upload_id = None
        self.draft_podcast_url = None
        self.draft_podcast_duration = None
        self.podcast_description = {"type": "doc", "content": []}

        # Optimistic-concurrency token. None on first create; callers should
        # set it from the previous draft response's ``draft_updated_at`` before
        # each subsequent PUT. See docs/PODCAST_ARCHITECTURE.md section 7.
        self.last_updated_at = None

    def set_section(self, name: str, sections: list):
        """

        Look up a section by name and store its id as ``draft_section_id``.

        Args:
            name: Section name as configured on the publication.
            sections: List of section dicts as returned by
                :meth:`substack.api.Api.get_sections`.

        Returns:
            Self for method chaining.
        """
        section = [s for s in sections if s.get("name") == name]
        if len(section) != 1:
            raise SectionNotExistsException(name)
        self.draft_section_id = section[0].get("id")
        return self

    def set_audio(self, upload_id: str, duration_seconds: float = None):
        """

        Attach a previously-uploaded audio file to the draft.

        Args:
            upload_id: The audio UUID returned by
                :meth:`substack.api.Api.upload_podcast_audio` (the
                ``id`` field of the transcoded media object).
            duration_seconds: Optional. When provided, stored as
                ``draft_podcast_duration``. Substack's player can derive
                duration from the transcoded media, so this is informational.

        Returns:
            Self for method chaining.
        """
        self.draft_podcast_upload_id = upload_id
        if duration_seconds is not None:
            self.draft_podcast_duration = duration_seconds
        return self

    def set_body_from_markdown(self, markdown: str, api=None):
        """

        Replace the post-page body with Markdown parsed into ProseMirror.

        Internally constructs a throwaway :class:`substack.post.Post`, runs
        its :meth:`~substack.post.Post.from_markdown`, then steals the
        resulting ``draft_body`` dict. Any prior body content is replaced.

        Args:
            markdown: Markdown source for the post-page body.
            api: Optional :class:`substack.api.Api` instance. Forwarded to
                ``Post.from_markdown`` so any local image paths referenced
                in the Markdown are uploaded via ``api.get_image`` and
                rewritten to their CDN URLs.

        Returns:
            Self for method chaining.
        """
        tmp = Post(title="", subtitle="", user_id=self.draft_bylines[0]["id"])
        tmp.from_markdown(markdown, api=api)
        self.draft_body = tmp.draft_body
        return self

    def set_show_notes_from_markdown(self, markdown: str, api=None):
        """

        Replace the show notes (``podcast_description``) with Markdown
        parsed into ProseMirror.

        Internally constructs a throwaway :class:`substack.post.Post`, runs
        its :meth:`~substack.post.Post.from_markdown`, then steals the
        resulting ``draft_body`` dict into ``podcast_description``. Any
        prior show notes are replaced.

        Args:
            markdown: Markdown source for the show notes.
            api: Optional :class:`substack.api.Api` instance. Forwarded to
                ``Post.from_markdown`` so any local image paths referenced
                in the Markdown are uploaded via ``api.get_image`` and
                rewritten to their CDN URLs.

        Returns:
            Self for method chaining.
        """
        tmp = Post(title="", subtitle="", user_id=self.draft_bylines[0]["id"])
        tmp.from_markdown(markdown, api=api)
        self.podcast_description = tmp.draft_body
        return self

    def get_draft(self) -> dict:
        """

        Return the draft payload as a JSON-ready dict.

        Both ProseMirror docs (``draft_body`` and ``podcast_description``)
        are JSON-encoded to strings, matching the wire format Substack
        expects. ``last_updated_at`` is omitted when None (the create call
        must not carry the field; PUTs after the first response should).

        Unlike :meth:`substack.post.Post.get_draft`, this method does not
        mutate ``self``. It returns a shallow copy of ``vars(self)`` so the
        same instance can be reused across create / PUT / publish.

        Returns:
            dict ready to pass to :meth:`substack.api.Api.post_draft` or to
            splat into :meth:`substack.api.Api.put_draft` as kwargs.
        """
        out = dict(vars(self))
        out["draft_body"] = json.dumps(out["draft_body"])
        out["podcast_description"] = json.dumps(out["podcast_description"])
        if out.get("last_updated_at") is None:
            out.pop("last_updated_at", None)
        return out
