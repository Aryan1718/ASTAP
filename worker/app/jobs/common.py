import hashlib
import tarfile
from pathlib import Path

from supabase import Client, create_client

from shared.config import settings


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def supabase_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def download_storage_object(bucket: str, object_key: str, destination: Path) -> None:
    payload = supabase_client().storage.from_(bucket).download(object_key)
    destination.write_bytes(payload)


def upload_file_to_storage(bucket: str, object_key: str, source: Path, content_type: str) -> None:
    storage = supabase_client().storage.from_(bucket)
    with source.open("rb") as handle:
        storage.upload(
            path=object_key,
            file=handle,
            file_options={"content-type": content_type, "upsert": "true"},
        )


def safe_extract_tar_gz(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            target_path = (destination / member.name).resolve()
            if destination.resolve() not in target_path.parents and target_path != destination.resolve():
                raise RuntimeError(f"Unsafe archive member path: {member.name}")
        archive.extractall(destination)
