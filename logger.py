"""AI Suite 结构化日志 — JSON lines + 滚动文件 + stderr"""
import logging
import os
import sys
from logging.handlers import RotatingFileHandler
from datetime import datetime, timezone

LOG_DIR = os.path.expanduser("~/.ai-suite/logs")
os.makedirs(LOG_DIR, exist_ok=True)

_loggers: dict[str, logging.Logger] = {}


def get_logger(name: str = "ai-suite") -> logging.Logger:
    """获取或创建 logger，自动附加 file+stderr handler"""
    if name in _loggers:
        return _loggers[name]

    logger = logging.getLogger(name)
    logger.setLevel(logging.DEBUG)

    # 文件 handler: 滚动 5MB，保留 3 个备份
    fh = RotatingFileHandler(
        os.path.join(LOG_DIR, f"{name}.log"),
        maxBytes=5_000_000, backupCount=3, encoding="utf-8"
    )
    fh.setLevel(logging.DEBUG)
    fh.setFormatter(logging.Formatter(
        "%(asctime)s [%(levelname)s] %(name)s:%(lineno)d %(message)s",
        datefmt="%Y-%m-%dT%H:%M:%S"
    ))
    logger.addHandler(fh)

    # stderr handler: WARNING+
    sh = logging.StreamHandler(sys.stderr)
    sh.setLevel(logging.WARNING)
    sh.setFormatter(logging.Formatter("[%(levelname)s] %(name)s %(message)s"))
    logger.addHandler(sh)

    _loggers[name] = logger
    return logger


log = get_logger("ai-suite")
