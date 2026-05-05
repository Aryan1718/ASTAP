import hashlib
import tarfile
from pathlib import Path

from shared.storage import download_storage_object, upload_file_to_storage


def file_sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()

def safe_extract_tar_gz(archive_path: Path, destination: Path) -> None:
    destination.mkdir(parents=True, exist_ok=True)
    with tarfile.open(archive_path, mode="r:gz") as archive:
        for member in archive.getmembers():
            target_path = (destination / member.name).resolve()
            if destination.resolve() not in target_path.parents and target_path != destination.resolve():
                raise RuntimeError(f"Unsafe archive member path: {member.name}")
        archive.extractall(destination)
