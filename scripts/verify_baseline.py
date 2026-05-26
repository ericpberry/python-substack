"""Baseline verification for python-substack against a sandbox publication.

Exercises the FastMCP tool surface end-to-end:
  1. Authenticate + list publications
  2. Create a newsletter draft from markdown via the MCP tool
  3. Publish it (send=False so no email goes out)
  4. Delete the resulting post

Reads .env from python-substack/.env. Prints PASS/FAIL per step and exits 0 only
if every step passed.
"""

from __future__ import annotations

import asyncio
import os
import sys
import time
import traceback
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))

from dotenv import load_dotenv

load_dotenv(REPO / ".env")

from substack_mcp.mcp_server import (  # noqa: E402
    get_api,
    post_draft_from_markdown,
    publish_draft,
)


def banner(msg: str) -> None:
    print(f"\n=== {msg} ===", flush=True)


def step(label: str, ok: bool, detail: str = "") -> None:
    tag = "PASS" if ok else "FAIL"
    line = f"[{tag}] {label}"
    if detail:
        line += f" — {detail}"
    print(line, flush=True)


async def main() -> int:
    failures: list[str] = []
    created_post_id: int | None = None
    api = None

    # --- Step 1: auth + list publications ---
    banner("Step 1: authenticate and list publications")
    try:
        api = get_api()
        pubs = api.get_user_publications()
        names = [p.get("subdomain") for p in pubs]
        step("authenticate via get_api()", True, f"current publication_url={api.publication_url}")
        step("get_user_publications()", True, f"{len(pubs)} publications: {names}")
        primary = api.get_user_primary_publication()
        step("get_user_primary_publication()", True, f"subdomain={primary.get('subdomain')}")
    except Exception as exc:
        step("authenticate / list publications", False, repr(exc))
        traceback.print_exc()
        failures.append("auth")
        return 1

    # --- Step 2: create draft from markdown via MCP tool ---
    banner("Step 2: post_draft_from_markdown (MCP tool)")
    ts = time.strftime("%Y-%m-%d %H:%M:%S")
    title = f"[baseline test {ts}] python-substack verification"
    markdown = (
        "# Baseline verification\n\n"
        "This draft was created by `scripts/verify_baseline.py` to confirm the "
        "FastMCP server functions correctly against the sandbox publication.\n\n"
        "It should be deleted immediately by the same script. If you are reading "
        "this in a published post, the cleanup step failed.\n"
    )
    try:
        result = await post_draft_from_markdown(
            title=title,
            markdown=markdown,
            subtitle="Automated baseline verification — safe to delete",
            audience="everyone",
            write_comment_permissions="everyone",
            prepublish=False,
            publish=False,
        )
        draft = result.get("draft") or {}
        created_post_id = draft.get("id")
        if not created_post_id:
            raise RuntimeError(f"no draft id in response: {result!r}")
        step(
            "post_draft_from_markdown",
            True,
            f"draft_id={created_post_id} type={draft.get('type')}",
        )
    except Exception as exc:
        step("post_draft_from_markdown", False, repr(exc))
        traceback.print_exc()
        failures.append("create_draft")

    # --- Step 3: publish (send=False so no email goes out) ---
    if created_post_id is not None:
        banner("Step 3: publish_draft (send=False, share_automatically=False)")
        try:
            pub_result = await publish_draft(
                draft_id=created_post_id,
                send=False,
                share_automatically=False,
            )
            published_id = (pub_result or {}).get("id") or created_post_id
            step(
                "publish_draft",
                True,
                f"published id={published_id} is_published={pub_result.get('is_published')}",
            )
            # publish typically returns the post with a new id distinct from the draft id;
            # keep the original draft id for cleanup, but note both.
            created_post_id = published_id
        except Exception as exc:
            step("publish_draft", False, repr(exc))
            traceback.print_exc()
            failures.append("publish")

    # --- Step 4: cleanup ---
    if created_post_id is not None:
        banner("Step 4: delete published draft")
        try:
            del_result = api.delete_draft(created_post_id)
            step("delete_draft", True, f"response={del_result!r}")
        except Exception as exc:
            step("delete_draft", False, repr(exc))
            traceback.print_exc()
            failures.append("delete")
            print(
                f"\n!! NOTE: Post id={created_post_id} may still exist on the publication. "
                "Delete it manually from the Substack dashboard.",
                flush=True,
            )

    banner("Summary")
    if failures:
        print(f"FAILED steps: {failures}", flush=True)
        return 1
    print("All steps passed.", flush=True)
    return 0


if __name__ == "__main__":
    sys.exit(asyncio.run(main()))
