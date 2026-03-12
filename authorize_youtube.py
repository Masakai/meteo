#!/usr/bin/env python3
"""Generate OAuth credentials for YouTube uploads."""

from __future__ import annotations

import argparse
import os
from pathlib import Path

from google_auth_oauthlib.flow import InstalledAppFlow


SCOPES = ["https://www.googleapis.com/auth/youtube.upload"]


def parse_args():
    parser = argparse.ArgumentParser(description="Authorize YouTube uploads and save OAuth token JSON.")
    parser.add_argument(
        "--client-secrets",
        default=os.environ.get("YOUTUBE_CLIENT_SECRETS_FILE", ""),
        help="Path to the Google OAuth client secrets JSON.",
    )
    parser.add_argument(
        "--token-file",
        default=os.environ.get("YOUTUBE_TOKEN_FILE", "youtube_token.json"),
        help="Path to write the authorized token JSON.",
    )
    return parser.parse_args()


def main():
    args = parse_args()
    client_secrets = Path(args.client_secrets).expanduser()
    token_file = Path(args.token_file).expanduser()

    if not args.client_secrets:
        raise SystemExit("--client-secrets is required")
    if not client_secrets.exists():
        raise SystemExit(f"client secrets file not found: {client_secrets}")

    flow = InstalledAppFlow.from_client_secrets_file(str(client_secrets), SCOPES)
    credentials = flow.run_local_server(port=0)

    token_file.parent.mkdir(parents=True, exist_ok=True)
    token_file.write_text(credentials.to_json(), encoding="utf-8")
    print(f"saved token: {token_file}")


if __name__ == "__main__":
    main()
