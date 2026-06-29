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


def get_browser_context(playwright, headless=True):
    """Launch browser and return a context with stored auth state if available."""
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


def scrape_recording_cards(page) -> list[dict]:
    """Extract recording info from the current page."""
    recordings = []

    cards = page.locator("a[href*='Recording'], div:has(a[href*='.webm']), [class*='card'], [class*='recording']")

    if cards.count() == 0:
        links = page.locator("a[href*='.webm']")
        for i in range(links.count()):
            link = links.nth(i)
            href = link.get_attribute("href") or ""
            text = link.inner_text().strip()
            recordings.append({
                "title": text or Path(href).stem,
                "url": urljoin(NEXTIM_BASE_URL, href),
                "filename": Path(href).name,
            })
        return recordings

    all_links = page.locator("a")
    for i in range(all_links.count()):
        link = all_links.nth(i)
        href = link.get_attribute("href") or ""
        if ".webm" in href or "Recording" in href:
            text = link.inner_text().strip()
            if not text:
                text = link.locator("..").inner_text().strip()[:100]
            filename = Path(href).name if "." in Path(href).name else href.split("/")[-1] + ".webm"
            recordings.append({
                "title": text or filename,
                "url": urljoin(NEXTIM_BASE_URL, href),
                "filename": sanitize_filename(text or filename),
            })

    # Deduplicate by URL
    seen = set()
    unique = []
    for r in recordings:
        if r["url"] not in seen:
            seen.add(r["url"])
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
            "filename": sanitize_filename(text if text != "video-element" else filename),
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


def download_recording(page, url: str, output_path: str) -> bool:
    """Download a single recording file."""
    output = Path(output_path)
    if output.exists() and output.stat().st_size > 0:
        print(f"  [SKIP] Already exists: {output.name}")
        return True

    output.parent.mkdir(parents=True, exist_ok=True)

    try:
        with page.expect_download(timeout=600000) as download_info:
            page.evaluate(f"""
                () => {{
                    const a = document.createElement('a');
                    a.href = '{url}';
                    a.download = '';
                    document.body.appendChild(a);
                    a.click();
                    a.remove();
                }}
            """)
        download = download_info.value
        download.save_as(output_path)
        size_mb = output.stat().st_size / (1024 * 1024)
        print(f"  [OK] {output.name} ({size_mb:.1f} MB)")
        return True
    except Exception:
        # Fallback: use request context to download directly
        try:
            response = page.context.request.get(url, timeout=600000)
            if response.ok:
                with open(output_path, "wb") as f:
                    f.write(response.body())
                size_mb = output.stat().st_size / (1024 * 1024)
                print(f"  [OK] {output.name} ({size_mb:.1f} MB)")
                return True
            else:
                print(f"  [FAIL] HTTP {response.status} for {output.name}")
                return False
        except Exception as e2:
            print(f"  [FAIL] {output.name}: {e2}")
            return False


def main():
    parser = argparse.ArgumentParser(description="Scrape interview recordings from Next IM")
    parser.add_argument("--company", default="", help="Filter by company name in dropdown")
    parser.add_argument("--search", default="", help="Filter by search text")
    parser.add_argument("--output", default=DEFAULT_OUTPUT, help="Output directory for downloads")
    parser.add_argument("--limit", type=int, default=0, help="Max number of recordings to download (0 = all)")
    parser.add_argument("--list-only", action="store_true", help="List recordings without downloading")
    parser.add_argument("--pick", action="store_true", help="Interactively choose which recordings to download")
    parser.add_argument("--no-headless", action="store_true", help="Show browser window (for manual login)")
    parser.add_argument("--min-round", type=int, default=0, help="Only include recordings at or above this round (e.g. --min-round 2 keeps R2, R3, R4, Rfinal)")
    args = parser.parse_args()

    try:
        from playwright.sync_api import sync_playwright
    except ImportError:
        print("[ERROR] playwright not installed. Run: pip install playwright && playwright install chromium")
        sys.exit(1)

    with sync_playwright() as p:
        headless = not args.no_headless
        browser, context = get_browser_context(p, headless=headless)
        page = context.new_page()

        try:
            if args.no_headless:
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

            print("\n[INFO] Scanning for recordings...")
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
            print(f"\n[INFO] Downloading {len(recordings)} recording(s) to {output_dir.resolve()}...\n")
            success = 0
            for rec in recordings:
                out_path = str(output_dir / rec["filename"])
                if download_recording(page, rec["url"], out_path):
                    success += 1

            print(f"\n[DONE] Downloaded {success}/{len(recordings)} recordings.")

        finally:
            browser.close()


if __name__ == "__main__":
    main()
