#!/usr/bin/env python3
"""
Scrape interview recording videos from Next IM (nextim.itcapp.ai).

Uses Playwright to authenticate and download .webm files.

Usage:
    python scrape_recordings.py                        # download all recordings
    python scrape_recordings.py --company "US"         # filter by company
    python scrape_recordings.py --search "goshen"      # filter by search text
    python scrape_recordings.py --output ./my_videos   # custom output directory
    python scrape_recordings.py --list-only            # just list recordings, don't download
"""

import argparse
import os
import re
import sys
import time
from pathlib import Path
from urllib.parse import urljoin

from dotenv import load_dotenv

load_dotenv()

NEXTIM_BASE_URL = "https://nextim.itcapp.ai"
RECORDINGS_URL = f"{NEXTIM_BASE_URL}/recordings/interviews"
DEFAULT_OUTPUT = os.path.join(Path.home(), "Downloads", "interview_recordings")


def get_browser_context(playwright, headless=True, use_existing_chrome=False):
    """Launch browser and return a context with stored auth state if available."""
    if use_existing_chrome:
        # Connect to an already-running Chrome with --remote-debugging-port=9222
        try:
            browser = playwright.chromium.connect_over_cdp("http://localhost:9222")
            context = browser.contexts[0] if browser.contexts else browser.new_context()
            return browser, context
        except Exception as e:
            print(f"[ERROR] Could not connect to Chrome on port 9222: {e}")
            print("        Make sure Chrome is running with --remote-debugging-port=9222")
            print("        See instructions printed at startup.")
            sys.exit(1)

    state_path = Path(".nextim_auth_state.json")
    browser = playwright.chromium.launch(headless=headless)
    if state_path.exists():
        context = browser.new_context(storage_state=str(state_path))
    else:
        context = browser.new_context()
    return browser, context


def save_auth_state(context):
    """Persist cookies/local storage so we don't need to log in again."""
    context.storage_state(path=".nextim_auth_state.json")


def login_if_needed(page):
    """Check if we're on a login page and handle authentication."""
    page.goto(RECORDINGS_URL, wait_until="networkidle", timeout=30000)
    time.sleep(2)

    if "/login" in page.url or page.locator("input[type='password']").count() > 0:
        email = os.getenv("NEXTIM_EMAIL", "")
        password = os.getenv("NEXTIM_PASSWORD", "")

        if not email or not password:
            print("[ERROR] Login required. Set NEXTIM_EMAIL and NEXTIM_PASSWORD in .env")
            print("        Or run with --no-headless to log in manually.")
            sys.exit(1)

        email_input = page.locator("input[type='email'], input[name='email'], input[name='username']").first
        pass_input = page.locator("input[type='password']").first

        if email_input.count() > 0:
            email_input.fill(email)
        pass_input.fill(password)

        submit = page.locator("button[type='submit'], input[type='submit']").first
        submit.click()
        page.wait_for_load_state("networkidle", timeout=15000)
        time.sleep(2)

    return page


def manual_login(page):
    """Open browser for manual login, then wait for user to reach recordings page."""
    page.goto(NEXTIM_BASE_URL, wait_until="domcontentloaded", timeout=120000)
    print("\n[INFO] Browser opened. Please log in manually.")
    print("       Navigate to the Recordings page when done.")
    print("       Waiting for you to reach the recordings page...\n")

    page.wait_for_url("**/recordings/**", timeout=300000)
    page.wait_for_load_state("domcontentloaded", timeout=30000)
    # Wait for recording cards to render
    try:
        page.wait_for_selector("a[href*='Recording'], a[href*='.webm'], [class*='card'], [class*='recording']", timeout=15000)
    except Exception:
        pass
    time.sleep(5)
    return page


def select_company_filter(page, company: str):
    """Select a company from the filter dropdown."""
    dropdown = page.locator("select").first
    if dropdown.count() > 0:
        dropdown.select_option(label=company)
        time.sleep(2)
        page.wait_for_load_state("networkidle", timeout=10000)


def apply_search_filter(page, search_text: str):
    """Type into the search box to filter recordings."""
    search_input = page.locator("input[type='text'], input[type='search']").first
    if search_input.count() > 0:
        search_input.fill(search_text)
        time.sleep(2)


_GENERIC_TEXTS = {"open", "view", "download", "watch", "play", "start", "go", "click here", "recording"}


def scrape_recording_cards(page) -> list[dict]:
    """Extract recording info from the current page using JS DOM traversal."""

    raw = page.evaluate("""
        () => {
            const GENERIC = new Set(["open","view","download","watch","play","start","go","click here","recording"]);
            const results = [];

            function cardTitle(el) {
                // Walk up to 6 ancestors looking for a meaningful title
                let node = el.parentElement;
                for (let i = 0; i < 6 && node; i++, node = node.parentElement) {
                    // Collect all text nodes / heading / span / p inside this ancestor
                    const kids = node.querySelectorAll('h1,h2,h3,h4,h5,h6,p,span,[class*="title"],[class*="name"],[class*="label"]');
                    for (const k of kids) {
                        const t = k.textContent.trim();
                        if (t && !GENERIC.has(t.toLowerCase()) && t.length > 4 && t.length < 200) {
                            return t.replace(/\\s+/g, ' ');
                        }
                    }
                    // Fall back to the whole ancestor text if it's short enough
                    const full = node.textContent.trim().replace(/\\s+/g, ' ');
                    if (full && !GENERIC.has(full.toLowerCase()) && full.length > 4 && full.length < 200) {
                        // Return only the first line-ish chunk
                        const first = full.split(/[\\n|]+/)[0].trim();
                        if (first && !GENERIC.has(first.toLowerCase()) && first.length > 4) {
                            return first.substring(0, 120);
                        }
                    }
                }
                return "";
            }

            document.querySelectorAll('a').forEach(a => {
                const href = a.href || '';
                if (!href.includes('.webm') && !href.includes('Recording') && !href.includes('recording')) return;
                const linkText = a.textContent.trim();
                const title = (!linkText || GENERIC.has(linkText.toLowerCase()))
                    ? cardTitle(a)
                    : linkText;
                results.push({ href, title: title.substring(0, 150) });
            });

            return results;
        }
    """)

    recordings = []
    for item in raw:
        href = item["href"]
        title = item["title"].strip()

        # Final fallback: use URL path segments
        if not title or title.lower() in _GENERIC_TEXTS:
            parts = [p for p in href.split("/") if p and p.lower() not in _GENERIC_TEXTS]
            title = parts[-1].split("?")[0] if parts else "recording"
            title = title.replace("%20", " ").replace("-", " ").replace("_", " ")

        url = href if href.startswith("http") else urljoin(NEXTIM_BASE_URL, href)
        # Derive title from the folder name in the URL (e.g. "01-12-25-5-00PM- R1 - Janvi B - TP-Link")
        # URL structure: recordings/interviews/<folder>/<Recording file>.webm
        decoded_href = href.replace("%20", " ").replace("%23", "#")
        parts = [p for p in decoded_href.split("/") if p]
        folder_name = parts[-2] if len(parts) >= 2 else ""
        # Strip internal hash tokens like #-#TECHPREP#-#TC
        folder_name = re.sub(r'#-#\w+', '', folder_name).strip(" #-")
        display_title = folder_name if folder_name else title
        filename = sanitize_filename(display_title)
        recordings.append({
            "title": display_title,
            "url": url,
            "filename": filename,
        })

    # Deduplicate by URL; suffix colliding filenames (Open.webm → Open_1.webm …)
    seen_urls: set[str] = set()
    seen_filenames: dict[str, int] = {}
    unique = []
    for r in recordings:
        if r["url"] in seen_urls:
            continue
        seen_urls.add(r["url"])
        fn = r["filename"]
        if fn in seen_filenames:
            seen_filenames[fn] += 1
            stem = fn[:-5] if fn.endswith(".webm") else fn
            r["filename"] = f"{stem}_{seen_filenames[fn]}.webm"
        else:
            seen_filenames[fn] = 0
        unique.append(r)

    return unique


def scrape_recording_links_via_dom(page) -> list[dict]:
    """Fallback: extract all video-like links from the DOM."""
    recordings = []

    links_data = page.evaluate("""
        () => {
            const results = [];
            // Look for any links or references to .webm files
            document.querySelectorAll('a').forEach(a => {
                const href = a.href || '';
                const text = a.textContent.trim();
                if (href.includes('.webm') || href.includes('Recording') || href.includes('recording')) {
                    results.push({ href, text: text.substring(0, 200) });
                }
            });
            // Also check for video/source elements
            document.querySelectorAll('video source, video').forEach(v => {
                const src = v.src || v.getAttribute('src') || '';
                if (src) results.push({ href: src, text: 'video-element' });
            });
            return results;
        }
    """)

    for item in links_data:
        href = item["href"]
        text = item["text"]
        filename = Path(href.split("?")[0]).name if href else "unknown.webm"
        if not filename.endswith(".webm"):
            filename += ".webm"
        recordings.append({
            "title": text or filename,
            "url": href,
            "filename": filename,
        })

    seen = set()
    unique = []
    for r in recordings:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)
    return unique


def get_round_number(url: str) -> int | None:
    """Extract round number from a recording URL. Returns None for non-round recordings (mocks, scrums)."""
    decoded = url.replace("%20", " ").replace("%23", "#")
    match = re.search(r'\bR(\d+)\b', decoded)
    if match:
        return int(match.group(1))
    if re.search(r'\bRfinal\b', decoded, re.IGNORECASE):
        return 99
    return None


def sanitize_filename(name: str) -> str:
    """Make a string safe for use as a filename."""
    name = re.sub(r'[<>:"/\\|?*]', '-', name)
    name = re.sub(r'\s+', ' ', name).strip()
    if not name.lower().endswith(".webm"):
        name += ".webm"
    if len(name) > 200:
        name = name[:195] + ".webm"
    return name


def _requests_session(page):
    """Build a requests.Session authenticated with the Playwright browser's cookies."""
    import requests
    session = requests.Session()
    for cookie in page.context.cookies():
        session.cookies.set(cookie["name"], cookie["value"], domain=cookie.get("domain", ""))
    return session


def upload_to_gcs(session, url: str, filename: str, bucket_name: str, gcs_prefix: str) -> bool:
    """Stream a recording directly from Next IM into GCS without writing to disk."""
    try:
        from google.cloud import storage as gcs
    except ImportError:
        print("[ERROR] google-cloud-storage not installed. Run: pip install google-cloud-storage")
        return False

    blob_name = f"{gcs_prefix.rstrip('/')}/{filename}" if gcs_prefix else filename

    client = gcs.Client()
    bucket = client.bucket(bucket_name)
    blob = bucket.blob(blob_name)

    if blob.exists():
        print(f"  [SKIP] Already in GCS: gs://{bucket_name}/{blob_name}")
        return True

    print(f"  [UPLOADING] {filename} → gs://{bucket_name}/{blob_name} ...")
    try:
        with session.get(url, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            if "text/html" in resp.headers.get("content-type", ""):
                print(f"  [FAIL] {filename}: got HTML (auth may have expired)")
                return False
            with blob.open("wb") as gcs_file:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    gcs_file.write(chunk)
        size_mb = blob.size / (1024 * 1024) if blob.size else 0
        print(f"  [OK] {filename} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"  [FAIL] {filename}: {e}")
        return False


def download_recording(page, url: str, output_path: str) -> bool:
    """Download a single recording file to local disk."""
    output = Path(output_path)
    if output.exists() and output.stat().st_size > 1024 * 100:
        print(f"  [SKIP] Already exists: {output.name}")
        return True

    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        import requests
    except ImportError:
        print("[ERROR] requests not installed. Run: pip install requests")
        return False

    session = _requests_session(page)

    try:
        print(f"  [DOWNLOADING] {output.name}...")
        with session.get(url, stream=True, timeout=600) as resp:
            resp.raise_for_status()
            if "text/html" in resp.headers.get("content-type", ""):
                print(f"  [FAIL] {output.name}: got HTML (auth may have expired)")
                return False
            with open(output_path, "wb") as f:
                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                    f.write(chunk)
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"  [OK] {output.name} ({size_mb:.1f} MB)")
        return True
    except Exception as e:
        print(f"  [FAIL] {output.name}: {e}")
        if output.exists() and output.stat().st_size < 1024 * 100:
            output.unlink(missing_ok=True)
        return False


def main():
    parser = argparse.ArgumentParser(description="Scrape interview recordings from Next IM")
    parser.add_argument("--company", default="", help="Filter by company name in dropdown")
    parser.add_argument("--search", default="", help="Filter by search text")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Local output directory (ignored when --gcs-bucket is set)")
    parser.add_argument("--gcs-bucket", default=os.getenv("GCS_BUCKET", ""), help="GCS bucket name to upload recordings to")
    parser.add_argument("--gcs-prefix", default=os.getenv("GCS_PREFIX", "interview_recordings"), help="Folder prefix inside the GCS bucket")
    parser.add_argument("--drive", action="store_true", help="Upload recordings to Google Drive instead of local disk")
    parser.add_argument("--drive-folder", default=os.getenv("DRIVE_RECORDINGS_FOLDER", "interview_recordings"), help="Subfolder name inside the Drive interview-prep folder")
    parser.add_argument("--min-round", type=int, default=0, help="Only include recordings at this round or higher (e.g. 2 for R2+)")
    parser.add_argument("--limit", type=int, default=0, help="Max number of recordings to download (0 = all)")
    parser.add_argument("--list-only", action="store_true", help="List recordings without downloading")
    parser.add_argument("--pick", action="store_true", help="Interactively choose which recordings to download")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window (for manual login)")
    parser.add_argument("--use-chrome", action="store_true", help="Connect to your existing Chrome browser instead of opening a new one")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    if args.use_chrome:
        print("\n[INFO] To connect to your existing Chrome, you need to relaunch it with remote debugging enabled.")
        print("       Close Chrome completely, then run this command:\n")
        print('       "C:\\Program Files\\Google\\Chrome\\Application\\chrome.exe" --remote-debugging-port=9222 --user-data-dir="C:\\chrome-debug"\n')
        print("       Then navigate to nextim.itcapp.ai/recordings/interviews in that Chrome window,")
        print("       expand the list until all recordings are visible, then press Enter here.\n")
        input("       Press Enter when ready...")

    with sync_playwright() as p:
        headless = not args.no_headless
        browser, context = get_browser_context(p, headless=headless, use_existing_chrome=args.use_chrome)
        page = context.new_page() if not args.use_chrome else context.pages[0] if context.pages else context.new_page()

        try:
            if args.use_chrome:
                pass  # user already logged in and expanded the list
            elif args.no_headless:
                manual_login(page)
            else:
                login_if_needed(page)

            save_auth_state(context)

            if not page.url.startswith(NEXTIM_BASE_URL + "/recordings"):
                page.goto(RECORDINGS_URL, wait_until="networkidle", timeout=30000)
                time.sleep(2)

            if args.company:
                select_company_filter(page, args.company)

            if args.search:
                apply_search_filter(page, args.search)

            print("\n[INFO] Expand the recordings list in the browser (click 'show more' until all are visible).")
            input("      Press Enter here when ready to scrape...\n")

            print("[INFO] Scanning for recordings...")
            recordings = scrape_recording_cards(page)

            if not recordings:
                print("[INFO] No card-based recordings found, trying DOM scan...")
                recordings = scrape_recording_links_via_dom(page)

            if not recordings:
                print("[WARN] No recordings found. Try --no-headless to verify the page loads correctly.")
                browser.close()
                return

            if args.min_round > 0:
                before = len(recordings)
                recordings = [r for r in recordings if (rn := get_round_number(r["url"])) is not None and rn >= args.min_round]
                print(f"[INFO] Round filter (>= R{args.min_round}): {before} -> {len(recordings)} recordings")

            print(f"\n[INFO] Found {len(recordings)} recording(s):\n")
            for i, rec in enumerate(recordings, 1):
                print(f"  {i}. {rec['title']}")
                print(f"     URL: {rec['url']}")
                print()

            if args.list_only:
                browser.close()
                return

            if not args.pick:
                selected = recordings
            else:
                print("Enter the numbers of recordings to download (comma-separated, e.g. 1,3,5):")
                choice = input("> ").strip()
                indices = []
                for part in choice.split(","):
                    part = part.strip()
                    if "-" in part:
                        lo, hi = part.split("-", 1)
                        indices.extend(range(int(lo), int(hi) + 1))
                    else:
                        indices.append(int(part))
                selected = [recordings[i - 1] for i in indices if 1 <= i <= len(recordings)]
                if not selected:
                    print("[WARN] No valid selections. Exiting.")
                    browser.close()
                    return

            output_dir = Path(args.output)
            output_dir.mkdir(parents=True, exist_ok=True)

            if args.limit > 0:
                selected = selected[:args.limit]

            recordings = selected

            success = 0
            if args.drive:
                from drive import upload_video_stream
                session = _requests_session(page)
                drive_folder = os.getenv("GOOGLE_DRIVE_FOLDER_NAME", "interview-prep")
                print(f"\n[INFO] Uploading {len(recordings)} recording(s) to Google Drive ({drive_folder}/{args.drive_folder})...\n")
                import tempfile
                for rec in recordings:
                    print(f"  [UPLOADING] {rec['filename']} ...")
                    tmp_path = None
                    try:
                        with session.get(rec["url"], stream=True, timeout=600) as resp:
                            resp.raise_for_status()
                            if "text/html" in resp.headers.get("content-type", ""):
                                print(f"  [FAIL] {rec['filename']}: got HTML (auth may have expired)")
                                continue
                            with tempfile.NamedTemporaryFile(delete=False, suffix=".webm") as tmp:
                                tmp_path = tmp.name
                                for chunk in resp.iter_content(chunk_size=8 * 1024 * 1024):
                                    tmp.write(chunk)
                        size_mb = Path(tmp_path).stat().st_size / (1024 * 1024)
                        with open(tmp_path, "rb") as f:
                            file_id = upload_video_stream(f, rec["filename"], args.drive_folder)
                        print(f"  [OK] {rec['filename']} ({size_mb:.1f} MB, Drive ID: {file_id})")
                        success += 1
                    except Exception as e:
                        print(f"  [FAIL] {rec['filename']}: {e}")
                    finally:
                        if tmp_path and Path(tmp_path).exists():
                            Path(tmp_path).unlink()
                print(f"\n[DONE] Uploaded {success}/{len(recordings)} recordings to Google Drive.")
            elif args.gcs_bucket:
                print(f"\n[INFO] Uploading {len(recordings)} recording(s) to gs://{args.gcs_bucket}/{args.gcs_prefix}/...\n")
                session = _requests_session(page)
                for rec in recordings:
                    if upload_to_gcs(session, rec["url"], rec["filename"], args.gcs_bucket, args.gcs_prefix):
                        success += 1
                print(f"\n[DONE] Uploaded {success}/{len(recordings)} recordings to GCS.")
            else:
                output_dir = Path(args.output)
                output_dir.mkdir(parents=True, exist_ok=True)
                print(f"\n[INFO] Downloading {len(recordings)} recording(s) to {output_dir.resolve()}...\n")
                for rec in recordings:
                    out_path = str(output_dir / rec["filename"])
                    if download_recording(page, rec["url"], out_path):
                        success += 1
                print(f"\n[DONE] Downloaded {success}/{len(recordings)} recordings.")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
