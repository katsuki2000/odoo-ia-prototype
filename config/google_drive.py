"""Google Drive ingestion configuration: the corpus folders and the approval flag come from the environment, the limits are constants."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class GoogleDriveSettings:
    folderIds: tuple[str, ...] = ()
    approvedForRag: bool = False
    timeout: float = 30
    maxBytes: int = 20971520
    maxFiles: int = 10000
    syncInterval: float = 300

    @classmethod
    def from_environment(cls):
        return cls(
            folderIds=tuple(dict.fromkeys(value.strip() for value in os.getenv('GOOGLE_DRIVE_FOLDER_IDS', '').split(',') if value.strip())),
            approvedForRag=os.getenv('GOOGLE_DRIVE_APPROVED_FOR_RAG', '').lower() == 'true',
        )
