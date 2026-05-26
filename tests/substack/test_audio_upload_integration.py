"""Integration test for Api.upload_podcast_audio against a real Substack sandbox.

Gated on the environment variable RUN_INTEGRATION_TESTS=1. Also marked with
the `integration` pytest marker so the default `pytest` run (or any run with
`-m "not integration"`) skips it.

Requires .env in the project root with COOKIES_STRING and PUBLICATION_URL
(or EMAIL/PASSWORD). Creates a temporary podcast draft, uploads a tiny
fixture MP3, asserts the media object reaches `state == "transcoded"` with a
non-zero duration, and deletes the draft in a finally block so cleanup
happens even if assertions fail.
"""

from __future__ import annotations

import os
import time
from pathlib import Path

import pytest
from dotenv import load_dotenv

from substack.api import Api

REPO = Path(__file__).resolve().parents[2]
load_dotenv(REPO / ".env")


pytestmark = [
    pytest.mark.integration,
    pytest.mark.skipif(
        os.getenv("RUN_INTEGRATION_TESTS") != "1",
        reason="set RUN_INTEGRATION_TESTS=1 to run integration tests",
    ),
]


def _build_api() -> Api:
    """Build an Api client from .env credentials, preferring cookies."""
    cookies_path = os.getenv("COOKIES_PATH")
    cookies_string = os.getenv("COOKIES_STRING")
    publication_url = os.getenv("PUBLICATION_URL")
    if cookies_path or cookies_string:
        return Api(
            cookies_path=cookies_path,
            cookies_string=cookies_string,
            publication_url=publication_url,
        )
    return Api(
        email=os.getenv("EMAIL"),
        password=os.getenv("PASSWORD"),
        publication_url=publication_url,
    )


def test_upload_real_mp3_to_sandbox(tiny_mp3_path, capsys):
    """Create a podcast draft, upload a tiny MP3, verify transcoded, cleanup."""
    api = _build_api()
    user_id = api.get_user_id()

    # Create a minimal podcast draft to give the upload a post_id to attach to.
    draft = api.post_draft({
        "draft_title": "",
        "draft_subtitle": "",
        "draft_podcast_url": None,
        "draft_podcast_duration": None,
        "draft_body": '{"type":"doc","content":[{"type":"paragraph"}]}',
        "section_chosen": True,
        "draft_bylines": [{"id": int(user_id), "is_guest": False}],
        "audience": "everyone",
        "type": "podcast",
    })
    draft_id = draft["id"]

    started_at = time.monotonic()
    try:
        media = api.upload_podcast_audio(
            file_path=str(tiny_mp3_path),
            draft_id=draft_id,
            poll_timeout_seconds=120,
            poll_interval_seconds=2,
        )
        elapsed = time.monotonic() - started_at

        # Surface a useful one-line report regardless of pass/fail.
        print(
            f"\n[integration] draft_id={draft_id} upload_id={media.get('id')} "
            f"state={media.get('state')!r} duration={media.get('duration')} "
            f"transcoded_size={media.get('primary_file_size')} "
            f"elapsed={elapsed:.2f}s"
        )

        assert media["state"] == "transcoded"
        assert media["duration"] is not None and media["duration"] > 0
        # The fixture is 2s of silence; allow a wide tolerance for encoder padding
        # and any server-side re-encode that nudges the duration slightly.
        assert 1.5 < media["duration"] < 3.5
    finally:
        api.delete_draft(draft_id)
