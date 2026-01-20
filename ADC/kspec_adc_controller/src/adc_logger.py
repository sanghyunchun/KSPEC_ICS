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
    """

    _initialized_loggers: Set[str] = set()

    def __init__(
        self,
        file: str,
        stream_level: int = logging.DEBUG,
        log_dir: Optional[str] = None,
    ) -> None:
        script_dir = os.path.dirname(os.path.abspath(__file__))
        if log_dir is None:
            log_dir = os.path.join(script_dir, "log")

        self.file_name = os.path.basename(file)
        self.logger = logging.getLogger(self.file_name)

        # 이미 초기화된 로거면 핸들러 중복 추가 방지
        if self.file_name in AdcLogger._initialized_loggers:
            return

        self.logger.setLevel(logging.DEBUG)
        self.logger.propagate = False  # 중복 출력 방지(루트 로거 전파 차단)

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

    def _fmt(self, message: str) -> str:
        return f"{message} (at {self.file_name})"

    def info(self, message: str, *args, **kwargs) -> None:
        self.logger.info(self._fmt(message), *args, **kwargs)

    def debug(self, message: str, *args, **kwargs) -> None:
        self.logger.debug(self._fmt(message), *args, **kwargs)

    def warning(self, message: str, *args, **kwargs) -> None:
        self.logger.warning(self._fmt(message), *args, **kwargs)

    def error(self, message: str, *args, **kwargs) -> None:
        self.logger.error(self._fmt(message), *args, **kwargs)

    def exception(self, message: str, *args, **kwargs) -> None:
        """
        예외 상황 로깅용: 현재 처리 중인 예외 스택트레이스를 함께 남김.
        사용 예) except Exception: logger.exception("connect failed")
        """
        self.logger.exception(self._fmt(message), *args, **kwargs)

    def critical(self, message: str, *args, **kwargs) -> None:
        self.logger.critical(self._fmt(message), *args, **kwargs)

    def setLevel(self, level: int) -> None:
        self.logger.setLevel(level)
