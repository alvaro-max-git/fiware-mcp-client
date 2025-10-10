import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path
from typing import Optional

def setup_logging(level: str = "INFO", log_to_file: bool = True, logs_dir: Path = Path("logs")) -> None:
    """
    Configures logging for the app
    Console -> always active
    Optional rotating file (default on, 5MB, 3 backups)
    """
    # Limpia configuración anterior (útil si se reimporta)
    root = logging.getLogger()
    for h in list(root.handlers):
        root.removeHandler(h)
    root.setLevel(getattr(logging, level.upper(), logging.INFO))

    # Consola
    ch = logging.StreamHandler()
    ch.setLevel(getattr(logging, level.upper(), logging.INFO))
    ch.setFormatter(logging.Formatter("[%(levelname)s] %(name)s: %(message)s"))
    root.addHandler(ch)

    # Archivo
    if log_to_file:
        logs_dir.mkdir(parents=True, exist_ok=True)
        fh = RotatingFileHandler(logs_dir / "run.log", maxBytes=5_000_000, backupCount=3, encoding="utf-8")
        fh.setLevel(getattr(logging, level.upper(), logging.INFO))
        fh.setFormatter(logging.Formatter(
            "%(asctime)s [%(levelname)s] %(name)s %(filename)s:%(lineno)d - %(message)s",
            datefmt="%Y-%m-%d %H:%M:%S",
        ))
        root.addHandler(fh)
