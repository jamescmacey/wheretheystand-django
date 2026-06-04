"""
Download original-resolution images from Wikimedia Commons file page URLs in a CSV.

Uses a two-phase workflow to avoid Commons API rate limits:
  1. resolve  — query the API in small batches, save URLs to a manifest JSON
  2. download — fetch files from upload.wikimedia.org using the manifest only

Re-run after failures with --download-only (no API calls) once the manifest exists.
"""

import csv
import json
import mimetypes
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils.text import slugify

DEFAULT_CSV = "migration/people_without_photos.csv"
DEFAULT_OUTPUT_DIR = "migration/wikimedia_photos"
DEFAULT_MANIFEST = "migration/wikimedia_photos/manifest.json"
URL_COLUMN = "Photo URL identified"
DISPLAY_NAME_COLUMN = "display_name"
COMMONS_API = "https://commons.wikimedia.org/w/api.php"


def _normalize_column_key(key):
    return (key or "").strip().lower()


def _get_row_value(row, column_name):
    target = _normalize_column_key(column_name)
    for key, value in row.items():
        if _normalize_column_key(key) == target:
            return (value or "").strip()
    return ""


def _commons_page_url_to_title(page_url):
    parsed = urllib.parse.urlparse(page_url)
    host = (parsed.netloc or "").lower()
    if host not in ("commons.wikimedia.org", "www.commons.wikimedia.org"):
        raise ValueError(f"Not a Wikimedia Commons file page URL: {page_url}")

    path = urllib.parse.unquote(parsed.path or "")
    prefix = "/wiki/"
    if not path.startswith(prefix):
        raise ValueError(f"Unexpected Commons URL path: {page_url}")

    title = path[len(prefix) :]
    if not title.startswith("File:"):
        raise ValueError(f"URL is not a File: page: {page_url}")
    return title


def _filename_from_title(title):
    if title.startswith("File:"):
        return title[5:]
    return title


def _wait_seconds_for_429(exc, attempt, base_wait):
    if isinstance(exc, urllib.error.HTTPError) and exc.code == 429:
        retry_after = exc.headers.get("Retry-After") if exc.headers else None
        if retry_after:
            try:
                return max(int(retry_after), base_wait)
            except ValueError:
                pass
        return min(300, base_wait * (2**attempt))
    return base_wait


def _urlopen_with_retry(req, timeout, max_retries=8, base_wait=15):
    last_exc = None
    for attempt in range(max_retries):
        try:
            return urllib.request.urlopen(req, timeout=timeout)
        except urllib.error.HTTPError as exc:
            last_exc = exc
            if exc.code == 429 and attempt < max_retries - 1:
                wait = _wait_seconds_for_429(exc, attempt, base_wait)
                time.sleep(wait)
                continue
            raise
        except urllib.error.URLError as exc:
            last_exc = exc
            if attempt < max_retries - 1:
                time.sleep(min(60, base_wait * (2**attempt)))
                continue
            raise
    raise last_exc  # pragma: no cover


def _fetch_image_info_batch(titles, user_agent):
    """Return dict mapping File: title -> {url, size}."""
    if not titles:
        return {}

    params = urllib.parse.urlencode(
        {
            "action": "query",
            "format": "json",
            "prop": "imageinfo",
            "iiprop": "url|size",
            "titles": "|".join(titles),
        }
    )
    req = urllib.request.Request(f"{COMMONS_API}?{params}")
    req.add_header("User-Agent", user_agent)

    with _urlopen_with_retry(req, timeout=60, base_wait=30) as response:
        payload = json.loads(response.read().decode("utf-8"))

    resolved = {}
    for page in payload.get("query", {}).get("pages", {}).values():
        if page.get("missing") or "imageinfo" not in page:
            continue
        info = page["imageinfo"][0]
        resolved[page["title"]] = {
            "url": info["url"],
            "size": info.get("size"),
        }
    return resolved


def _resolve_via_special_filepath(filename, user_agent):
    """
    Fallback: follow Special:FilePath redirect (no API).
    Returns upload.wikimedia.org URL or raises.
    """
    path_segment = urllib.parse.quote(filename.replace(" ", "_"), safe="/")
    page_url = f"https://commons.wikimedia.org/wiki/Special:FilePath/{path_segment}"
    req = urllib.request.Request(page_url)
    req.add_header("User-Agent", user_agent)
    opener = urllib.request.build_opener(urllib.request.HTTPRedirectHandler())
    with opener.open(req, timeout=60) as response:
        final_url = response.geturl()
    if "upload.wikimedia.org" not in final_url:
        raise ValueError(f"Unexpected redirect target: {final_url}")
    return final_url


def _download_file(url, dest_path, user_agent):
    req = urllib.request.Request(url)
    req.add_header("User-Agent", user_agent)
    with _urlopen_with_retry(req, timeout=120, base_wait=20) as response:
        content = response.read()
        if not content:
            raise ValueError("Empty response")
    dest_path.parent.mkdir(parents=True, exist_ok=True)
    dest_path.write_bytes(content)
    return len(content)


def _extension_from_url(url):
    path = urllib.parse.urlparse(url).path
    ext = os.path.splitext(path)[1].lower()
    if ext in (".jpg", ".jpeg", ".png", ".gif", ".webp", ".tif", ".tiff", ".svg"):
        return ext
    return ".jpg"


def _load_manifest(path):
    if not path.exists():
        return {}
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _save_manifest(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(data, fh, indent=2, ensure_ascii=False)
        fh.write("\n")


class Command(BaseCommand):
    help = (
        "Download original-resolution files from Wikimedia Commons URLs in a CSV. "
        "Resolves URLs via a cached manifest (small API batches) then downloads "
        "from upload.wikimedia.org. Use --download-only to retry without API calls."
    )

    def add_arguments(self, parser):
        parser.add_argument(
            "--csv",
            default=DEFAULT_CSV,
            help=f"Input CSV path (default: {DEFAULT_CSV}).",
        )
        parser.add_argument(
            "--output-dir",
            default=DEFAULT_OUTPUT_DIR,
            help=f"Directory for downloaded originals (default: {DEFAULT_OUTPUT_DIR}).",
        )
        parser.add_argument(
            "--manifest",
            default=DEFAULT_MANIFEST,
            help=f"JSON cache of resolved download URLs (default: {DEFAULT_MANIFEST}).",
        )
        parser.add_argument(
            "--output-csv",
            help="Optional results CSV path.",
        )
        parser.add_argument(
            "--resolve-only",
            action="store_true",
            help="Only resolve Commons URLs to manifest; do not download files.",
        )
        parser.add_argument(
            "--download-only",
            action="store_true",
            help="Only download using an existing manifest (no API calls).",
        )
        parser.add_argument(
            "--overwrite",
            action="store_true",
            help="Re-download files that already exist on disk.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Print planned actions without downloading.",
        )
        parser.add_argument(
            "--api-batch-size",
            type=int,
            default=5,
            help="File titles per Commons API request (default: 5).",
        )
        parser.add_argument(
            "--api-delay",
            type=float,
            default=25.0,
            help="Seconds between Commons API batch requests (default: 25).",
        )
        parser.add_argument(
            "--download-delay",
            type=float,
            default=8.0,
            help="Seconds between file downloads (default: 8).",
        )
        parser.add_argument(
            "--resolve-fallback",
            action="store_true",
            help=(
                "If API resolve fails for a title, try Special:FilePath redirect "
                "(one Commons request per file; slower but no API quota)."
            ),
        )

    def handle(self, *args, **options):
        if options["resolve_only"] and options["download_only"]:
            raise CommandError("Use only one of --resolve-only or --download-only.")

        csv_path = options["csv"]
        output_dir = Path(options["output_dir"])
        manifest_path = Path(options["manifest"])
        output_csv = options.get("output_csv")
        overwrite = options["overwrite"]
        dry_run = options["dry_run"]
        resolve_only = options["resolve_only"]
        download_only = options["download_only"]
        api_batch_size = max(1, options["api_batch_size"])
        api_delay = options["api_delay"]
        download_delay = options["download_delay"]
        resolve_fallback = options["resolve_fallback"]

        user_agent = getattr(
            settings,
            "BOT_USER_AGENT",
            "WhereTheyStand/2.0 (https://wheretheystand.nz; migration bot)",
        )

        if not os.path.exists(csv_path):
            raise CommandError(f"CSV file does not exist: {csv_path}")

        jobs = self._load_jobs(csv_path)
        if not jobs:
            self.stdout.write(self.style.WARNING("No Wikimedia URLs found in CSV."))
            return

        manifest = _load_manifest(manifest_path)

        if not download_only:
            manifest = self._resolve_manifest(
                jobs,
                manifest,
                manifest_path,
                user_agent,
                api_batch_size,
                api_delay,
                resolve_fallback,
                dry_run,
            )

        if resolve_only:
            self.stdout.write(
                self.style.SUCCESS(
                    f"Resolve complete. Manifest: {manifest_path} "
                    f"({len(manifest)} entries)"
                )
            )
            return

        if download_only and not manifest_path.exists():
            raise CommandError(
                f"Manifest not found: {manifest_path}. Run without --download-only first."
            )

        downloaded, skipped, errors, results = self._download_all(
            jobs,
            manifest,
            output_dir,
            user_agent,
            overwrite,
            dry_run,
            download_delay,
        )

        if output_csv and results:
            self._write_results_csv(output_csv, results)

        summary = (
            f"Done. {downloaded} downloaded"
            + (" (dry run)" if dry_run else "")
            + f", {skipped} skipped, {errors} errors."
        )
        if output_csv and results:
            summary += f" Results: {output_csv}"
        self.stdout.write(self.style.SUCCESS(summary))

    def _load_jobs(self, csv_path):
        jobs = []
        with open(csv_path, encoding="utf-8-sig", newline="") as fh:
            reader = csv.DictReader(fh)
            if not reader.fieldnames:
                raise CommandError("CSV has no header row.")
            rows = list(reader)

        for row_num, row in enumerate(rows, start=2):
            page_url = _get_row_value(row, URL_COLUMN)
            display_name = _get_row_value(row, DISPLAY_NAME_COLUMN) or f"row-{row_num}"
            if not page_url or "wikimedia.org" not in page_url.lower():
                continue
            try:
                title = _commons_page_url_to_title(page_url)
            except ValueError as exc:
                self.stdout.write(self.style.ERROR(f"Skipping {display_name}: {exc}"))
                continue
            jobs.append(
                {
                    "row": row,
                    "page_url": page_url,
                    "title": title,
                    "display_name": display_name,
                    "slug": slugify(display_name) or f"person-{row_num}",
                }
            )
        return jobs

    def _resolve_manifest(
        self,
        jobs,
        manifest,
        manifest_path,
        user_agent,
        api_batch_size,
        api_delay,
        resolve_fallback,
        dry_run,
    ):
        titles_needed = []
        for job in jobs:
            entry = manifest.get(job["title"])
            if entry and entry.get("url"):
                continue
            titles_needed.append(job["title"])

        unique_needed = list(dict.fromkeys(titles_needed))
        if not unique_needed:
            self.stdout.write("All titles already in manifest.")
            return manifest

        self.stdout.write(
            f"Resolving {len(unique_needed)} file(s) via API "
            f"(batch size {api_batch_size}, {api_delay}s between batches)..."
        )

        for batch_start in range(0, len(unique_needed), api_batch_size):
            batch = unique_needed[batch_start : batch_start + api_batch_size]
            if batch_start > 0 and api_delay and not dry_run:
                self.stdout.write(f"Waiting {api_delay}s before next API batch...")
                time.sleep(api_delay)

            if dry_run:
                for title in batch:
                    self.stdout.write(f"Would resolve API: {title}")
                continue

            try:
                resolved = _fetch_image_info_batch(batch, user_agent)
            except urllib.error.HTTPError as exc:
                self.stdout.write(
                    self.style.ERROR(
                        f"API batch failed ({exc}). "
                        f"Wait and re-run, or use --resolve-fallback for missing titles."
                    )
                )
                resolved = {}

            for title in batch:
                info = resolved.get(title)
                if info:
                    manifest[title] = {
                        "url": info["url"],
                        "size": info.get("size"),
                        "page_url": next(
                            (j["page_url"] for j in jobs if j["title"] == title), ""
                        ),
                        "resolved_via": "api",
                    }
                    self.stdout.write(self.style.SUCCESS(f"Resolved: {title}"))
                    continue

                if resolve_fallback:
                    if api_delay:
                        time.sleep(max(api_delay / 2, 5))
                    try:
                        filename = _filename_from_title(title)
                        url = _resolve_via_special_filepath(filename, user_agent)
                        manifest[title] = {
                            "url": url,
                            "page_url": next(
                                (j["page_url"] for j in jobs if j["title"] == title), ""
                            ),
                            "resolved_via": "special_filepath",
                        }
                        self.stdout.write(
                            self.style.SUCCESS(f"Resolved (redirect): {title}")
                        )
                    except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
                        self.stdout.write(
                            self.style.ERROR(f"Could not resolve {title}: {exc}")
                        )
                else:
                    self.stdout.write(self.style.ERROR(f"Could not resolve: {title}"))

            if not dry_run:
                _save_manifest(manifest_path, manifest)

        return manifest

    def _download_all(
        self,
        jobs,
        manifest,
        output_dir,
        user_agent,
        overwrite,
        dry_run,
        download_delay,
    ):
        downloaded = 0
        skipped = 0
        errors = 0
        results = []

        pending = [
            j
            for j in jobs
            if manifest.get(j["title"], {}).get("url")
            and not (
                (output_dir / f"{j['slug']}{_extension_from_url(manifest[j['title']]['url'])}").exists()
                and not overwrite
            )
        ]
        self.stdout.write(
            f"Downloading: {len(pending)} remaining "
            f"({len(jobs) - len(pending)} already on disk or missing from manifest)."
        )

        download_attempts = 0
        for job in jobs:
            title = job["title"]
            display_name = job["display_name"]
            page_url = job["page_url"]
            entry = manifest.get(title) or {}
            original_url = entry.get("url")

            result_row = dict(job["row"])
            result_row["commons_page_url"] = page_url
            result_row["commons_file_title"] = title

            if not original_url:
                errors += 1
                result_row["status"] = "error"
                result_row["error"] = "Not in manifest; run resolve first"
                results.append(result_row)
                continue

            result_row["original_download_url"] = original_url
            result_row["original_bytes"] = entry.get("size") or ""

            ext = _extension_from_url(original_url)
            dest_path = output_dir / f"{job['slug']}{ext}"

            if dest_path.exists() and not overwrite:
                skipped += 1
                result_row["local_file"] = str(dest_path)
                result_row["status"] = "skipped_exists"
                results.append(result_row)
                continue

            if dry_run:
                downloaded += 1
                result_row["local_file"] = str(dest_path)
                result_row["status"] = "dry_run"
                self.stdout.write(
                    f"Would download {display_name}: {original_url} -> {dest_path}"
                )
                results.append(result_row)
                continue

            try:
                if download_attempts > 0 and download_delay:
                    time.sleep(download_delay)
                download_attempts += 1
                nbytes = _download_file(original_url, dest_path, user_agent)
                downloaded += 1
                result_row["local_file"] = str(dest_path)
                result_row["status"] = "downloaded"
                result_row["downloaded_bytes"] = nbytes
                mime, _ = mimetypes.guess_type(str(dest_path))
                self.stdout.write(
                    self.style.SUCCESS(
                        f"Downloaded {display_name}: {nbytes:,} bytes -> {dest_path}"
                        + (f" ({mime})" if mime else "")
                    )
                )
            except (urllib.error.HTTPError, urllib.error.URLError, ValueError) as exc:
                errors += 1
                result_row["status"] = "error"
                result_row["error"] = str(exc)
                self.stdout.write(
                    self.style.ERROR(f"Error for {display_name}: {exc}")
                )

            results.append(result_row)

        return downloaded, skipped, errors, results

    def _write_results_csv(self, output_csv, results):
        fieldnames = list(results[0].keys())
        for row in results[1:]:
            for key in row:
                if key not in fieldnames:
                    fieldnames.append(key)
        out_dir = os.path.dirname(output_csv)
        if out_dir:
            os.makedirs(out_dir, exist_ok=True)
        with open(output_csv, "w", encoding="utf-8", newline="") as fh:
            writer = csv.DictWriter(fh, fieldnames=fieldnames, extrasaction="ignore")
            writer.writeheader()
            writer.writerows(results)
