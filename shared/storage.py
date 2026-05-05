from pathlib import Path

from supabase import Client, create_client

from shared.config import settings


def supabase_client() -> Client:
    return create_client(settings.supabase_url, settings.supabase_service_role_key)


def download_storage_object(bucket: str, object_key: str, destination: Path) -> None:
    payload = supabase_client().storage.from_(bucket).download(object_key)
    destination.write_bytes(payload)


def download_storage_object_bytes(bucket: str, object_key: str) -> bytes:
    return supabase_client().storage.from_(bucket).download(object_key)


def download_storage_object_text(bucket: str, object_key: str, encoding: str = "utf-8") -> str:
    return download_storage_object_bytes(bucket, object_key).decode(encoding)


def upload_file_to_storage(bucket: str, object_key: str, source: Path, content_type: str) -> None:
    storage = supabase_client().storage.from_(bucket)
    with source.open("rb") as handle:
        storage.upload(
            path=object_key,
            file=handle,
            file_options={"content-type": content_type, "upsert": "true"},
        )
