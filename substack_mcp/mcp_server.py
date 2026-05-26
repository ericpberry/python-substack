from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

try:
    from dotenv import load_dotenv
except ImportError:
    load_dotenv = None

from mcp.server.fastmcp import FastMCP

from substack.api import Api
from substack.podcast import PodcastPost
from substack.post import Post

if load_dotenv is not None:
    load_dotenv()


def get_api() -> Api:
    email = os.getenv("EMAIL")
    password = os.getenv("PASSWORD")
    cookies_path = os.getenv("COOKIES_PATH")
    cookies_string = os.getenv("COOKIES_STRING")
    publication_url = os.getenv("PUBLICATION_URL")

    if cookies_path or cookies_string:
        return Api(
            cookies_path=cookies_path,
            cookies_string=cookies_string,
            publication_url=publication_url,
        )

    if email and password:
        return Api(
            email=email,
            password=password,
            publication_url=publication_url,
        )

    raise ValueError(
        "Missing Substack auth configuration: set EMAIL/PASSWORD or COOKIES_PATH/COOKIES_STRING"
    )


def _normalize_tags(tags: Optional[Any]) -> List[str]:
    if tags is None:
        return []
    if isinstance(tags, str):
        return [tags]
    if isinstance(tags, list):
        return [str(tag) for tag in tags]
    raise ValueError("tags must be a string or a list of strings")


mcp = FastMCP("substack")


@mcp.tool()
async def post_draft_from_markdown(
    title: str,
    markdown: str,
    subtitle: Optional[str] = "",
    audience: str = "everyone",
    write_comment_permissions: str = "everyone",
    search_engine_title: Optional[str] = None,
    search_engine_description: Optional[str] = None,
    slug: Optional[str] = None,
    draft_section_id: Optional[int] = None,
    tags: Optional[Any] = None,
    prepublish: bool = False,
    publish: bool = False,
    send: bool = True,
    share_automatically: bool = False,
) -> Dict[str, Any]:
    """Create or update a Substack draft from Markdown.

    This tool builds a Substack `Post` from markdown content and posts a draft.
    It supports optional tag assignment, prepublish (setup check), and publishing.

    Args:
        title: Draft title.
        markdown: Markdown body content.
        subtitle: Optional subtitle text.
        audience: One of `everyone`, `only_paid`, `founding`, `only_free`.
        write_comment_permissions: One of `none`, `only_paid`, `everyone`.
        search_engine_title: Optional title for search engine optimization.
        search_engine_description: Optional description for search engine optimization.
        slug: Optional URL slug for the post.
        draft_section_id: Optional section ID for the draft.
        tags: Tag or list of tags to attach to the post.
        prepublish: If true, calls `prepublish_draft` after creation.
        publish: If true, calls `publish_draft` after creation (and optionally prepublish).
        send: Passed to `publish_draft` for newsletter delivery.
        share_automatically: Passed to `publish_draft`.

    Returns:
        dict containing drafted post (`draft`), optional `tags`, `prepublish`, `publish` results.

    Examples:
        With the YAML structure from the README, a caller can map fields like:

        ```yaml
        title: "My Post Title"
        subtitle: "My Post Subtitle"
        audience: "everyone"
        write_comment_permissions: "everyone"
        markdown: |
          # Hello

          This is the body.

        tags:
          - python
          - substack
        prepublish: true
        publish: true
        send: false
        share_automatically: true
        ```

        Then invoke via MCP directly:

        ```python
        from substack_mcp.mcp_server import post_draft_from_markdown

        result = await post_draft_from_markdown(
            title='My Post Title',
            markdown='# Hello\n\nThis is the body.',
            subtitle='My Post Subtitle',
            audience='everyone',
            write_comment_permissions='everyone',
            tags=['python', 'substack'],
            prepublish=True,
            publish=False,  # set true when ready
        )
        print(result)
        ```

        A longer process with manual prepublish/publish calls:

        ```python
        from substack_mcp.mcp_server import (
            post_draft_from_markdown,
            prepublish_draft,
            publish_draft,
            add_tags,
        )

        d = await post_draft_from_markdown(
            title='Long flow',
            markdown='Content',
            tags=['a','b'],
            publish=False,
        )
        draft_id = d['draft']['id']

        await add_tags(draft_id, ['post-tag', 'news'])
        await prepublish_draft(draft_id)
        await publish_draft(draft_id, send=True, share_automatically=True)
        ```

        This docstring example is meant to mirror the YAML-driven workflow and show how to decompose the same operations into explicit tool calls.
    """
    client = get_api()
    user_id = client.get_user_id()

    post = Post(
        title=title,
        subtitle=subtitle or "",
        user_id=user_id,
        audience=audience,
        write_comment_permissions=write_comment_permissions,
    )

    post.from_markdown(markdown, api=client)

    draft = client.post_draft(post.get_draft())

    update_payload: Dict[str, Any] = {}
    if search_engine_title:
        update_payload["search_engine_title"] = search_engine_title
    if search_engine_description:
        update_payload["search_engine_description"] = search_engine_description
    if slug:
        update_payload["slug"] = slug
    if draft_section_id is not None:
        update_payload["draft_section_id"] = draft_section_id

    if update_payload:
        draft = client.put_draft(draft.get("id"), **update_payload)

    tags_list = _normalize_tags(tags)
    tags_result = None
    if tags_list:
        tags_result = client.add_tags_to_post(draft.get("id"), tags_list)

    prepublish_result = None
    if prepublish:
        prepublish_result = client.prepublish_draft(draft.get("id"))

    publish_result = None
    if publish:
        publish_result = client.publish_draft(
            draft.get("id"), send=send, share_automatically=share_automatically
        )

    return {
        "draft": draft,
        "tags": tags_result,
        "prepublish": prepublish_result,
        "publish": publish_result,
    }


@mcp.tool()
async def put_draft(
    draft_id: int,
    update_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Update an existing draft by draft ID.

    Args:
        draft_id: target draft identifier.
        update_payload: dict of fields supported by Substack `put_draft` (e.g. `slug`, `draft_section_id`).

    Returns:
        API response dict for the updated draft.
    """
    client = get_api()
    return client.put_draft(draft_id, **update_payload)


@mcp.tool()
async def add_tags(draft_id: int, tags: Any) -> Dict[str, Any]:
    """Add tags to a specific draft/post.

    Args:
        draft_id: target draft identifier.
        tags: string or list of tag names (e.g. `"tech"` or `["tech", "python"]`).

    Returns:
        Response from `add_tags_to_post` (tag IDs + names).
    """
    client = get_api()
    tags_list = _normalize_tags(tags)
    if not tags_list:
        raise ValueError("tags is required and cannot be empty")
    return client.add_tags_to_post(draft_id, tags_list)


@mcp.tool()
async def prepublish_draft(draft_id: int) -> Dict[str, Any]:
    """Invoke prepublish checks for a draft.

    Args:
        draft_id: target draft identifier.

    Returns:
        Prepublish response dict from Substack API.
    """
    client = get_api()
    return client.prepublish_draft(draft_id)


@mcp.tool()
async def publish_draft(
    draft_id: int,
    send: bool = True,
    share_automatically: bool = False,
) -> Dict[str, Any]:
    """Publish a draft to live post state.

    Args:
        draft_id: target draft identifier.
        send: if False then do not send email to subscribers.
        share_automatically: whether to auto-share (e.g. social propagation).

    Returns:
        Response from Substack `publish_draft`.
    """
    client = get_api()
    return client.publish_draft(
        draft_id, send=send, share_automatically=share_automatically
    )


@mcp.tool()
async def upload_podcast_audio(
    file_path: str,
    draft_id: int,
) -> Dict[str, Any]:
    """Upload a podcast audio file (typically an MP3) and wait for transcoding.

    Performs the full Substack upload sequence: initiate, PUT raw bytes to
    the pre-signed S3 URL(s), trigger transcode, and poll the media object
    until its state is ``"transcoded"``. Duration is computed locally via
    mutagen and sent with the transcode call.

    Args:
        file_path: Local path to the audio file on the machine running this
            MCP server.
        draft_id: ID of the podcast draft this audio is being attached to.
            Substack scopes the upload to a ``post_id`` at init time, so the
            draft must already exist.

    Returns:
        The final media object dict with ``state == "transcoded"``. The
        ``id`` field is the audio UUID; pass it as ``audio_upload_id`` /
        ``draft_podcast_upload_id`` to attach the audio to a draft.

    Examples:
        ```python
        from substack_mcp.mcp_server import (
            post_podcast_draft_from_markdown,
            upload_podcast_audio,
            put_draft,
        )

        # Create a podcast shell first so we have a draft_id to scope the
        # upload to.
        d = await post_podcast_draft_from_markdown(title='Episode 1')
        draft_id = d['draft']['id']

        media = await upload_podcast_audio(
            file_path='/abs/path/episode-01.mp3',
            draft_id=draft_id,
        )
        # media['id'] is the upload UUID; attach it to the draft:
        await put_draft(draft_id, {'draft_podcast_upload_id': media['id']})
        ```
    """
    client = get_api()
    return client.upload_podcast_audio(file_path=file_path, draft_id=draft_id)


@mcp.tool()
async def post_podcast_draft_from_markdown(
    title: str,
    subtitle: Optional[str] = "",
    show_notes_markdown: Optional[str] = None,
    post_body_markdown: Optional[str] = None,
    audio_file_path: Optional[str] = None,
    audience: str = "everyone",
    write_comment_permissions: Optional[str] = None,
    draft_section_id: Optional[int] = None,
    tags: Optional[Any] = None,
    prepublish: bool = False,
    publish: bool = False,
    send: bool = True,
    share_automatically: bool = False,
) -> Dict[str, Any]:
    """Create (and optionally publish) a Substack podcast draft end-to-end.

    Composes the full podcast publishing flow: build a ``PodcastPost`` from
    the supplied fields, create the draft, optionally upload + attach audio,
    optionally tag, optionally prepublish, optionally publish. Each step is
    independently opt-in and surfaced separately in the return value.

    Show notes (``podcast_description``) and the post-page body
    (``draft_body``) are two distinct ProseMirror documents on a podcast
    draft; both are independently optional.

    Args:
        title: Episode title.
        subtitle: Optional subtitle.
        show_notes_markdown: Markdown for the show notes
            (``podcast_description``). Renders alongside the audio player.
        post_body_markdown: Markdown for the post-page body (``draft_body``).
            Same field a newsletter post uses.
        audio_file_path: Local path to the episode audio file (MP3). When
            provided, the audio is uploaded via :func:`upload_podcast_audio`
            and attached to the draft.
        audience: One of ``everyone``, ``only_paid``, ``founding``, ``only_free``.
        write_comment_permissions: One of ``none``, ``only_paid``, ``everyone``.
            Defaults to ``audience`` when omitted.
        draft_section_id: Optional section ID.
        tags: Tag or list of tags to attach to the post.
        prepublish: If true, calls ``prepublish_draft`` (server-side validation).
        publish: If true, calls ``publish_draft``.
        send: Passed to ``publish_draft`` -- newsletter email delivery on
            publish. Ignored when ``publish`` is false.
        share_automatically: Passed to ``publish_draft``. Substack's podcast
            publish endpoint ignores this key, but it is included for
            symmetry with :func:`post_draft_from_markdown`.

    Returns:
        Dict with one key per composed step:

          * ``draft``: latest draft / post object (post-PUT if audio attached,
            otherwise the create response; not replaced by the publish response).
          * ``upload``: transcoded media object, or ``None`` if no audio uploaded.
          * ``tags``: result of ``add_tags_to_post``, or ``None`` if no tags.
          * ``prepublish``: result of ``prepublish_draft``, or ``None`` if skipped.
          * ``publish``: result of ``publish_draft``, or ``None`` if skipped.

    Examples:
        Minimal draft, no audio, stop at draft stage:

        ```python
        from substack_mcp.mcp_server import post_podcast_draft_from_markdown

        result = await post_podcast_draft_from_markdown(
            title='Pilot episode',
            subtitle='Where it all begins',
            show_notes_markdown='## Topics\\n\\n- Topic one\\n- Topic two',
        )
        draft_id = result['draft']['id']
        ```

        Full end-to-end publish (no email, safe for sandbox):

        ```python
        result = await post_podcast_draft_from_markdown(
            title='Episode 7: Async I/O',
            subtitle='What asyncio buys you, and what it costs',
            show_notes_markdown='## Show notes\\n\\n- Event loops\\n- Backpressure',
            post_body_markdown='Full episode text mirror for the post page.',
            audio_file_path='/abs/path/episode-07.mp3',
            tags=['python', 'async'],
            prepublish=True,
            publish=True,
            send=False,
        )
        assert result['publish']['is_published']
        ```
    """
    client = get_api()
    user_id = client.get_user_id()

    pod = PodcastPost(
        title=title,
        subtitle=subtitle or "",
        user_id=user_id,
        audience=audience,
        write_comment_permissions=write_comment_permissions,
    )

    if show_notes_markdown:
        pod.set_show_notes_from_markdown(show_notes_markdown, api=client)
    if post_body_markdown:
        pod.set_body_from_markdown(post_body_markdown, api=client)
    if draft_section_id is not None:
        pod.draft_section_id = draft_section_id

    draft = client.post_draft(pod.get_draft())
    draft_id = draft["id"]

    upload_result: Optional[Dict[str, Any]] = None
    if audio_file_path:
        upload_result = client.upload_podcast_audio(
            file_path=audio_file_path, draft_id=draft_id
        )
        pod.set_audio(
            upload_result["id"], duration_seconds=upload_result.get("duration")
        )
        pod.last_updated_at = draft.get("draft_updated_at")
        draft = client.put_draft(draft_id, **pod.get_draft())

    tags_list = _normalize_tags(tags)
    tags_result = None
    if tags_list:
        tags_result = client.add_tags_to_post(draft_id, tags_list)

    prepublish_result = None
    if prepublish:
        prepublish_result = client.prepublish_draft(draft_id)

    publish_result = None
    if publish:
        publish_result = client.publish_draft(
            draft_id, send=send, share_automatically=share_automatically
        )

    return {
        "draft": draft,
        "upload": upload_result,
        "tags": tags_result,
        "prepublish": prepublish_result,
        "publish": publish_result,
    }


def main() -> None:
    mcp.run(transport="stdio")


if __name__ == "__main__":
    main()
