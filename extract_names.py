#!/usr/bin/env python3
"""
Extract unique interviewee names from Google Drive recording filenames.
Filenames follow the pattern: DD-MM-YY-H-MMPM- RX - Name - Company.webm

Usage:
    python extract_names.py
    python extract_names.py --output names.csv --drive-folder interview_recordings
"""

import argparse
import csv
import os
import re
import sys
from dotenv import load_dotenv

load_dotenv()


def list_drive_files(service, drive_folder: str) -> list[dict]:
    from drive import _get_folder_id, _get_or_create_subfolder

    root_id = _get_folder_id(service, os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "interview-prep"))
    if not root_id:
        print("[ERROR] Root Drive folder not found.")
        sys.exit(1)

    sub_id = _get_or_create_subfolder(service, root_id, drive_folder)

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


def extract_name(filename: str) -> str | None:
    """
    Extract the interviewee name from a filename like:
    '01-07-26-1-00PM- R2 - Luke W - JPMC.webm'
    '02-12-25-2-00PM- R2 - Daniel A - Tata Consultancy Services.webm'
    """
    # Remove extension
    name = filename.replace(".webm", "").strip()

    # Match pattern: ... - RX - <Name> - <Company>
    m = re.search(r'-\s*R\w+\s*-\s*(.+?)\s*-\s*[^-]+$', name, re.IGNORECASE)
    if m:
        return m.group(1).strip()

    return None


def main():
    parser = argparse.ArgumentParser(description="Extract unique names from Drive recordings")
    parser.add_argument("--output", default="interviewee_names.csv", help="Output CSV file path")
    parser.add_argument("--drive-folder", default=os.getenv("DRIVE_RECORDINGS_FOLDER", "interview_recordings"))
    args = parser.parse_args()

    from drive import _get_service
    service = _get_service()

    print(f"[INFO] Fetching files from Drive folder '{args.drive_folder}'...")
    files = list_drive_files(service, args.drive_folder)
    print(f"[INFO] Found {len(files)} files.")

    names = {}  # name -> count
    no_match = []

    for f in files:
        name = extract_name(f["name"])
        if name:
            names[name] = names.get(name, 0) + 1
        else:
            no_match.append(f["name"])

    sorted_names = sorted(names.items(), key=lambda x: x[0])

    with open(args.output, "w", newline="", encoding="utf-8") as csvfile:
        writer = csv.writer(csvfile)
        writer.writerow(["Name", "Recording Count"])
        for name, count in sorted_names:
            writer.writerow([name, count])

    print(f"\n[DONE] {len(sorted_names)} unique names saved to {args.output}")
    if no_match:
        print(f"[WARN] {len(no_match)} filenames didn't match the expected pattern:")
        for f in no_match[:10]:
            print(f"  {f}")
        if len(no_match) > 10:
            print(f"  ... and {len(no_match) - 10} more")


if __name__ == "__main__":
    main()
