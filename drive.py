"""
Google Drive integration for interview prep document storage.
Uploads generated markdown files to a shared Drive folder and
provides listing/download for the Documents tab.
"""

import os
from pathlib import Path
from functools import lru_cache

from dotenv import load_dotenv
from google.oauth2 import service_account
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload, MediaIoBaseDownload
import io

load_dotenv()

SCOPES = ["https://www.googleapis.com/auth/drive"]


def _get_service():
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    if not creds_path or not Path(creds_path).exists():
        raise FileNotFoundError(
            f"Service account JSON not found at: {creds_path}\n"
            "Set GOOGLE_SERVICE_ACCOUNT_JSON in .env"
        )
    creds = service_account.Credentials.from_service_account_file(
        creds_path, scopes=SCOPES
    )
    return build("drive", "v3", credentials=creds)


def _get_folder_id(service, folder_name: str) -> str | None:
    """Return the root Drive folder ID — uses GOOGLE_DRIVE_FOLDER_ID if set, otherwise searches by name."""
    folder_id = os.getenv("GOOGLE_DRIVE_FOLDER_ID", "").strip()
    if folder_id:
        return folder_id
    res = service.files().list(
        q=f"name='{folder_name}' and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    files = res.get("files", [])
    return files[0]["id"] if files else None


def _get_or_create_subfolder(service, parent_id: str, name: str) -> str:
    """Get or create a subfolder inside the parent folder."""
    res = service.files().list(
        q=f"name='{name}' and '{parent_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    files = res.get("files", [])
    if files:
        return files[0]["id"]
    meta = {
        "name": name,
        "mimeType": "application/vnd.google-apps.folder",
        "parents": [parent_id],
    }
    folder = service.files().create(body=meta, fields="id", supportsAllDrives=True).execute()
    return folder["id"]


def upload_file(local_path: str, drive_subfolder: str) -> str:
    """
    Upload a markdown file to Drive under interview-prep/drive_subfolder/.
    Returns the Drive file ID.
    """
    folder_name = os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "interview-prep")
    service = _get_service()

    root_id = _get_folder_id(service, folder_name)
    if not root_id:
        raise RuntimeError(
            f"Drive folder '{folder_name}' not found. "
            "Make sure you shared it with the service account."
        )

    sub_id = _get_or_create_subfolder(service, root_id, drive_subfolder)

    filename = Path(local_path).name

    # Check if file already exists — update it instead of creating a duplicate
    existing = service.files().list(
        q=f"name='{filename}' and '{sub_id}' in parents and trashed=false",
        fields="files(id)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute().get("files", [])

    ext = Path(local_path).suffix.lower()
    mime_map = {".md": "text/markdown", ".pdf": "application/pdf", ".txt": "text/plain"}
    mimetype = mime_map.get(ext, "application/octet-stream")
    media = MediaFileUpload(local_path, mimetype=mimetype, resumable=False)

    if existing:
        file = service.files().update(
            fileId=existing[0]["id"],
            media_body=media,
            fields="id",
            supportsAllDrives=True,
        ).execute()
    else:
        meta = {"name": filename, "parents": [sub_id]}
        file = service.files().create(
            body=meta, media_body=media, fields="id", supportsAllDrives=True,
        ).execute()

    return file["id"]


def _collect_all_md_files(service, folder_id: str, folder_name: str, results: list):
    """Recursively collect all .md files under folder_id."""
    # Files in this folder
    page_token = None
    while True:
        res = service.files().list(
            q=f"'{folder_id}' in parents and name contains '.md' and mimeType!='application/vnd.google-apps.folder' and trashed=false",
            fields="files(id, name, size, modifiedTime)",
            orderBy="modifiedTime desc",
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        for f in res.get("files", []):
            parts = f["name"].replace(".md", "").split("_", 2)
            results.append({
                "id":       f["id"],
                "name":     f["name"],
                "filename": f["name"],
                "folder":   folder_name,
                "date":     parts[0] if len(parts) > 0 else "",
                "company":  parts[1] if len(parts) > 1 else "",
                "doc_type": parts[2] if len(parts) > 2 else f["name"],
                "size_kb":  round(int(f.get("size", 0)) / 1024, 1),
                "modified": f.get("modifiedTime", "")[:10],
            })
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    # Recurse into subfolders
    sub_res = service.files().list(
        q=f"'{folder_id}' in parents and mimeType='application/vnd.google-apps.folder' and trashed=false",
        fields="files(id, name)",
        includeItemsFromAllDrives=True,
        supportsAllDrives=True,
    ).execute()
    for sub in sub_res.get("files", []):
        _collect_all_md_files(service, sub["id"], sub["name"], results)


def list_files() -> list[dict]:
    """
    List all markdown files in the interview-prep Drive folder (any depth).
    Returns list of dicts with: id, name, folder, size, modified.
    Raises RuntimeError if the root folder can't be found so the caller can show a useful error.
    """
    folder_name = os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "interview-prep")
    service = _get_service()

    root_id = _get_folder_id(service, folder_name)
    if not root_id:
        raise RuntimeError(
            f"Google Drive folder '{folder_name}' not found. "
            "Make sure it exists and is shared with the service account."
        )

    results = []
    _collect_all_md_files(service, root_id, "", results)
    return results


def download_file(file_id: str) -> bytes:
    """Download a file from Drive by ID. Returns raw bytes."""
    service = _get_service()
    request = service.files().get_media(fileId=file_id)
    buf = io.BytesIO()
    downloader = MediaIoBaseDownload(buf, request)
    done = False
    while not done:
        _, done = downloader.next_chunk()
    return buf.getvalue()


def is_configured() -> bool:
    """Return True if Google Drive is configured and usable."""
    creds_path = os.getenv("GOOGLE_SERVICE_ACCOUNT_JSON", "")
    return bool(creds_path) and Path(creds_path).exists()
