"""Celery application entrypoint placeholder."""
import time
from loguru import logger

logger.info("Celery placeholder worker initialized.")

if __name__ == "__main__":
    logger.info("Worker placeholder running. Waiting for tasks in Phase 2...")
    try:
        while True:
            time.sleep(3600)
    except (KeyboardInterrupt, SystemExit):
        logger.info("Worker placeholder exiting.")
