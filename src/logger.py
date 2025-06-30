"""
ログ管理モジュール
"""
import logging
import logging.handlers
import os
from datetime import datetime
from pathlib import Path
from typing import Optional

class Logger:
    def __init__(self, name: str = "esp32_writer", log_dir: str = None):
        if log_dir is None:
            # プロジェクトルートからの相対パス
            project_root = Path(__file__).parent.parent
            log_dir = str(project_root / "logs")
        self.name = name
        self.log_dir = Path(log_dir)
        self.log_dir.mkdir(parents=True, exist_ok=True)
        
        # ロガーの設定
        self.logger = logging.getLogger(name)
        self.logger.setLevel(logging.DEBUG)
        
        # 既存のハンドラーをクリア
        self.logger.handlers.clear()
        
        # フォーマッターの設定
        formatter = logging.Formatter(
            '%(asctime)s - %(name)s - %(levelname)s - %(message)s'
        )
        
        # ファイルハンドラー（回転ログ）
        file_handler = logging.handlers.RotatingFileHandler(
            self.log_dir / "system.log",
            maxBytes=10*1024*1024,  # 10MB
            backupCount=5
        )
        file_handler.setLevel(logging.DEBUG)
        file_handler.setFormatter(formatter)
        self.logger.addHandler(file_handler)
        
        # コンソールハンドラー
        console_handler = logging.StreamHandler()
        console_handler.setLevel(logging.INFO)
        console_handler.setFormatter(formatter)
        self.logger.addHandler(console_handler)
        
        # 専用ログファイル用のハンドラー辞書
        self.specialized_handlers = {}
    
    def get_specialized_logger(self, log_type: str) -> logging.Logger:
        """特定用途のロガーを取得（build.log, flash.log など）"""
        if log_type not in self.specialized_handlers:
            handler = logging.FileHandler(self.log_dir / f"{log_type}.log")
            handler.setLevel(logging.DEBUG)
            formatter = logging.Formatter('%(asctime)s - %(levelname)s - %(message)s')
            handler.setFormatter(formatter)
            
            specialized_logger = logging.getLogger(f"{self.name}.{log_type}")
            specialized_logger.setLevel(logging.DEBUG)
            specialized_logger.addHandler(handler)
            
            self.specialized_handlers[log_type] = specialized_logger
        
        return self.specialized_handlers[log_type]
    
    def debug(self, message: str):
        self.logger.debug(message)
    
    def info(self, message: str):
        self.logger.info(message)
    
    def warning(self, message: str):
        self.logger.warning(message)
    
    def error(self, message: str):
        self.logger.error(message)
    
    def critical(self, message: str):
        self.logger.critical(message)
    
    def log_build(self, message: str, level: str = "info"):
        """ビルド専用ログ"""
        build_logger = self.get_specialized_logger("build")
        getattr(build_logger, level.lower())(message)
    
    def log_flash(self, message: str, level: str = "info"):
        """フラッシュ専用ログ"""
        flash_logger = self.get_specialized_logger("flash")
        getattr(flash_logger, level.lower())(message)
    
    def log_usb(self, message: str, level: str = "info"):
        """USB監視専用ログ"""
        usb_logger = self.get_specialized_logger("usb")
        getattr(usb_logger, level.lower())(message)

# グローバルロガーインスタンス
_global_logger: Optional[Logger] = None

def get_logger() -> Logger:
    """グローバルロガーインスタンスを取得"""
    global _global_logger
    if _global_logger is None:
        _global_logger = Logger()
    return _global_logger

def init_logger(name: str = "esp32_writer", log_dir: str = None) -> Logger:
    """ロガーを初期化"""
    global _global_logger
    _global_logger = Logger(name, log_dir)
    return _global_logger