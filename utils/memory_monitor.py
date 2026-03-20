"""
Lightweight memory monitoring utility.

Periodically logs RSS, VMS, and CPU usage of the current Python process.
Useful for tracking RAM consumption in development and production (e.g. Render 512MB limit).
"""

import os
import threading
import time
import logging

import psutil

logger = logging.getLogger("memory_monitor")


def start_memory_monitor(interval=30):
    """
    Start a background thread that logs process memory and CPU usage every `interval` seconds.

    Args:
        interval: Seconds between each log entry. Default 30.
    """
    process = psutil.Process(os.getpid())

    def monitor():
        while True:
            mem = process.memory_info()
            rss = mem.rss / (1024 * 1024)
            vms = mem.vms / (1024 * 1024)
            cpu = process.cpu_percent(interval=None)

            logger.info(
                f"[MEMORY] PID={process.pid} RSS={rss:.2f}MB VMS={vms:.2f}MB CPU={cpu:.2f}%"
            )

            time.sleep(interval)

    thread = threading.Thread(target=monitor, daemon=True)
    thread.start()
