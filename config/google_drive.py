"""Google Drive ingestion configuration: the corpus folders and the approval flag come from the environment, the limits are constants."""

from dataclasses import dataclass
import os

DEFAULT_TIMEOUT = 30
DEFAULT_MAX_BYTES = 20 * 1024 * 1024
DEFAULT_MAX_FILES = 10000


@dataclass(frozen=True)
class GoogleDriveSettings:
    folder_ids: tuple[str, ...] = ()
    approved_for_rag: bool = False
    timeout: float = DEFAULT_TIMEOUT
    max_bytes: int = DEFAULT_MAX_BYTES
    max_files: int = DEFAULT_MAX_FILES
    sync_interval: float = 300

    @classmethod
    def from_environment(cls):
        folder_ids = os.getenv('GOOGLE_DRIVE_FOLDER_IDS', '').split(',')
        return cls(
            folder_ids=tuple(dict.fromkeys(value.strip() for value in folder_ids if value.strip())),
            approved_for_rag=os.getenv('GOOGLE_DRIVE_APPROVED_FOR_RAG', '').lower() == 'true',
        )
