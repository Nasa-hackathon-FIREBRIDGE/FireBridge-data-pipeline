"""Acquire bounded standard MODIS monthly point products from official UMD SFTP.

The shared public account is published in the MODIS C6/C6.1 user guide,
section 4.3. No user credentials are read, printed, or persisted.
Raw monthly files are retained unchanged; later analysis must filter the
requested inclusive UTC window (2024-01-17 through 2025-01-17).
"""
from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
from pathlib import Path
import re
import socket

import paramiko


ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "data/external/modis_2024_2025"
HOST = "fuoco.geog.umd.edu"
REMOTE = "/data/MODIS/C61/MCD14ML"
GUIDE = "https://www.earthdata.nasa.gov/s3fs-public/2023-09/MODIS_C6_C6.1_Fire_User_Guide_1.0.pdf"
MAX_COMPRESSED_BYTES = 250_000_000


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--download", action="store_true")
    args = parser.parse_args()
    OUT.mkdir(parents=True, exist_ok=True)
    manifest = {
        "retrieved_utc": dt.datetime.now(dt.timezone.utc).isoformat(),
        "requested_utc_start_inclusive": "2024-01-17",
        "requested_utc_end_inclusive": "2025-01-17",
        "geography": "global",
        "product": "MCD14ML Collection 6.1 standard processing",
        "provider": "University of Maryland MODIS Fire Science Team",
        "documentation_url": GUIDE,
        "server": HOST,
        "remote_directory": REMOTE,
        "acquisition_mode": "download" if args.download else "discovery",
        "files": [],
    }
    client = paramiko.SSHClient()
    client.load_system_host_keys()
    # This server uses a deliberately shared public account. Record its key
    # fingerprint for provenance; no private account credentials are supplied.
    client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
    try:
        client.connect(HOST, username="fire", password="burnt", timeout=25,
                       banner_timeout=25, auth_timeout=25,
                       look_for_keys=False, allow_agent=False)
        key = client.get_transport().get_remote_server_key()
        manifest["server_host_key_sha256_hex"] = hashlib.sha256(key.asbytes()).hexdigest()
        with client.open_sftp() as sftp:
            attrs = sftp.listdir_attr(REMOTE)
            selected = []
            for attr in attrs:
                match = re.fullmatch(r"MCD14ML\.(\d{6})\.(\d{3})\.(\d{2})\.txt\.gz", attr.filename)
                if match and "202401" <= match[1] <= "202501" and match[2] == "061" and match[3] == "03":
                    selected.append(attr)
            selected.sort(key=lambda a: a.filename)
            planned_size = sum(a.st_size for a in selected)
            manifest["listed_candidate_bytes"] = planned_size
            manifest["listed_candidate_months"] = sorted({a.filename.split(".")[1] for a in selected})
            manifest["expected_months"] = [f"2024{m:02d}" for m in range(1,13)] + ["202501"]
            if manifest["listed_candidate_months"] != manifest["expected_months"]:
                raise ValueError("The provider listing does not contain every requested version-03 month")
            print("MONTHS", manifest["listed_candidate_months"], flush=True)
            print("CANDIDATE_COMPRESSED_BYTES", planned_size, flush=True)
            if planned_size > MAX_COMPRESSED_BYTES:
                raise ValueError("Refusing download above bounded compressed-byte limit")
            for attr in selected:
                path = OUT / attr.filename
                entry = {
                    "filename": attr.filename,
                    "url": f"sftp://{HOST}{REMOTE}/{attr.filename}",
                    "remote_bytes": attr.st_size,
                    "remote_mtime_utc": dt.datetime.fromtimestamp(attr.st_mtime, dt.timezone.utc).isoformat(),
                    "status": "discovered",
                }
                manifest["files"].append(entry)
                if args.download:
                    if path.exists() and path.stat().st_size == attr.st_size:
                        entry["cache_used"] = True
                    else:
                        tmp = path.with_suffix(path.suffix + ".partial")
                        sftp.get(f"{REMOTE}/{attr.filename}", str(tmp))
                        if tmp.stat().st_size != attr.st_size:
                            raise ValueError("Downloaded size differs from remote listing")
                        tmp.replace(path)
                    digest = hashlib.sha256()
                    with path.open("rb") as stream:
                        for block in iter(lambda: stream.read(1024*1024), b""):
                            digest.update(block)
                    entry.update(status="downloaded", local_path=str(path.relative_to(ROOT)),
                                 downloaded_bytes=path.stat().st_size, sha256=digest.hexdigest())
                print(entry["status"].upper(), attr.filename, attr.st_size, flush=True)
            manifest["status"] = "downloaded" if args.download else "discovered"
    except Exception as exc:
        manifest["status"] = "failed"
        manifest["error_type"] = type(exc).__name__
        manifest["error"] = str(exc)[:300]
        print("FAILED", type(exc).__name__, str(exc)[:300], flush=True)
        raise
    finally:
        client.close()
        (OUT / "acquisition_manifest.json").write_text(json.dumps(manifest, indent=2) + "\n")


if __name__ == "__main__":
    main()
