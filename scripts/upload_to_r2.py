"""Upload processed COGs and assets to Cloudflare R2.

R2 provides S3-compatible storage with 10 GB free and zero egress fees,
enabling cost-free COG streaming to the dashboard.

Usage:
    python scripts/upload_to_r2.py
    python scripts/upload_to_r2.py --directory data/baselines --prefix baselines/
"""

from __future__ import annotations

import os
import sys
from pathlib import Path

import boto3
import click
from loguru import logger

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from config.settings import BASELINES_DIR, R2_BUCKET_NAME


def get_r2_client():
    """Create a boto3 S3 client configured for Cloudflare R2."""
    endpoint_url = os.environ.get("R2_ENDPOINT_URL")
    access_key = os.environ.get("R2_ACCESS_KEY")
    secret_key = os.environ.get("R2_SECRET_KEY")

    if not all([endpoint_url, access_key, secret_key]):
        raise EnvironmentError(
            "R2 credentials not set. Required environment variables: "
            "R2_ENDPOINT_URL, R2_ACCESS_KEY, R2_SECRET_KEY"
        )

    return boto3.client(
        "s3",
        endpoint_url=endpoint_url,
        aws_access_key_id=access_key,
        aws_secret_access_key=secret_key,
    )


def upload_file(
    client,
    local_path: Path,
    bucket: str,
    key: str,
    content_type: str | None = None,
) -> str:
    """Upload a single file to R2.

    Parameters
    ----------
    client : boto3.client
        S3 client configured for R2.
    local_path : Path
        Local file to upload.
    bucket : str
        R2 bucket name.
    key : str
        Object key (path in bucket).
    content_type : str, optional
        MIME type. Auto-detected for common extensions.

    Returns
    -------
    str
        The object key.
    """
    if content_type is None:
        ext = local_path.suffix.lower()
        content_types = {
            ".tif": "image/tiff",
            ".tiff": "image/tiff",
            ".geojson": "application/geo+json",
            ".json": "application/json",
            ".db": "application/x-sqlite3",
        }
        content_type = content_types.get(ext, "application/octet-stream")

    extra_args = {"ContentType": content_type}

    # Set public read for COGs (needed for browser streaming)
    if ext in (".tif", ".tiff"):
        extra_args["ACL"] = "public-read"

    client.upload_file(
        str(local_path),
        bucket,
        key,
        ExtraArgs=extra_args,
    )

    logger.info("Uploaded {} → s3://{}/{}", local_path.name, bucket, key)
    return key


def upload_directory(
    client,
    directory: Path,
    bucket: str,
    prefix: str = "",
    pattern: str = "*.tif",
) -> list[str]:
    """Upload all matching files in a directory to R2.

    Parameters
    ----------
    client : boto3.client
        S3 client.
    directory : Path
        Local directory to scan.
    bucket : str
        R2 bucket name.
    prefix : str
        Key prefix in the bucket.
    pattern : str
        Glob pattern for files to upload.

    Returns
    -------
    list[str]
        List of uploaded object keys.
    """
    files = sorted(directory.glob(pattern))
    if not files:
        logger.warning("No files matching {} in {}", pattern, directory)
        return []

    logger.info("Uploading {} files from {} to s3://{}/{}", len(files), directory, bucket, prefix)

    keys = []
    for f in files:
        key = f"{prefix}{f.name}" if prefix else f.name
        upload_file(client, f, bucket, key)
        keys.append(key)

    return keys


@click.command()
@click.option(
    "--directory",
    default=str(BASELINES_DIR),
    type=click.Path(exists=True),
    help="Directory to upload.",
)
@click.option("--prefix", default="baselines/", help="R2 key prefix.")
@click.option("--pattern", default="*.tif", help="File glob pattern.")
@click.option("--bucket", default=R2_BUCKET_NAME, help="R2 bucket name.")
def main(directory: str, prefix: str, pattern: str, bucket: str) -> None:
    """Upload processed files to Cloudflare R2."""
    client = get_r2_client()
    keys = upload_directory(client, Path(directory), bucket, prefix, pattern)
    logger.info("Upload complete: {} files", len(keys))


if __name__ == "__main__":
    main()
