#!/usr/bin/env python3
"""
Rename recordings in Google Drive from URL-encoded names
(e.g. Recording%202026-06-25%2019-27-17.webm)
to meaningful titles scraped from Next IM
(e.g. 25-06-26-9-00AM- R2 - GOSHEN N - Bank Of America.webm).

Usage:
    python rename_drive_recordings.py --use-chrome --drive-folder interview_recordings
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin, unquote

from dotenv import load_dotenv

load_dotenv()

NEXTIM_BASE_URL = "https://nextim.itcapp.ai"
RECORDINGS_URL = f"{NEXTIM_BASE_URL}/recordings/interviews"


def get_drive_service():
    from drive import _get_service
    return _get_service()


def list_drive_files(service, folder_name: str) -> list[dict]:
    """List all .webm files in the given Drive subfolder."""
    from drive import _get_folder_id, _get_or_create_subfolder

    root_id = _get_folder_id(service, os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "interview-prep"))
    if not root_id:
        print("[ERROR] Root Drive folder not found.")
        sys.exit(1)

    sub_id = _get_or_create_subfolder(service, root_id, folder_name)

    files = []
    page_token = None
    while True:
        res = service.files().list(
            q=f"'{sub_id}' in parents and name contains '.webm' and trashed=false",
            fields="nextPageToken, files(id, name)",
            pageSize=1000,
            pageToken=page_token,
            includeItemsFromAllDrives=True,
            supportsAllDrives=True,
        ).execute()
        files.extend(res.get("files", []))
        page_token = res.get("nextPageToken")
        if not page_token:
            break

    return files


def rename_drive_file(service, file_id: str, new_name: str):
    service.files().update(
        fileId=file_id,
        body={"name": new_name},
        supportsAllDrives=True,
    ).execute()


def scrape_recordings(page) -> list[dict]:
    """Scrape all recordings from the current page."""
    raw = page.evaluate("""
        () => {
            const results = [];
            document.querySelectorAll('a').forEach(a => {
                const href = a.href || '';
                if (href.includes('.webm')) {
                    results.push({ href });
                }
            });
            return results;
        }
    """)

    print(f"  [DEBUG] Found {len(raw)} raw .webm links on page")
    if raw:
        print(f"  [DEBUG] Sample href: {raw[0]['href']}")

    recordings = []
    for item in raw:
        href = item["href"]
        # Strip query string (S3 presigned URLs have ?X-Amz-... params)
        href = href.split("?")[0]
        decoded = unquote(href)
        # URL structure: .../recordings/<type>/<folder>/<Recording file>.webm
        parts = [p for p in decoded.split("/") if p]
        if len(parts) < 2:
            continue

        folder_name = parts[-2]
        file_name = parts[-1]  # e.g. "Recording 2025-11-26 14-57-21.webm"

        # Strip internal hash tokens like #-#TECHPREP#-#TC and #1459568
        folder_name = re.sub(r'#-#\w+', '', folder_name)
        folder_name = re.sub(r'#\d+', '', folder_name).strip(" #-")

        recordings.append({
            "folder_title": folder_name,
            "file_name": file_name,
        })

    # Deduplicate by file_name
    seen = set()
    unique = []
    for r in recordings:
        if r["file_name"] not in seen:
            seen.add(r["file_name"])
            unique.append(r)
    return unique


def sanitize_filename(name: str) -> str:
    name = re.sub(r'[<>:"/\\|?*]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if not name.lower().endswith(".webm"):
        name += ".webm"
    if len(name) > 200:
        name = name[:195] + ".webm"
    return name


def main():
    parser = argparse.ArgumentParser(description="Rename Drive recordings to Next IM titles")
    parser.add_argument("--use-chrome", action="store_true", help="Connect to existing Chrome")
    parser.add_argument("--drive-folder", default=os.getenv("DRIVE_RECORDINGS_FOLDER", "interview_recordings"))
    parser.add_argument("--dry-run", action="store_true", help="Show what would be renamed without doing it")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] playwright not installed.")
        sys.exit(1)

    print("[INFO] Connecting to Next IM to fetch recording titles...")

    with sync_playwright() as p:
        if args.use_chrome:
            browser = p.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0]
            page = context.pages[0] if context.pages else context.new_page()
        else:
            state_path = Path(".nextim_auth_state.json")
            browser = p.chromium.launch(headless=False)
            context = browser.new_context(storage_state=str(state_path)) if state_path.exists() else browser.new_context()
            page = context.new_page()
            page.goto(RECORDINGS_URL, wait_until="networkidle", timeout=30000)

        print("[INFO] Expand the list in the browser until all recordings are visible.")
        input("      Press Enter when ready...\n")

        recordings = scrape_recordings(page)
        browser.close()

    if not recordings:
        print("[WARN] No recordings found from Next IM.")
        sys.exit(1)

    print(f"[INFO] Scraped {len(recordings)} recording titles from Next IM.")
    print(f"       Sample: {recordings[0]['file_name']} → {recordings[0]['folder_title']}")

    # Build lookup: decoded recording filename → folder title
    # e.g. "Recording 2025-11-26 14-57-21.webm" → "01-12-25-5-00PM- R1 - Janvi B - TP-Link.webm"
    title_map = {}
    for r in recordings:
        title_map[r["file_name"]] = sanitize_filename(r["folder_title"])

    print(f"  [DEBUG] Sample title_map entry: {next(iter(title_map.items())) if title_map else 'empty'}")

    print("[INFO] Fetching files from Google Drive...")
    service = get_drive_service()
    drive_files = list_drive_files(service, args.drive_folder)
    print(f"[INFO] Found {len(drive_files)} files in Drive folder '{args.drive_folder}'.\n")

    renamed = 0
    skipped = 0
    not_found = 0

    for f in drive_files:
        current_name = f["name"]
        decoded_name = unquote(current_name)

        new_name = title_map.get(decoded_name) or title_map.get(current_name)

        if not new_name:
            print(f"  [NO MATCH] {current_name}")
            not_found += 1
            continue

        if current_name == new_name:
            skipped += 1
            continue

        if args.dry_run:
            print(f"  [DRY RUN] {current_name}\n           → {new_name}")
        else:
            try:
                rename_drive_file(service, f["id"], new_name)
                print(f"  [RENAMED] {current_name}\n           → {new_name}")
                renamed += 1
            except Exception as e:
                print(f"  [FAIL] {current_name}: {e}")

    print(f"\n[DONE] Renamed: {renamed} | Already correct: {skipped} | No match: {not_found}")


if __name__ == "__main__":
    main()
