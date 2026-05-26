"""Extract a digestible summary of a HAR capture.

Filters to substack.com / S3 / amazonaws hosts and prints, for each request:
URL, method, status, content-type, body sizes, and a truncated body preview.

Usage:
    python extract_har.py <path-to-har> [--filter SUBSTRING]
"""

from __future__ import annotations

import argparse
import io
import json
import sys
from pathlib import Path

# Force UTF-8 stdout on Windows.
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")


def short(text: str | None, limit: int = 600) -> str:
    if text is None:
        return ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"... [+{len(text) - limit} bytes]"


def header(headers, name):
    name_l = name.lower()
    for h in headers or []:
        if h.get("name", "").lower() == name_l:
            return h.get("value", "")
    return ""


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("har")
    p.add_argument("--filter", default="", help="substring to require in URL")
    p.add_argument("--method", default="", help="only this HTTP method")
    p.add_argument("--limit", type=int, default=0, help="max entries to print (0 = all)")
    p.add_argument("--full-body", action="store_true", help="print full bodies (no truncation)")
    args = p.parse_args()

    har = json.loads(Path(args.har).read_text(encoding="utf-8", errors="replace"))
    entries = har["log"]["entries"]
    matched = 0
    for i, e in enumerate(entries):
        req = e["request"]
        res = e["response"]
        url = req["url"]
        if args.filter and args.filter not in url:
            continue
        if args.method and req["method"].upper() != args.method.upper():
            continue
        matched += 1
        print("=" * 100)
        print(f"#{i}  {req['method']} {url}")
        print(f"     status: {res['status']} {res.get('statusText','')}")
        ct_req = header(req.get("headers"), "content-type")
        ct_res = header(res.get("headers"), "content-type")
        print(f"     req content-type: {ct_req}")
        print(f"     res content-type: {ct_res}")
        # Show interesting auth/csrf headers
        for hname in ("x-csrf-token", "x-substack-publication-id", "x-amz-meta-uuid",
                      "x-amz-server-side-encryption", "x-amz-acl"):
            v = header(req.get("headers"), hname)
            if v:
                print(f"     req {hname}: {v}")
        # Body sizes
        pd = req.get("postData") or {}
        body_text = pd.get("text", "")
        body_size = req.get("bodySize", -1)
        pd_mime = pd.get("mimeType", "")
        print(f"     req bodySize: {body_size}, postData.text len: {len(body_text)}, mime: {pd_mime}")
        # Don't print bodies for binary mime types
        is_binary = pd_mime.startswith(("audio/", "image/", "video/", "application/octet")) or "binary" in pd_mime
        if body_text and not is_binary:
            print(f"     req body: {body_text if args.full_body else short(body_text)}")
        elif body_text and is_binary:
            print(f"     req body: <binary {pd_mime} {len(body_text)} bytes elided>")
        else:
            if pd.get("params"):
                print(f"     req postData.params: {pd['params']}")
        # Useful response headers
        for hname in ("etag", "x-amz-version-id", "location"):
            v = header(res.get("headers"), hname)
            if v:
                print(f"     res {hname}: {v}")
        # Response body
        content = res.get("content") or {}
        rtext = content.get("text", "")
        rsize = content.get("size", -1)
        print(f"     res size: {rsize}, content.text len: {len(rtext)}")
        if rtext:
            print(f"     res body: {rtext if args.full_body else short(rtext)}")
        if args.limit and matched >= args.limit:
            break

    print(f"\n=== matched {matched} entries ===")
    return 0


if __name__ == "__main__":
    sys.exit(main())
