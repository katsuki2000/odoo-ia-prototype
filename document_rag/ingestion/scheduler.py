"""Incremental scan of the documents folder, run once at startup then periodically."""

import logging
from itertools import chain, repeat
from threading import Event, Thread

from document_rag.ingestion.incremental import reindex_if_changed
from document_rag.ingestion.logging_utils import now_iso, start_timer, write_ingestion_event
from document_rag.ingestion.periodic import run_periodically
from document_rag.ingestion.scan_root import DOCS_DIR
from document_rag.vectorstore.chroma_manager import ChromaManager

logger = logging.getLogger(__name__)

STARTUP_SCAN = "startup_incremental_scan"
PERIODIC_SCAN = "periodic_incremental_scan"


def run_scan(scan_type, roots=None, docs_manager=None, status_dict=None):
    started_at = start_timer()
    result = reindex_if_changed(roots if roots is not None else [DOCS_DIR], docs_manager=docs_manager or ChromaManager())
    if status_dict is not None:
        status_dict["last_ingestion_time"] = now_iso()
        status_dict["last_result"] = result
        status_dict["last_scan_type"] = scan_type
    write_ingestion_event(event_type=scan_type, result=result, started_at=started_at)
    return result


def start_scan_loop(interval_hours, status_dict, roots=None):
    """Scan now, then every `interval_hours`, in a daemon thread; set the returned event to stop."""
    stop_event = Event()
    scan_types = chain([STARTUP_SCAN], repeat(PERIODIC_SCAN))

    def scan():
        try:
            return run_scan(next(scan_types), roots, status_dict=status_dict)
        except Exception:
            logger.exception("Incremental scan failed")
            raise

    def report(result):
        logger.info("Incremental scan report: %s", result)

    Thread(target=run_periodically, args=(scan, interval_hours * 3600, report, stop_event), daemon=True).start()
    return stop_event
