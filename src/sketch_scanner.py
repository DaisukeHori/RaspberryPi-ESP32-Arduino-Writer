"""
スケッチスキャナーモジュール - .ino ファイルとビルド済みバイナリの検出・解析
"""
import os
import re
import zipfile
from pathlib import Path
from typing import List, Dict, Any, Optional, Tuple
from dataclasses import dataclass
from datetime import datetime
import yaml

from .logger import get_logger

@dataclass
class SketchInfo:
    """スケッチ情報"""
    name: str
    path: str
    ino_file: Optional[str] = None
    binary_file: Optional[str] = None
    board_type: Optional[str] = None
    libraries: List[str] = None
    has_binary: bool = False
    has_source: bool = False
    modified_time: Optional[datetime] = None
    size: int = 0

class SketchScanner:
    """Arduino スケッチとバイナリファイルのスキャナー"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/boards.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # サポートするファイル拡張子
        self.sketch_extensions = ['.ino']
        self.binary_extensions = ['.bin', '.hex']
        self.library_extensions = ['.zip']
        
        self.logger.info("Sketch Scanner initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {'boards': {}, 'auto_detect': {'default_board': 'esp32'}}
    
    async def scan_usb_device(self, usb_path: str) -> List[SketchInfo]:
        """USB デバイス内のスケッチをスキャン"""
        sketches = []
        
        try:
            usb_dir = Path(usb_path)
            if not usb_dir.exists() or not usb_dir.is_dir():
                self.logger.warning(f"USB path does not exist: {usb_path}")
                return sketches
            
            self.logger.info(f"Scanning USB device: {usb_path}")
            
            # .ino ファイルを検索
            ino_files = self._find_files(usb_dir, self.sketch_extensions)
            
            # .bin/.hex ファイルを検索
            binary_files = self._find_files(usb_dir, self.binary_extensions)
            
            # スケッチ情報を構築
            sketch_map = {}
            
            # .ino ファイルから情報を構築
            for ino_file in ino_files:
                sketch_name = self._get_sketch_name(ino_file)
                if sketch_name not in sketch_map:
                    sketch_map[sketch_name] = SketchInfo(
                        name=sketch_name,
                        path=str(ino_file.parent),
                        ino_file=str(ino_file),
                        has_source=True,
                        modified_time=datetime.fromtimestamp(ino_file.stat().st_mtime),
                        size=ino_file.stat().st_size
                    )
                    
                    # ボード情報を解析
                    board_type = await self._detect_board_type(ino_file)
                    sketch_map[sketch_name].board_type = board_type
                    
                    # ライブラリ依存関係を解析
                    libraries = await self._extract_libraries(ino_file)
                    sketch_map[sketch_name].libraries = libraries
            
            # バイナリファイルから情報を構築
            for binary_file in binary_files:
                sketch_name = self._get_sketch_name(binary_file)
                
                if sketch_name in sketch_map:
                    # 既存のスケッチにバイナリ情報を追加
                    sketch_map[sketch_name].binary_file = str(binary_file)
                    sketch_map[sketch_name].has_binary = True
                else:
                    # バイナリのみのスケッチを作成
                    sketch_map[sketch_name] = SketchInfo(
                        name=sketch_name,
                        path=str(binary_file.parent),
                        binary_file=str(binary_file),
                        has_binary=True,
                        modified_time=datetime.fromtimestamp(binary_file.stat().st_mtime),
                        size=binary_file.stat().st_size
                    )
            
            sketches = list(sketch_map.values())
            
            # ライブラリファイルもチェック
            await self._scan_libraries(usb_dir)
            
            self.logger.info(f"Found {len(sketches)} sketches on USB device")
            for sketch in sketches:
                self.logger.debug(f"Sketch: {sketch.name}, Source: {sketch.has_source}, Binary: {sketch.has_binary}")
            
        except Exception as e:
            self.logger.error(f"Error scanning USB device: {e}")
        
        return sketches
    
    def _find_files(self, directory: Path, extensions: List[str]) -> List[Path]:
        """指定された拡張子のファイルを再帰的に検索"""
        files = []
        try:
            for ext in extensions:
                files.extend(directory.rglob(f"*{ext}"))
        except Exception as e:
            self.logger.error(f"Error finding files: {e}")
        return files
    
    def _get_sketch_name(self, file_path: Path) -> str:
        """ファイルパスからスケッチ名を取得"""
        return file_path.stem
    
    async def _detect_board_type(self, ino_file: Path) -> str:
        """スケッチファイルからボードタイプを検出"""
        try:
            content = ino_file.read_text(encoding='utf-8', errors='ignore')
            
            # コメント内のボード指定を検索
            board_patterns = [
                r'//\s*board\s*:\s*(\w+)',
                r'/\*\s*board\s*:\s*(\w+)\s*\*/',
                r'#define\s+BOARD\s+(\w+)',
            ]
            
            for pattern in board_patterns:
                match = re.search(pattern, content, re.IGNORECASE)
                if match:
                    board_name = match.group(1).lower()
                    if board_name in self.config.get('boards', {}):
                        return board_name
            
            # ESP32 固有のライブラリやコードを検索
            esp32_indicators = [
                '#include <WiFi.h>',
                '#include <BluetoothSerial.h>',
                'esp_',
                'ESP.restart()',
                'WiFi.begin(',
            ]
            
            for indicator in esp32_indicators:
                if indicator in content:
                    return 'esp32'
            
            # デフォルトボード
            return self.config.get('auto_detect', {}).get('default_board', 'esp32')
            
        except Exception as e:
            self.logger.error(f"Error detecting board type: {e}")
            return self.config.get('auto_detect', {}).get('default_board', 'esp32')
    
    async def _extract_libraries(self, ino_file: Path) -> List[str]:
        """スケッチファイルから必要なライブラリを抽出"""
        libraries = []
        
        try:
            content = ino_file.read_text(encoding='utf-8', errors='ignore')
            
            # #include 文を検索
            include_pattern = r'#include\s*[<"](.*?)[>"]'
            includes = re.findall(include_pattern, content)
            
            # 標準ライブラリを除外
            standard_libs = {
                'Arduino.h', 'stdio.h', 'stdlib.h', 'string.h', 'math.h',
                'WiFi.h', 'BluetoothSerial.h', 'SPIFFS.h', 'FS.h'
            }
            
            for include in includes:
                lib_name = include.split('/')[0]  # ディレクトリ部分を除去
                if lib_name not in standard_libs and lib_name.endswith('.h'):
                    lib_base = lib_name[:-2]  # .h を除去
                    if lib_base not in libraries:
                        libraries.append(lib_base)
            
        except Exception as e:
            self.logger.error(f"Error extracting libraries: {e}")
        
        return libraries
    
    async def _scan_libraries(self, usb_dir: Path) -> Dict[str, Any]:
        """USB内のライブラリファイルをスキャン"""
        library_info = {
            'has_libraries': False,
            'library_dir': None,
            'library_zip': None,
            'libraries': []
        }
        
        try:
            # libraries ディレクトリを検索
            lib_dir = usb_dir / 'libraries'
            if lib_dir.exists() and lib_dir.is_dir():
                library_info['has_libraries'] = True
                library_info['library_dir'] = str(lib_dir)
                
                # ライブラリ一覧を取得
                for item in lib_dir.iterdir():
                    if item.is_dir():
                        library_info['libraries'].append(item.name)
                
                self.logger.info(f"Found libraries directory with {len(library_info['libraries'])} libraries")
            
            # libs.zip ファイルを検索
            lib_zip = usb_dir / 'libs.zip'
            if lib_zip.exists():
                library_info['has_libraries'] = True
                library_info['library_zip'] = str(lib_zip)
                
                # ZIP内のライブラリ一覧を取得
                try:
                    with zipfile.ZipFile(lib_zip, 'r') as zf:
                        lib_names = set()
                        for name in zf.namelist():
                            parts = name.split('/')
                            if len(parts) > 1:
                                lib_names.add(parts[0])
                        library_info['libraries'].extend(list(lib_names))
                    
                    self.logger.info(f"Found libs.zip with {len(lib_names)} libraries")
                except Exception as e:
                    self.logger.error(f"Error reading libs.zip: {e}")
            
        except Exception as e:
            self.logger.error(f"Error scanning libraries: {e}")
        
        return library_info
    
    def get_sketch_priority(self, sketch: SketchInfo) -> Tuple[int, datetime]:
        """スケッチの優先度を計算（ソート用）"""
        priority = 0
        
        # ソースとバイナリ両方がある場合は高優先度
        if sketch.has_source and sketch.has_binary:
            priority += 100
        elif sketch.has_source:
            priority += 50
        elif sketch.has_binary:
            priority += 25
        
        # 更新時間も考慮
        mod_time = sketch.modified_time or datetime.min
        
        return (priority, mod_time)
    
    def sort_sketches(self, sketches: List[SketchInfo]) -> List[SketchInfo]:
        """スケッチを優先度順にソート"""
        return sorted(sketches, key=self.get_sketch_priority, reverse=True)
    
    def get_recommended_action(self, sketch: SketchInfo) -> str:
        """推奨アクションを取得"""
        if sketch.has_source and sketch.has_binary:
            return "choose"  # ユーザーに選択させる
        elif sketch.has_source:
            return "build"   # ビルドが必要
        elif sketch.has_binary:
            return "flash"   # 直接フラッシュ
        else:
            return "error"   # エラー
    
    async def validate_sketch(self, sketch: SketchInfo) -> Dict[str, Any]:
        """スケッチの妥当性を検証"""
        validation = {
            'valid': True,
            'errors': [],
            'warnings': []
        }
        
        try:
            # ソースファイルの検証
            if sketch.has_source and sketch.ino_file:
                ino_path = Path(sketch.ino_file)
                if not ino_path.exists():
                    validation['valid'] = False
                    validation['errors'].append(f"Source file not found: {sketch.ino_file}")
                elif ino_path.stat().st_size == 0:
                    validation['warnings'].append("Source file is empty")
            
            # バイナリファイルの検証
            if sketch.has_binary and sketch.binary_file:
                bin_path = Path(sketch.binary_file)
                if not bin_path.exists():
                    validation['valid'] = False
                    validation['errors'].append(f"Binary file not found: {sketch.binary_file}")
                elif bin_path.stat().st_size == 0:
                    validation['valid'] = False
                    validation['errors'].append("Binary file is empty")
            
            # ボード設定の検証
            if sketch.board_type and sketch.board_type not in self.config.get('boards', {}):
                validation['warnings'].append(f"Unknown board type: {sketch.board_type}")
            
        except Exception as e:
            validation['valid'] = False
            validation['errors'].append(f"Validation error: {str(e)}")
        
        return validation