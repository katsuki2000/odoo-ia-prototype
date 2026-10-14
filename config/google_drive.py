"""Environment-based Google Drive ingestion configuration."""

from dataclasses import dataclass
import os


@dataclass(frozen=True)
class GoogleDriveSettings:
    folderIds: tuple[str, ...] = ()
    approvedForRag: bool = False
    timeout: float = 30
    maxBytes: int = 20971520
    maxFiles: int = 10000

    @classmethod
    def from_environment(cls):
        settings = cls(
            folderIds=tuple(dict.fromkeys(value.strip() for value in os.getenv('GOOGLE_DRIVE_FOLDER_IDS', '').split(',') if value.strip())),
            approvedForRag=os.getenv('GOOGLE_DRIVE_APPROVED_FOR_RAG', '').lower() == 'true',
            timeout=float(os.getenv('GOOGLE_DRIVE_TIMEOUT', '30')),
            maxBytes=int(os.getenv('GOOGLE_DRIVE_MAX_BYTES', '20971520')),
            maxFiles=int(os.getenv('GOOGLE_DRIVE_MAX_FILES', '10000')),
        )
        if settings.timeout <= 0 or settings.maxBytes <= 0 or settings.maxFiles <= 0:
            raise ValueError('Google Drive limits must be positive.')
        return settings
