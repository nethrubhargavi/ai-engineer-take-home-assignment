"""Extract structured lab results from a lab report.

Usage:
    python extract.py reports/report_01.pdf

Prints JSON matching schema.json to stdout.
"""
from dotenv import load_dotenv
import base64
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
import json
import math
import os
import random
import re
import subprocess
import sys
import tempfile
import time
import urllib.error
import urllib.request
from pathlib import Path
load_dotenv()
API_KEY = os.environ.get("GEMINI_API_KEY")
MODEL = os.environ.get("GEMINI_MODEL", "gemini-3.8-flash")
DPI = 150

PROMPT = """You are an expert at reading medical lab reports.

Look at this lab report and extract every test result from it.

Return JSON in exactly this format:
{"tests": [{"test_name": "...", "value": 0.0 or "...", "unit": "...", "reference_range": "...", "status": "normal"}]}

Rules:
- Use the standard medical name for each test.
- Use a number for a single numeric result. If the report prints a range, comparison, or qualitative result, return it as a string exactly as printed. Do not replace ranges with midpoints or qualitative results with numbers.
- If a reference range is missing from the report, fill in the standard reference range for that test.
- status is "normal", "high" or "low", based on the value and the reference range.
- Be thorough. Do not miss any tests.
"""

MEDIA_TYPES = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png"}
RETRYABLE_HTTP_CODES = {429, 503}
MAX_RETRIES = 3
BASE_RETRY_DELAY_SECONDS = 1.0
MAX_BACKOFF_SECONDS = 30.0
MAX_SERVER_RETRY_DELAY_SECONDS = 60.0


def load_images(path: Path) -> list[tuple[str, str]]:
    """Return (media_type, base64 data) for each report page/image."""
    if path.suffix.lower() == ".pdf":
        with tempfile.TemporaryDirectory() as directory:
            prefix = Path(directory) / "page"
            try:
                subprocess.run(["pdftoppm", "-r", str(DPI), "-png", str(path), str(prefix)],
                               check=True, capture_output=True)
            except FileNotFoundError:
                raise RuntimeError("Install Poppler (pdftoppm); see README.md.") from None
            pages = sorted(prefix.parent.glob("page-*.png"), key=lambda page: int(page.stem.rsplit("-", 1)[1]))
            if not pages:
                raise RuntimeError(f"Could not render any pages from {path}.")
            return [
                ("image/png", base64.standard_b64encode(page.read_bytes()).decode())
                for page in pages
            ]
    return [(MEDIA_TYPES[path.suffix.lower()], base64.standard_b64encode(path.read_bytes()).decode())]


def parse_retry_after(value: str | None, now: datetime | None = None) -> float | None:
    """Parse Retry-After as seconds or an HTTP date."""
    if not value:
        return None
    try:
        seconds = float(value)
        return max(0.0, seconds) if math.isfinite(seconds) else None
    except ValueError:
        pass
    try:
        retry_at = parsedate_to_datetime(value)
    except (TypeError, ValueError, OverflowError):
        return None
    if retry_at.tzinfo is None:
        retry_at = retry_at.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    if now.tzinfo is None:
        now = now.replace(tzinfo=timezone.utc)
    return max(0.0, (retry_at - now).total_seconds())


def parse_retry_info_delay(body: bytes) -> float | None:
    """Read a google.rpc.RetryInfo delay from a Google API error body."""
    try:
        error = json.loads(body).get("error", {})
    except (json.JSONDecodeError, UnicodeDecodeError, AttributeError):
        return None
    delays = []
    for detail in error.get("details", []):
        if not isinstance(detail, dict) or not str(detail.get("@type", "")).endswith("google.rpc.RetryInfo"):
            continue
        delay = detail.get("retryDelay", detail.get("retry_delay"))
        if isinstance(delay, dict):
            try:
                seconds = float(delay.get("seconds", 0)) + float(delay.get("nanos", 0)) / 1_000_000_000
            except (TypeError, ValueError, OverflowError):
                continue
        elif isinstance(delay, str):
            match = re.fullmatch(r"\s*(\d+(?:\.\d+)?)s\s*", delay)
            if not match:
                continue
            seconds = float(match.group(1))
        else:
            continue
        if math.isfinite(seconds) and seconds >= 0:
            delays.append(seconds)
    return max(delays) if delays else None


def server_retry_delay(error: urllib.error.HTTPError) -> float | None:
    """Return the longest server-provided retry delay, if any."""
    delays = []
    headers = error.headers
    if headers is not None:
        header_delay = parse_retry_after(headers.get("Retry-After"))
        if header_delay is not None:
            delays.append(header_delay)
    try:
        body = error.read()
    except OSError:
        body = b""
    body_delay = parse_retry_info_delay(body)
    if body_delay is not None:
        delays.append(body_delay)
    return max(delays) if delays else None


def retry_delay(retry_index: int, server_delay: float | None) -> float:
    """Use exponential full jitter, or jitter after the server's minimum delay."""
    if server_delay is None:
        ceiling = min(MAX_BACKOFF_SECONDS, BASE_RETRY_DELAY_SECONDS * (2 ** retry_index))
        return random.uniform(0.0, ceiling)
    jitter = min(
        1.0,
        max(0.1, server_delay * 0.1),
        max(0.0, MAX_SERVER_RETRY_DELAY_SECONDS - server_delay),
    )
    return server_delay + random.uniform(0.0, jitter)


def call_model(images: list[tuple[str, str]]) -> str:
    key = os.environ.get("GEMINI_API_KEY")
    if not key:
        raise RuntimeError("Set GEMINI_API_KEY; see README.md. No API call made.")
    body = {
        "contents": [{"role": "user", "parts": [
            *({"inlineData": {"mimeType": media_type, "data": data}}
              for media_type, data in images),
            {"text": PROMPT},
        ]}],
        "generationConfig": {"temperature": 0, "maxOutputTokens": 16000},
    }
    request_body = json.dumps(body).encode()
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{MODEL}:generateContent"
    result = None
    for attempt in range(MAX_RETRIES + 1):
        request = urllib.request.Request(
            url, data=request_body,
            headers={"x-goog-api-key": key, "Content-Type": "application/json"},
        )
        try:
            with urllib.request.urlopen(request, timeout=180) as response:
                result = json.load(response)
            break
        except urllib.error.HTTPError as error:
            if error.code not in RETRYABLE_HTTP_CODES:
                raise RuntimeError(
                    f"Gemini HTTP {error.code}; check API access, model and quota. See README.md."
                ) from None
            if attempt >= MAX_RETRIES:
                reason = "rate limit or quota" if error.code == 429 else "service unavailable"
                raise RuntimeError(
                    f"Gemini HTTP {error.code} after {MAX_RETRIES} retries; {reason} persists. "
                    "Check API status, project limits and quota, then retry later."
                ) from None
            delay = server_retry_delay(error)
            if delay is not None and delay > MAX_SERVER_RETRY_DELAY_SECONDS:
                raise RuntimeError(
                    f"Gemini HTTP {error.code}; server requested retry after {delay:.1f}s, "
                    f"beyond the {MAX_SERVER_RETRY_DELAY_SECONDS:.0f}s automatic wait limit. "
                    "Retry manually later."
                ) from None
            time.sleep(retry_delay(attempt, delay))
        except urllib.error.URLError:
            raise RuntimeError("Gemini connection failed; check network/TLS access and retry. See README.md.") from None
    candidate = result.get("candidates", [{}])[0]
    return "".join(part["text"] for part in candidate.get("content", {}).get("parts", [])
                   if "text" in part and not part.get("thought"))


class ResponseParseError(RuntimeError):
    """Raised when the model response is not a JSON object with a tests array."""


def parse(text: str) -> list[dict]:
    match = re.search(r"\{.*\}", text, re.DOTALL)
    if match is None:
        raise ResponseParseError("Gemini response did not contain a JSON object.")
    try:
        result = json.loads(match.group(0))
    except json.JSONDecodeError as error:
        raise ResponseParseError(
            "Gemini response contained malformed or truncated JSON "
            f"(line {error.lineno}, column {error.colno}: {error.msg})."
        ) from error
    if not isinstance(result, dict) or not isinstance(result.get("tests"), list):
        raise ResponseParseError("Gemini response JSON must be an object containing a 'tests' array.")
    return result["tests"]


def to_number(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def clean(tests: list[dict]) -> list[dict]:
    out = []
    seen = set()
    for t in tests:
        raw_value = t.get("value")
        number_value = to_number(raw_value)
        value = number_value if number_value is not None else (
            raw_value if isinstance(raw_value, str) else None
        )
        row = {
            "test_name": str(t.get("test_name", "")).strip(),
            "value": value,
            "unit": t.get("unit") or None,
            "reference_range": t.get("reference_range") or None,
            "status": t.get("status"),
        }
        key = (
            " ".join(row["test_name"].casefold().split()), row["value"],
            " ".join(str(row["unit"] or "").casefold().split()),
        )
        if key not in seen:
            seen.add(key)
            out.append(row)
    return out


def extract(path: Path) -> dict:
    images = load_images(path)
    return {"tests": clean(parse(call_model(images)))}


if __name__ == "__main__":
    if len(sys.argv) != 2:
        sys.exit(__doc__)
    try:
        print(json.dumps(extract(Path(sys.argv[1])), indent=2, ensure_ascii=False))
    except RuntimeError as error:
        sys.exit(str(error))
