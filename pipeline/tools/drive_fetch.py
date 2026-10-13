#!/usr/bin/env python3
"""Recursively download a Google Drive folder tree to local disk.

Standalone replacement for the manual "download files from the Shared Drive"
step in the QC cycle workflow. Runs outside Claude Code. Supports three auth
modes — use whichever your org can actually provision:

Mode A — Impersonate a service account via your own login (no static key
ever exists; this is what most security-conscious orgs will actually grant):
    1. An admin creates a service account and grants YOUR account the
       "Service Account Token Creator" role on it (this is what lets you
       impersonate it — no JSON key is created or shared).
    2. Someone with access shares the target Shared Drive / folder with
       the service account's email (...@<project>.iam.gserviceaccount.com),
       same as sharing with a person — Viewer access is enough.
    3. Install the Google Cloud SDK (gcloud), then run:
         gcloud auth login
         gcloud auth application-default login \\
             --impersonate-service-account=<service-account-email>
    4. Run this script with --impersonate <service-account-email> (or set
       env var DRIVE_FETCH_IMPERSONATE). No credentials.json needed at all.

Mode B — Service account JSON key (no browser consent, works headlessly;
most orgs won't hand these out anymore — see Mode A):
    1. Ask an admin to create a GCP service account with the Drive API
       enabled, then download its JSON key.
    2. Share the target Shared Drive / folder with the service account's
       email, same as sharing with a person — Viewer access is enough.
    3. Save the key JSON as pipeline/.driveauth/credentials.json.
    Detected automatically (the file has "type": "service_account").

Mode C — OAuth Desktop client (needs Cloud Console project-creation
rights, which not everyone has):
    1. https://console.cloud.google.com -> select/create a project.
    2. Enable the "Google Drive API" (APIs & Services -> Library).
    3. APIs & Services -> Credentials -> Create Credentials -> OAuth client
       ID -> Application type "Desktop app". Download the JSON.
    4. Save it as pipeline/.driveauth/credentials.json.
    5. Run this script. The first run opens a browser for consent and
       caches a refresh token at pipeline/.driveauth/token.json.

Usage:
    python drive_fetch.py <folder_id_or_url> <dest_dir> [options]

Example (impersonation mode, after the gcloud commands in Mode A above):
    python drive_fetch.py \\
        https://drive.google.com/drive/folders/1VwkGxBKcSjrCFWENFEk7-ICT922TvYvR \\
        cycles/2026-07-30/00_fetched/396 \\
        --impersonate ekw-ots-qc@turing-delivery-apac-dev.iam.gserviceaccount.com
"""

import argparse
import io
import json
import os
import re
import sys
from pathlib import Path

import google.auth
import google.auth.exceptions
from google.auth import impersonated_credentials
from google.auth.transport.requests import Request
from google.oauth2 import service_account
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError
from googleapiclient.http import MediaIoBaseDownload

SCOPES = ["https://www.googleapis.com/auth/drive.readonly"]

DEFAULT_AUTH_DIR = Path(__file__).resolve().parents[1] / ".driveauth"
DEFAULT_CREDENTIALS = DEFAULT_AUTH_DIR / "credentials.json"
DEFAULT_TOKEN = DEFAULT_AUTH_DIR / "token.json"

# Native Google Docs types must be exported to a real file format.
EXPORT_MIME = {
    "application/vnd.google-apps.document": (
        "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        ".docx",
    ),
    "application/vnd.google-apps.spreadsheet": (
        "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        ".xlsx",
    ),
    "application/vnd.google-apps.presentation": (
        "application/vnd.openxmlformats-officedocument.presentationml.presentation",
        ".pptx",
    ),
    "application/vnd.google-apps.drawing": ("application/pdf", ".pdf"),
}

FOLDER_MIME = "application/vnd.google-apps.folder"
SHORTCUT_MIME = "application/vnd.google-apps.shortcut"

INVALID_CHARS = re.compile(r'[/\\:*?"<>|]')


def sanitize(name: str) -> str:
    return INVALID_CHARS.sub("_", name).strip() or "_"


def extract_folder_id(value: str) -> str:
    match = re.search(r"/folders/([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)
    match = re.search(r"[?&]id=([a-zA-Z0-9_-]+)", value)
    if match:
        return match.group(1)
    return value.strip()


def get_credentials(
    credentials_path: Path, token_path: Path, impersonate: str | None, use_adc: bool
) -> Credentials:
    if impersonate:
        source_creds, _ = google.auth.default()
        return impersonated_credentials.Credentials(
            source_credentials=source_creds,
            target_principal=impersonate,
            target_scopes=SCOPES,
            lifetime=3600,
        )

    if use_adc or not credentials_path.exists():
        try:
            creds, _ = google.auth.default(scopes=SCOPES)
            return creds
        except google.auth.exceptions.DefaultCredentialsError:
            pass
        sys.exit(
            f"Missing credentials file: {credentials_path}\n"
            "and no Application Default Credentials found. Either save a "
            "credentials.json (see --help) or run:\n"
            "  gcloud auth application-default login "
            f"--scopes={','.join(SCOPES)}"
        )

    key_data = json.loads(credentials_path.read_text())
    if key_data.get("type") == "service_account":
        return service_account.Credentials.from_service_account_file(
            str(credentials_path), scopes=SCOPES
        )

    creds = None
    if token_path.exists():
        creds = Credentials.from_authorized_user_file(str(token_path), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(
                str(credentials_path), SCOPES
            )
            creds = flow.run_local_server(port=0)
        token_path.parent.mkdir(parents=True, exist_ok=True)
        token_path.write_text(creds.to_json())
    return creds


def list_children(service, folder_id: str):
    page_token = None
    while True:
        response = (
            service.files()
            .list(
                q=f"'{folder_id}' in parents and trashed = false",
                fields="nextPageToken, files(id, name, mimeType, size, shortcutDetails)",
                pageSize=200,
                supportsAllDrives=True,
                includeItemsFromAllDrives=True,
                corpora="allDrives",
                pageToken=page_token,
            )
            .execute()
        )
        yield from response.get("files", [])
        page_token = response.get("nextPageToken")
        if not page_token:
            break


def download_file(service, file_id: str, mime_type: str, dest: Path, force: bool):
    export_pair = EXPORT_MIME.get(mime_type)
    if export_pair:
        export_mime, ext = export_pair
        if dest.suffix.lower() != ext:
            dest = dest.with_suffix(ext)
        if dest.exists() and not force:
            print(f"  skip (exists): {dest}")
            return
        request = service.files().export_media(fileId=file_id, mimeType=export_mime)
    else:
        if dest.exists() and not force:
            print(f"  skip (exists): {dest}")
            return
        request = service.files().get_media(fileId=file_id, supportsAllDrives=True)

    try:
        buf = io.BytesIO()
        downloader = MediaIoBaseDownload(buf, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
    except HttpError as exc:
        print(f"  FAILED: {dest} ({exc})")
        return
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(buf.getvalue())
    print(f"  downloaded: {dest} ({dest.stat().st_size} bytes)")


def walk(service, folder_id: str, dest_dir: Path, force: bool, seen_shortcuts=None):
    seen_shortcuts = seen_shortcuts or set()
    for item in list_children(service, folder_id):
        name = sanitize(item["name"])
        mime_type = item["mimeType"]

        if mime_type == SHORTCUT_MIME:
            target = item.get("shortcutDetails", {})
            target_id = target.get("targetId")
            target_mime = target.get("targetMimeType", "")
            if not target_id or target_id in seen_shortcuts:
                continue
            seen_shortcuts.add(target_id)
            if target_mime == FOLDER_MIME:
                walk(service, target_id, dest_dir / name, force, seen_shortcuts)
            else:
                download_file(service, target_id, target_mime, dest_dir / name, force)
            continue

        if mime_type == FOLDER_MIME:
            walk(service, item["id"], dest_dir / name, force, seen_shortcuts)
            continue

        download_file(service, item["id"], mime_type, dest_dir / name, force)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("folder", help="Drive folder ID or full folder URL")
    parser.add_argument("dest", help="Local destination directory")
    parser.add_argument("--credentials", default=str(DEFAULT_CREDENTIALS))
    parser.add_argument("--token", default=str(DEFAULT_TOKEN))
    parser.add_argument(
        "--impersonate",
        default=os.environ.get("DRIVE_FETCH_IMPERSONATE"),
        help=(
            "Service account email to impersonate via your own gcloud "
            "login, instead of a credentials.json key (see Mode A in "
            "--help). Also settable via DRIVE_FETCH_IMPERSONATE."
        ),
    )
    parser.add_argument(
        "--adc",
        action="store_true",
        help=(
            "Use your own Application Default Credentials directly (no "
            "impersonation, no credentials.json) — run "
            "`gcloud auth application-default login "
            "--scopes=https://www.googleapis.com/auth/drive.readonly` "
            "first. Works as long as your own account already has access "
            "to the target Drive folder."
        ),
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Re-download files that already exist locally",
    )
    args = parser.parse_args()

    folder_id = extract_folder_id(args.folder)
    dest_dir = Path(args.dest).resolve()
    creds = get_credentials(
        Path(args.credentials), Path(args.token), args.impersonate, args.adc
    )
    service = build("drive", "v3", credentials=creds)

    print(f"Fetching Drive folder {folder_id} -> {dest_dir}")
    walk(service, folder_id, dest_dir, args.force)
    print("Done.")


if __name__ == "__main__":
    main()
