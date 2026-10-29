"""Run an action now, then at a fixed interval, until stopped."""

from threading import Event


def run_periodically(action, interval_seconds, emit, stop_event=None):
    if interval_seconds <= 0:
        raise ValueError('Interval must be positive.')
    stop_event = stop_event or Event()
    while not stop_event.is_set():
        try:
            emit(action())
        except Exception as error:
            emit({'status': 'failed', 'error_type': type(error).__name__})
        if stop_event.wait(interval_seconds):
            break
