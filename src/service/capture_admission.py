"""Shared local admission lock for capture jobs using the same Chrome profile."""
import threading
ADMISSION_LOCK = threading.RLock()
