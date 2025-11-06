import logging
import os
from datetime import datetime


def setup_logging(log_dir: str, verbose: bool = False) -> str:
    """
    Configure logging to file (daily file) and console.

    Returns path to the logfile used.
    """
    os.makedirs(log_dir, exist_ok=True)
    date_str = datetime.now().strftime("%Y-%m-%d")
    logfile = os.path.join(log_dir, f"backup_{date_str}.log")

    # Remove existing handlers if reconfiguring
    for h in list(logging.getLogger().handlers):
        logging.getLogger().removeHandler(h)

    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format='%(asctime)s [%(levelname)s] %(name)s: %(message)s', handlers=[])

    # File handler
    fh = logging.FileHandler(logfile, encoding='utf-8')
    fh.setLevel(level)
    fh.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logging.getLogger().addHandler(fh)

    # Console handler
    ch = logging.StreamHandler()
    ch.setLevel(level)
    ch.setFormatter(logging.Formatter('%(asctime)s [%(levelname)s] %(name)s: %(message)s'))
    logging.getLogger().addHandler(ch)

    logging.getLogger(__name__).debug("Logging initialized. Log file: %s", logfile)
    return logfile
