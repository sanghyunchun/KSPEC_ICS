#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# @Author: Mingyeong Yang (mmingyeong@kasi.re.kr)
# @Date: 2024-12-04
# @Filename: adc_logger.py

import logging
import os
import datetime

class AdcLogger:
    """
    A logging utility class for managing console and optional file logging with distinct levels.

    This class supports simultaneous logging to the console and, optionally, to a file.
    """

    _initialized_loggers = set()  # Class-level set to track initialized loggers

    def __init__(self, stream_level=logging.INFO, enable_file_logging=True):
        """
        Initialize the logger with configurable log levels and optional file logging.

        Parameters
        ----------
        stream_level : int, optional
            Logging level for console output. Defaults to logging.DEBUG.
        enable_file_logging : bool, optional
            Whether to enable file logging. Defaults to False.
        """
        # base_dir: 현재 스크립트 파일(adc_logger.py)이 위치한 디렉토리의 절대 경로
        base_dir = os.path.abspath(os.path.dirname(__file__))

        # logger_name: 스크립트 파일 이름만 추출 (adc_logger.py)
        logger_name = os.path.basename(__file__)
        
        # 중복 초기화 방지
        if logger_name in AdcLogger._initialized_loggers:
            return
        AdcLogger._initialized_loggers.add(logger_name)

        # Logger 생성
        self.logger = logging.getLogger(logger_name)
        self.logger.setLevel(logging.INFO)

        # Formatter 설정
        formatter = logging.Formatter(
            "%(asctime)s [%(levelname)s] %(message)s", "%Y-%m-%d %H:%M:%S"
        )

        # 콘솔 핸들러
        stream_handler = logging.StreamHandler()
        stream_handler.setFormatter(formatter)
        stream_handler.setLevel(stream_level)  # INFO 혹은 DEBUG 등으로 세팅 가능
        if not self.logger.hasHandlers():
            self.logger.addHandler(stream_handler)

        # 파일 로깅 활성화
        if enable_file_logging:
            # 1) 스크립트 파일이 있는 디렉토리에 log 폴더 생성
            log_dir = os.path.join(base_dir, "log")
            os.makedirs(log_dir, exist_ok=True)

            # 2) 날짜/시간 정보를 파일 이름에 포함: adc_logger_YYYY-MM-DD_HH-MM-SS.log
            timestamp = datetime.datetime.now().strftime('%Y-%m-%d_%H-%M-%S')
            log_file_name = f"adc_logger_{timestamp}.log"  # adc_logger.log 대신 시분초 포함

            # 3) 최종 파일 경로
            log_file_path = os.path.join(log_dir, log_file_name)

            # 파일 핸들러 생성
            file_handler = logging.FileHandler(log_file_path)
            file_handler.setFormatter(formatter)
            file_handler.setLevel(logging.DEBUG)  # 파일에는 상세 정보까지 기록
            self.logger.addHandler(file_handler)

    def debug(self, message):
        """Log a debug message."""
        self.logger.debug(message)

    def info(self, message):
        """Log an informational message."""
        self.logger.info(message)

    def warning(self, message):
        """Log a warning message."""
        self.logger.warning(message)

    def error(self, message):
        """Log an error message."""
        self.logger.error(message)
