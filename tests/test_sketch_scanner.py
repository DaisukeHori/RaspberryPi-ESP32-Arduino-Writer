"""
Sketch Scanner モジュールのテスト
"""
import unittest
from unittest.mock import Mock, patch, MagicMock
import asyncio
import sys
from pathlib import Path
from datetime import datetime

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.sketch_scanner import SketchScanner, SketchInfo


class TestSketchScanner(unittest.TestCase):
    """Sketch Scanner のテストクラス"""
    
    def setUp(self):
        """テストのセットアップ"""
        self.config_path = str(Path(__file__).parent.parent / "config" / "boards.yaml")
        self.scanner = SketchScanner(self.config_path)
        
    def test_init(self):
        """初期化テスト"""
        self.assertIsNotNone(self.scanner)
        self.assertIsNotNone(self.scanner.config)
        
    def test_sketch_info_creation(self):
        """SketchInfo作成テスト"""
        sketch = SketchInfo(
            name="test_sketch",
            ino_file="/path/to/test.ino",
            binary_file="/path/to/test.bin",
            board_type="esp32",
            libraries=["WiFi", "ArduinoJson"],
            file_size=1024,
            modified_time=datetime.now()
        )
        
        self.assertEqual(sketch.name, "test_sketch")
        self.assertEqual(sketch.ino_file, "/path/to/test.ino")
        self.assertEqual(sketch.binary_file, "/path/to/test.bin")
        self.assertEqual(sketch.board_type, "esp32")
        self.assertEqual(len(sketch.libraries), 2)
        
    @patch('pathlib.Path.exists')
    @patch('pathlib.Path.is_dir')
    @patch('pathlib.Path.rglob')
    def test_scan_usb_device(self, mock_rglob, mock_is_dir, mock_exists):
        """USBデバイススキャンテスト"""
        # モックの設定
        mock_exists.return_value = True
        mock_is_dir.return_value = True
        
        # モックファイル
        mock_ino = MagicMock()
        mock_ino.suffix = ".ino"
        mock_ino.stem = "test_sketch"
        mock_ino.stat.return_value.st_size = 1024
        mock_ino.stat.return_value.st_mtime = datetime.now().timestamp()
        
        mock_bin = MagicMock()
        mock_bin.suffix = ".bin"
        mock_bin.stem = "test_sketch"
        mock_bin.stat.return_value.st_size = 2048
        mock_bin.stat.return_value.st_mtime = datetime.now().timestamp()
        
        mock_rglob.side_effect = lambda pattern: {
            "*.ino": [mock_ino],
            "*.bin": [mock_bin],
            "*.hex": []
        }.get(pattern, [])
        
        async def test_async():
            sketches = await self.scanner.scan_usb_device("/mock/usb/path")
            self.assertEqual(len(sketches), 2)  # .inoと.binで2つ
            
        asyncio.run(test_async())
        
    def test_get_sketch_priority(self):
        """スケッチ優先度テスト"""
        now = datetime.now()
        
        # .inoファイルのスケッチ
        ino_sketch = SketchInfo(
            name="ino_sketch",
            ino_file="/path/to/test.ino",
            modified_time=now
        )
        
        # .binファイルのスケッチ
        bin_sketch = SketchInfo(
            name="bin_sketch",
            binary_file="/path/to/test.bin",
            modified_time=now
        )
        
        # 優先度を取得
        ino_priority = self.scanner.get_sketch_priority(ino_sketch)
        bin_priority = self.scanner.get_sketch_priority(bin_sketch)
        
        # .inoファイルの方が優先度が高い（数値が小さい）
        self.assertLess(ino_priority[0], bin_priority[0])
        
    def test_sort_sketches(self):
        """スケッチソートテスト"""
        now = datetime.now()
        
        sketches = [
            SketchInfo(name="old_bin", binary_file="/old.bin", 
                      modified_time=datetime(2024, 1, 1)),
            SketchInfo(name="new_ino", ino_file="/new.ino", 
                      modified_time=now),
            SketchInfo(name="old_ino", ino_file="/old.ino", 
                      modified_time=datetime(2024, 1, 1)),
        ]
        
        sorted_sketches = self.scanner.sort_sketches(sketches)
        
        # 最初は新しい.inoファイル
        self.assertEqual(sorted_sketches[0].name, "new_ino")
        
    def test_get_recommended_action(self):
        """推奨アクション取得テスト"""
        # .inoファイルのみ
        ino_sketch = SketchInfo(name="test", ino_file="/test.ino")
        action = self.scanner.get_recommended_action(ino_sketch)
        self.assertEqual(action, "build")
        
        # .binファイルのみ
        bin_sketch = SketchInfo(name="test", binary_file="/test.bin")
        action = self.scanner.get_recommended_action(bin_sketch)
        self.assertEqual(action, "flash")
        
        # 両方ある場合
        both_sketch = SketchInfo(name="test", ino_file="/test.ino", 
                                binary_file="/test.bin")
        action = self.scanner.get_recommended_action(both_sketch)
        self.assertEqual(action, "choose")
        
        # どちらもない場合
        empty_sketch = SketchInfo(name="test")
        action = self.scanner.get_recommended_action(empty_sketch)
        self.assertEqual(action, "error")
        
    @patch('builtins.open', create=True)
    @patch('pathlib.Path.exists')
    def test_detect_board_type(self, mock_exists, mock_open):
        """ボードタイプ検出テスト"""
        mock_exists.return_value = True
        
        # ESP32-S3を含むコード
        mock_open.return_value.__enter__.return_value.read.return_value = """
        #include <ESP32S3.h>
        void setup() {
            // ESP32-S3 specific code
        }
        """
        
        async def test_async():
            board_type = await self.scanner._detect_board_type(Path("/test.ino"))
            self.assertEqual(board_type, "esp32s3")
            
        asyncio.run(test_async())


if __name__ == '__main__':
    unittest.main()
