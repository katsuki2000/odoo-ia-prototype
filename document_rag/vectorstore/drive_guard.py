"""Check current Drive chunk availability, including stale lexical candidates."""


def is_drive_chunk(item):
    metadata = item.get('metadata') or {}
    return metadata.get('origin') == 'google_drive' or bool(metadata.get('drive_file_id'))


def filter_current_drive_chunks(items, managers):
    driveIds = {item.get('id') for item in items if is_drive_chunk(item) and item.get('id')}
    if not driveIds:
        return [item for item in items if not is_drive_chunk(item)]
    managers = managers if isinstance(managers, list) else [managers]
    activeIds = set()
    for manager in managers:
        try:
            rows = manager.collection.get(ids=list(driveIds), include=['metadatas'])
            for chunkId, metadata in zip(rows.get('ids', []), rows.get('metadatas', [])):
                if metadata and metadata.get('origin') == 'google_drive' and metadata.get('drive_active', True) is True:
                    activeIds.add(chunkId)
        except Exception:
            continue
    return [item for item in items if not is_drive_chunk(item) or item.get('id') in activeIds]
