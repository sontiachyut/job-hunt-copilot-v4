#!/usr/bin/env python3
"""Extract Jobright connections using the logged-in Comet browser session."""

from __future__ import annotations

import argparse
import hashlib
import json
import shutil
import sqlite3
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import requests
from cryptography.hazmat.primitives.ciphers import Cipher, algorithms, modes

from jobright_extract_connections import (
    build_cookie_jar,
    extract_from_next_data,
    extract_next_data,
    extract_title,
    now_utc,
)


CHROME_EPOCH_OFFSET_SECONDS = 11_644_473_600
DEFAULT_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/149.0.0.0 Safari/537.36"
)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description=(
            "Reuse the logged-in Comet browser session to fetch a Jobright job "
            "page and extract personalized connections without UI automation."
        )
    )
    parser.add_argument("--job-url", required=True, help="Jobright job detail URL.")
    parser.add_argument("--output", required=True, help="Path to write the extracted JSON.")
    parser.add_argument(
        "--comet-root",
        default=str(Path.home() / "Library/Application Support/Comet"),
        help="Comet profile root directory. Default: %(default)s",
    )
    parser.add_argument(
        "--profile-name",
        default="Default",
        help="Comet profile directory name. Default: %(default)s",
    )
    parser.add_argument(
        "--safe-storage-service",
        default="Comet Safe Storage",
        help="Keychain service name for the Comet Safe Storage key. Default: %(default)s",
    )
    parser.add_argument(
        "--safe-storage-account",
        default="Comet",
        help="Keychain account name for the Comet Safe Storage key. Default: %(default)s",
    )
    parser.add_argument(
        "--user-agent",
        default=DEFAULT_USER_AGENT,
        help="HTTP user agent for the replayed browser session. Default: Chrome 149 on macOS.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=30,
        help="HTTP timeout in seconds. Default: %(default)s",
    )
    return parser.parse_args()


def ensure_parent(path_str: str) -> Path:
    path = Path(path_str).expanduser().resolve()
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def chrome_expires_to_unix(expires_utc: int) -> int:
    if expires_utc <= 0:
        return -1
    return max(0, int(expires_utc / 1_000_000 - CHROME_EPOCH_OFFSET_SECONDS))


def get_safe_storage_secret(service: str, account: str) -> str:
    result = subprocess.run(
        ["security", "find-generic-password", "-w", "-s", service, "-a", account],
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode != 0:
        stderr = result.stderr.strip() or result.stdout.strip() or "unknown keychain error"
        raise RuntimeError(
            f"Could not read the {service} key from Keychain: {stderr}"
        )
    return result.stdout.strip()


def derive_cookie_key(secret: str) -> bytes:
    return hashlib.pbkdf2_hmac("sha1", secret.encode("utf-8"), b"saltysalt", 1003, dklen=16)


def decrypt_chromium_cookie(host_key: str, encrypted_value: bytes, key: bytes) -> str:
    if not encrypted_value:
        return ""

    if encrypted_value.startswith(b"v10"):
        iv = b" " * 16
        cipher = Cipher(algorithms.AES(key), modes.CBC(iv)).decryptor()
        plaintext = cipher.update(encrypted_value[3:]) + cipher.finalize()
        pad_length = plaintext[-1]
        plaintext = plaintext[:-pad_length]
        host_digest = hashlib.sha256(host_key.encode("utf-8")).digest()
        if plaintext.startswith(host_digest):
            plaintext = plaintext[len(host_digest) :]
        return plaintext.decode("utf-8", "ignore")

    return encrypted_value.decode("utf-8", "ignore")


def copy_cookie_db(profile_dir: Path) -> Path:
    cookies_db = profile_dir / "Cookies"
    if not cookies_db.exists():
        raise FileNotFoundError(f"Comet cookies DB not found: {cookies_db}")

    temp_path = Path(tempfile.gettempdir()) / "comet-jobright-cookies-copy.sqlite"
    shutil.copy2(cookies_db, temp_path)
    return temp_path


def load_jobright_cookies(profile_dir: Path, key: bytes) -> list[dict[str, Any]]:
    temp_db = copy_cookie_db(profile_dir)
    try:
        connection = sqlite3.connect(temp_db)
        cursor = connection.cursor()
        rows = cursor.execute(
            """
            SELECT host_key, name, path, is_secure, is_httponly, expires_utc, encrypted_value
            FROM cookies
            WHERE host_key LIKE '%jobright%'
            ORDER BY host_key, name
            """
        ).fetchall()
    finally:
        try:
            connection.close()
        except Exception:
            pass
        temp_db.unlink(missing_ok=True)

    cookies: list[dict[str, Any]] = []
    for host_key, name, path, is_secure, is_httponly, expires_utc, encrypted_value in rows:
        cookies.append(
            {
                "name": name,
                "value": decrypt_chromium_cookie(host_key, encrypted_value, key),
                "domain": host_key,
                "path": path,
                "secure": bool(is_secure),
                "httpOnly": bool(is_httponly),
                "expires": chrome_expires_to_unix(expires_utc),
            }
        )
    return cookies


def fetch_html(job_url: str, cookies: list[dict[str, Any]], user_agent: str, timeout_seconds: int) -> tuple[str, int]:
    storage_state = {"cookies": cookies, "origins": []}
    jar = build_cookie_jar(storage_state)
    session = requests.Session()
    session.cookies = jar
    response = session.get(
        job_url,
        timeout=timeout_seconds,
        headers={"User-Agent": user_agent},
    )
    response.raise_for_status()
    return response.text, response.status_code


def build_output(
    job_url: str,
    comet_root: Path,
    profile_name: str,
    html_text: str,
    http_status: int,
) -> dict[str, Any]:
    page_title = extract_title(html_text)
    next_data = extract_next_data(html_text)
    extracted = extract_from_next_data(next_data)
    return {
        "captured_at": now_utc(),
        "job_url": job_url,
        "source_profile": {
            "browser": "Comet",
            "comet_root": str(comet_root),
            "profile_name": profile_name,
            "mode": "comet_cookie_replay",
        },
        "fetch": {
            "mode": "requests",
            "http_status": http_status,
            "page_title": page_title,
            "next_data_found": next_data is not None,
        },
        **extracted,
    }


def main() -> int:
    args = parse_args()

    comet_root = Path(args.comet_root).expanduser().resolve()
    profile_dir = comet_root / args.profile_name
    output_path = ensure_parent(args.output)

    safe_storage_secret = get_safe_storage_secret(
        service=args.safe_storage_service,
        account=args.safe_storage_account,
    )
    key = derive_cookie_key(safe_storage_secret)
    cookies = load_jobright_cookies(profile_dir, key)
    if not cookies:
        sys.stderr.write("No Jobright cookies found in the Comet profile.\n")
        return 2

    html_text, http_status = fetch_html(
        job_url=args.job_url,
        cookies=cookies,
        user_agent=args.user_agent,
        timeout_seconds=args.timeout_seconds,
    )
    output = build_output(
        job_url=args.job_url,
        comet_root=comet_root,
        profile_name=args.profile_name,
        html_text=html_text,
        http_status=http_status,
    )
    output_path.write_text(json.dumps(output, indent=2) + "\n", encoding="utf-8")
    print(f"Wrote {output_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
