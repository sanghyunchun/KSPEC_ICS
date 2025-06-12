#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-12-04
# @Filename: adc_logger.py

import logging
import os
from datetime import datetime
from typing import Set, Optional

__all__ = ["AdcLogger"]

class AdcLogger:
    """
    A custom logging system for the ADC project, modeled after GFALogger.

    Supports stream and file logging with customizable paths and prevents
    duplicate logger initialization using a class-level registry.

    Attributes
    ----------
    file_name : str
        The base filename for which the logger is created.
    logger : logging.Logger
        The underlying logger instance.
    """

    _initialized_loggers: Set[str] = set()

    def __init__(
        self,
        file: str,
        stream_level: int = logging.INFO,
        log_dir: Optional[str] = None
    ) -> None:
        """
        Initialize a logger with stream and file handlers.

        Parameters
        ----------
        file : str
            File name to derive logger identity (e.g., __file__).
        stream_level : int, optional
            Logging level for console output (default: logging.INFO).
        log_dir : str, optional
            Custom log directory path. Defaults to 'log/' next to script.
        """
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if log_dir is None:
            log_dir = os.path.join(script_dir, "log")

        self.file_name = os.path.basename(file)
        self.logger = logging.getLogger(self.file_name)

        if self.file_name in AdcLogger._initialized_loggers:
            return

        self.logger.setLevel(logging.DEBUG)
        os.makedirs(log_dir, exist_ok=True)

        log_filename = f"adc_{datetime.now().strftime('%Y-%m-%d')}.log"
        log_file_path = os.path.join(log_dir, log_filename)

        formatter = logging.Formatter("%(asctime)s [%(levelname)s] %(message)s")

        # Console handler
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)
        self.logger.addHandler(stream_handler)

        # File handler
        file_handler = logging.FileHandler(log_file_path, mode="a", encoding="utf-8")
        file_handler.setFormatter(formatter)
        file_handler.setLevel(logging.DEBUG)
        self.logger.addHandler(file_handler)

        AdcLogger._initialized_loggers.add(self.file_name)

    def info(self, message: str) -> None:
        """Log an INFO-level message."""
        self.logger.info(f"{message} (at {self.file_name})")

    def debug(self, message: str) -> None:
        """Log a DEBUG-level message."""
        self.logger.debug(f"{message} (at {self.file_name})")

    def warning(self, message: str) -> None:
        """Log a WARNING-level message."""
        self.logger.warning(f"{message} (at {self.file_name})")

    def error(self, message: str) -> None:
        """Log an ERROR-level message."""
        self.logger.error(f"{message} (at {self.file_name})")
