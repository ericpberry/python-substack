"""Tests for Api.upload_podcast_audio.

Deliberate departure from the no-mock convention in STYLE.md §5: HTTP integration
logic for the multi-step audio upload (init -> S3 PUT -> transcode -> poll) cannot
be exercised without mocking the HTTP layer. Mocks target the underlying
`requests.Session` method calls (`post`, `put`, `get`) since `_handle_response`
inspects `response.json()` / `response.status_code` / `response.headers`.

All fixture payload shapes are derived from real HAR captures; see
docs/PODCAST_API_CONTRACT.md for the canonical wire-level reference.
"""

import json
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from substack.api import Api
from substack.exceptions import SubstackAPIException, SubstackRequestException


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

SAMPLES_DIR = Path(__file__).resolve().parents[2].parent / "samples"
SMALL_SAMPLE = SAMPLES_DIR / "sample-speech-10m.mp3"


def make_api():
    """Construct an Api instance without touching the network.

    Api.__init__ authenticates and fetches the publication; tests can't run
    through that. We bypass it via __new__ and set the minimum attributes the
    upload code path actually touches.
    """
    api = Api.__new__(Api)
    api._session = MagicMock()
    api.publication_url = "https://test.substack.com/api/v1"
    api.base_url = "https://substack.com/api/v1"
    return api


def fake_response(status=200, json_data=None, headers=None, text=""):
    """Build a MagicMock that quacks like requests.Response."""
    r = MagicMock()
    r.status_code = status
    r.ok = 200 <= status < 300
    r.headers = headers or {}
    r.text = text
    if json_data is None:
        r.json.side_effect = ValueError("no json")
    else:
        r.json.return_value = json_data
    return r


# Fixture payloads modeled after captures/substack_capture_small.har entries
# #12, #14, #15, #16, #19. UUIDs and IDs are made-up but shape-faithful.

DRAFT_ID = 199281706
AUDIO_UUID = "198f70da-d9b5-42d7-8241-8ea327b09101"
MULTIPART_UPLOAD_ID = "56fy3HuHONW7_f6sUFFYGq5A0Ez76Bw_test_multipart_upload_id"
S3_PUT_URL = (
    "https://substack-video.s3-accelerate.amazonaws.com/video_upload/post/"
    f"{DRAFT_ID}/{AUDIO_UUID}/original"
    "?X-Amz-Algorithm=AWS4-HMAC-SHA256&X-Amz-Signature=fake&partNumber=1"
    f"&uploadId={MULTIPART_UPLOAD_ID}"
)
S3_ETAG = '"bf25ca5cb165f948f3c26faef0fbedba"'

INIT_RESPONSE_BODY = {
    "mediaUpload": {
        "user_id": 253249334,
        "name": "sample-speech-10m.mp3",
        "publication_id": 9222054,
        "post_id": DRAFT_ID,
        "state": "created",
        "media_type": "audio",
        "is_mux": False,
        "primary_file_size": 9601402,
        "id": AUDIO_UUID,
        "parts": [],
        "multipart_upload_id": MULTIPART_UPLOAD_ID,
    },
    "multipartUploadId": MULTIPART_UPLOAD_ID,
    "multipartUploadUrls": [S3_PUT_URL],
}

TRANSCODE_RESPONSE_BODY = {
    "id": AUDIO_UUID,
    "name": "sample-speech-10m.mp3",
    "state": "uploaded",
    "post_id": DRAFT_ID,
    "duration": 600.058776,
    "media_type": "audio",
    "primary_file_size": 9601402,
    "is_mux": False,
    "explicit": False,
}

POLL_UPLOADED_BODY = {
    "id": AUDIO_UUID,
    "state": "uploaded",
    "duration": 600.0588,
    "primary_file_size": 9601402,
    "media_type": "audio",
}

POLL_TRANSCODED_BODY = {
    "id": AUDIO_UUID,
    "state": "transcoded",
    "duration": 600.0588,
    "primary_file_size": 7201063,  # smaller after transcode
    "media_type": "audio",
}

FAKE_DURATION_SECONDS = 600.032653


def configure_happy_path(api, *, poll_uploaded_count=1):
    """Wire api._session to return the canonical success sequence.

    Order of responses:
      POST  /audio/upload           -> INIT_RESPONSE_BODY
      PUT   {S3 URL}                -> 200 with ETag header
      POST  /audio/upload/{uuid}/transcode -> TRANSCODE_RESPONSE_BODY
      GET   /audio/upload/{uuid}    -> "uploaded" (x poll_uploaded_count) then "transcoded"
    """
    api._session.post.side_effect = [
        fake_response(200, json_data=INIT_RESPONSE_BODY),
        fake_response(200, json_data=TRANSCODE_RESPONSE_BODY),
    ]
    api._session.put.side_effect = [
        fake_response(200, headers={"ETag": S3_ETAG}),
    ]
    api._session.get.side_effect = [
        fake_response(200, json_data=POLL_UPLOADED_BODY)
        for _ in range(poll_uploaded_count)
    ] + [
        fake_response(200, json_data=POLL_TRANSCODED_BODY),
    ]


def call_upload(api, **overrides):
    """Invoke the unit under test with sleep + mutagen patched out.

    `time.sleep` is patched so polling tests don't actually wait.
    `MP3` from mutagen is patched to return a deterministic duration so tests
    don't depend on a real audio file (one separate test exercises mutagen).
    """
    kwargs = {"file_path": str(SMALL_SAMPLE), "draft_id": DRAFT_ID}
    kwargs.update(overrides)
    with patch("substack.api.time.sleep"), patch("substack.api.MP3") as mp3:
        mp3.return_value.info.length = FAKE_DURATION_SECONDS
        return api.upload_podcast_audio(**kwargs)


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioInit
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioInit:
    """The init call: POST /audio/upload with query params."""

    def test_init_hits_correct_endpoint(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        init_url = api._session.post.call_args_list[0][0][0]
        assert init_url == "https://test.substack.com/api/v1/audio/upload"

    def test_init_sends_filename_filesize_filetype_postid_params(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        init_call = api._session.post.call_args_list[0]
        params = init_call.kwargs.get("params") or init_call[1].get("params")
        assert params["filetype"] == "audio/mpeg"
        assert params["fileSize"] == SMALL_SAMPLE.stat().st_size
        assert params["fileName"] == "sample-speech-10m.mp3"
        assert params["post_id"] == DRAFT_ID

    def test_init_sends_no_body(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        init_call = api._session.post.call_args_list[0]
        assert init_call.kwargs.get("json") is None
        assert init_call.kwargs.get("data") is None


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioS3Put
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioS3Put:
    """The S3 PUT: uses the pre-signed URL from init, sends raw bytes."""

    def test_s3_put_uses_url_from_init_response(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        put_call = api._session.put.call_args_list[0]
        assert put_call[0][0] == S3_PUT_URL

    def test_s3_put_sends_raw_audio_bytes(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        put_call = api._session.put.call_args_list[0]
        # Either positional `data=` or kwarg — both acceptable; tolerate both.
        body = put_call.kwargs.get("data")
        if body is None:
            # Try positional
            body = put_call[0][1] if len(put_call[0]) > 1 else None
        assert body is not None
        # Body should be the bytes of the source file (or a streaming handle).
        expected_bytes = SMALL_SAMPLE.read_bytes()
        if hasattr(body, "read"):
            actual = body.read()
        else:
            actual = body
        assert actual == expected_bytes

    def test_s3_put_iterates_all_multipart_upload_urls(self):
        """Defensive: today multipartUploadUrls is always length 1, but the
        implementation must loop so a future multi-part upload doesn't silently
        drop bytes."""
        api = make_api()
        # Hand-craft an init response with two URLs to prove the loop is real.
        url2 = S3_PUT_URL.replace("partNumber=1", "partNumber=2")
        etag2 = '"deadbeefdeadbeefdeadbeefdeadbeef"'
        multi_init = {
            **INIT_RESPONSE_BODY,
            "multipartUploadUrls": [S3_PUT_URL, url2],
        }
        multi_transcode_request_etags = [S3_ETAG, etag2]
        api._session.post.side_effect = [
            fake_response(200, json_data=multi_init),
            fake_response(200, json_data=TRANSCODE_RESPONSE_BODY),
        ]
        api._session.put.side_effect = [
            fake_response(200, headers={"ETag": S3_ETAG}),
            fake_response(200, headers={"ETag": etag2}),
        ]
        api._session.get.side_effect = [
            fake_response(200, json_data=POLL_TRANSCODED_BODY),
        ]
        call_upload(api)
        assert api._session.put.call_count == 2
        # Both etags should appear in the transcode payload, in order.
        transcode_call = api._session.post.call_args_list[1]
        transcode_body = transcode_call.kwargs.get("json")
        assert transcode_body["multipart_upload_etags"] == multi_transcode_request_etags


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioTranscode
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioTranscode:
    """The transcode call: POST with duration + multipart upload id + etags."""

    def test_transcode_hits_correct_endpoint(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        transcode_url = api._session.post.call_args_list[1][0][0]
        assert transcode_url == (
            f"https://test.substack.com/api/v1/audio/upload/{AUDIO_UUID}/transcode"
        )

    def test_transcode_payload_carries_duration_from_mutagen(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        transcode_body = api._session.post.call_args_list[1].kwargs.get("json")
        assert transcode_body["duration"] == FAKE_DURATION_SECONDS

    def test_transcode_payload_carries_multipart_upload_id(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        transcode_body = api._session.post.call_args_list[1].kwargs.get("json")
        assert transcode_body["multipart_upload_id"] == MULTIPART_UPLOAD_ID

    def test_transcode_payload_carries_etag_with_quotes(self):
        """The S3 ETag header includes surrounding double-quotes that the
        transcode endpoint expects to be preserved verbatim."""
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        transcode_body = api._session.post.call_args_list[1].kwargs.get("json")
        assert transcode_body["multipart_upload_etags"] == [S3_ETAG]
        # Defensive: the quotes are still there, not stripped.
        assert transcode_body["multipart_upload_etags"][0].startswith('"')
        assert transcode_body["multipart_upload_etags"][0].endswith('"')


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioPolling
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioPolling:
    """Polling for state transition from 'uploaded' to 'transcoded'."""

    def test_polling_endpoint(self):
        api = make_api()
        configure_happy_path(api)
        call_upload(api)
        poll_url = api._session.get.call_args_list[0][0][0]
        assert poll_url == (
            f"https://test.substack.com/api/v1/audio/upload/{AUDIO_UUID}"
        )

    def test_polling_stops_immediately_when_already_transcoded(self):
        """If the first poll returns 'transcoded', no further polls happen."""
        api = make_api()
        configure_happy_path(api, poll_uploaded_count=0)
        call_upload(api)
        assert api._session.get.call_count == 1

    def test_polling_continues_until_transcoded(self):
        """When polls return 'uploaded' first, polling continues."""
        api = make_api()
        configure_happy_path(api, poll_uploaded_count=3)
        call_upload(api)
        assert api._session.get.call_count == 4  # 3 'uploaded' + 1 'transcoded'

    def test_polling_returns_final_transcoded_media_object(self):
        api = make_api()
        configure_happy_path(api, poll_uploaded_count=2)
        result = call_upload(api)
        assert result["state"] == "transcoded"
        assert result["id"] == AUDIO_UUID
        # The smaller transcoded file size is what comes back.
        assert result["primary_file_size"] == 7201063


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioErrors
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioErrors:
    """Error paths — each step's failure raises a meaningful exception."""

    def test_init_non_2xx_raises_substack_api_exception(self):
        api = make_api()
        api._session.post.side_effect = [
            fake_response(500, text='{"errors": [{"msg": "internal"}]}'),
        ]
        with pytest.raises(SubstackAPIException) as exc:
            call_upload(api)
        assert exc.value.status_code == 500

    def test_s3_put_non_2xx_raises_substack_request_exception(self):
        api = make_api()
        api._session.post.side_effect = [
            fake_response(200, json_data=INIT_RESPONSE_BODY),
        ]
        api._session.put.side_effect = [
            fake_response(403, text="<Error>AccessDenied</Error>"),
        ]
        with pytest.raises(SubstackRequestException) as exc:
            call_upload(api)
        # The error message should mention S3 / the status code so the user
        # can tell upload failures apart from Substack API failures.
        msg = str(exc.value)
        assert "S3" in msg or "403" in msg

    def test_transcode_non_2xx_raises_substack_api_exception(self):
        api = make_api()
        api._session.post.side_effect = [
            fake_response(200, json_data=INIT_RESPONSE_BODY),
            fake_response(400, text='{"errors": [{"msg": "bad etag"}]}'),
        ]
        api._session.put.side_effect = [
            fake_response(200, headers={"ETag": S3_ETAG}),
        ]
        with pytest.raises(SubstackAPIException) as exc:
            call_upload(api)
        assert exc.value.status_code == 400

    def test_polling_times_out_raises_substack_request_exception(self):
        """If state never reaches 'transcoded' within the timeout window,
        raise rather than spin forever.

        Note: does NOT patch time.sleep — the test relies on real wall clock
        to advance past the (tiny) timeout. A callable side_effect avoids
        StopIteration when the loop polls many times.
        """
        api = make_api()
        api._session.post.side_effect = [
            fake_response(200, json_data=INIT_RESPONSE_BODY),
            fake_response(200, json_data=TRANSCODE_RESPONSE_BODY),
        ]
        api._session.put.side_effect = [
            fake_response(200, headers={"ETag": S3_ETAG}),
        ]
        api._session.get.side_effect = (
            lambda *a, **kw: fake_response(200, json_data=POLL_UPLOADED_BODY)
        )
        with patch("substack.api.MP3") as mp3:
            mp3.return_value.info.length = FAKE_DURATION_SECONDS
            with pytest.raises(SubstackRequestException) as exc:
                api.upload_podcast_audio(
                    file_path=str(SMALL_SAMPLE),
                    draft_id=DRAFT_ID,
                    poll_timeout_seconds=0.3,
                    poll_interval_seconds=0.05,
                )
        assert "transcode" in str(exc.value).lower() or "timeout" in str(exc.value).lower()


# ---------------------------------------------------------------------------
# TestMutagenDuration
# ---------------------------------------------------------------------------


class TestMutagenDuration:
    """One real-fixture test confirming mutagen reads MP3 duration.

    All other tests mock MP3 out — this test guards the integration so a
    mutagen version bump or API change is caught locally.
    """

    @pytest.mark.skipif(
        not SMALL_SAMPLE.exists(),
        reason=f"sample MP3 not present at {SMALL_SAMPLE}",
    )
    def test_mutagen_reads_sample_mp3_duration(self):
        from mutagen.mp3 import MP3
        info = MP3(str(SMALL_SAMPLE)).info
        # Sample is ~10 minutes; sanity bounds, not exact equality.
        assert 590 < info.length < 610

    @pytest.mark.skipif(
        not SMALL_SAMPLE.exists(),
        reason=f"sample MP3 not present at {SMALL_SAMPLE}",
    )
    def test_upload_uses_real_mutagen_when_not_patched(self):
        """End-to-end with no MP3 patch: confirms api.py imports mutagen
        correctly and feeds the real duration into the transcode payload."""
        api = make_api()
        configure_happy_path(api)
        # No MP3 patch this time; only sleep.
        with patch("substack.api.time.sleep"):
            api.upload_podcast_audio(file_path=str(SMALL_SAMPLE), draft_id=DRAFT_ID)
        transcode_body = api._session.post.call_args_list[1].kwargs.get("json")
        # Real duration of the sample, with a small tolerance.
        assert 590 < transcode_body["duration"] < 610


# ---------------------------------------------------------------------------
# TestUploadPodcastAudioReturnShape
# ---------------------------------------------------------------------------


class TestUploadPodcastAudioReturnShape:
    """The public method returns the final media object verbatim."""

    def test_returns_dict_with_uuid_state_duration(self):
        api = make_api()
        configure_happy_path(api)
        result = call_upload(api)
        assert isinstance(result, dict)
        assert result["id"] == AUDIO_UUID
        assert result["state"] == "transcoded"
        assert "duration" in result

    def test_does_not_mutate_response_body(self):
        """Caller should receive the parsed JSON without wrapper keys added."""
        api = make_api()
        configure_happy_path(api)
        result = call_upload(api)
        # No invented fields — should match what the API returned.
        assert set(result.keys()) == set(POLL_TRANSCODED_BODY.keys())
