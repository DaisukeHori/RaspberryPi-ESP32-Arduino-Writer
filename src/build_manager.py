"""
ビルドマネージャーモジュール - Arduino CLI を使用したスケッチのビルド
"""
import asyncio
import os
import shutil
import tempfile
import zipfile
from pathlib import Path
from typing import Dict, Any, Optional, List
from dataclasses import dataclass
import yaml
import subprocess

from .logger import get_logger
from .sketch_scanner import SketchInfo

@dataclass
class BuildResult:
    """ビルド結果"""
    success: bool
    sketch_name: str
    binary_path: Optional[str] = None
    board_type: str = "esp32"
    build_log: str = ""
    error_message: str = ""
    build_time: float = 0.0
    binary_size: int = 0

class BuildManager:
    """Arduino CLI を使用したビルド管理"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/boards.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # ビルド用の一時ディレクトリ
        self.build_dir = Path("/tmp/esp32_writer_build")
        self.build_dir.mkdir(exist_ok=True)
        
        # Arduino CLI の設定
        self.arduino_cli = "arduino-cli"
        self.sketch_dir = self.build_dir / "sketches"
        self.library_dir = self.build_dir / "libraries"
        
        self.logger.info("Build Manager initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {'boards': {'esp32': {'fqbn': 'esp32:esp32:esp32'}}}
    
    async def setup_build_environment(self):
        """ビルド環境をセットアップ"""
        try:
            # ディレクトリ作成
            self.sketch_dir.mkdir(parents=True, exist_ok=True)
            self.library_dir.mkdir(parents=True, exist_ok=True)
            
            # Arduino CLI の初期化確認
            result = await self._run_arduino_cli(["version"])
            if not result['success']:
                raise Exception("Arduino CLI not available")
            
            self.logger.info("Build environment setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup build environment: {e}")
            return False
    
    async def install_libraries(self, usb_path: str, required_libs: List[str]) -> bool:
        """ライブラリをインストール"""
        try:
            usb_dir = Path(usb_path)
            installed_any = False
            
            # USB内のlibrariesディレクトリをチェック
            lib_dir = usb_dir / "libraries"
            if lib_dir.exists():
                self.logger.info("Installing libraries from USB libraries directory")
                await self._install_from_directory(lib_dir)
                installed_any = True
            
            # libs.zipをチェック
            lib_zip = usb_dir / "libs.zip"
            if lib_zip.exists():
                self.logger.info("Installing libraries from libs.zip")
                await self._install_from_zip(lib_zip)
                installed_any = True
            
            # 必要なライブラリが不足している場合は警告
            if required_libs and not installed_any:
                self.logger.warning(f"Required libraries not found: {required_libs}")
                # 事前インストール済みライブラリに依存
                self.logger.info("Using pre-installed libraries")
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to install libraries: {e}")
            return False
    
    async def _install_from_directory(self, lib_dir: Path):
        """ディレクトリからライブラリをインストール"""
        try:
            for lib_path in lib_dir.iterdir():
                if lib_path.is_dir():
                    # ライブラリディレクトリをコピー
                    dest_path = self.library_dir / lib_path.name
                    if dest_path.exists():
                        shutil.rmtree(dest_path)
                    shutil.copytree(lib_path, dest_path)
                    self.logger.debug(f"Installed library: {lib_path.name}")
        except Exception as e:
            self.logger.error(f"Error installing from directory: {e}")
    
    async def _install_from_zip(self, zip_path: Path):
        """ZIPファイルからライブラリをインストール"""
        try:
            with zipfile.ZipFile(zip_path, 'r') as zf:
                zf.extractall(self.library_dir)
            self.logger.info("Libraries extracted from ZIP")
        except Exception as e:
            self.logger.error(f"Error installing from ZIP: {e}")
    
    async def build_sketch(self, sketch: SketchInfo, usb_path: str) -> BuildResult:
        """スケッチをビルド"""
        start_time = asyncio.get_event_loop().time()
        
        try:
            self.logger.info(f"Building sketch: {sketch.name}")
            self.logger.log_build(f"Starting build for {sketch.name}")
            
            # ビルド環境のセットアップ
            if not await self.setup_build_environment():
                return BuildResult(
                    success=False,
                    sketch_name=sketch.name,
                    error_message="Failed to setup build environment"
                )
            
            # ライブラリのインストール
            if sketch.libraries:
                await self.install_libraries(usb_path, sketch.libraries)
            
            # スケッチファイルを準備
            sketch_build_dir = await self._prepare_sketch(sketch)
            if not sketch_build_dir:
                return BuildResult(
                    success=False,
                    sketch_name=sketch.name,
                    error_message="Failed to prepare sketch"
                )
            
            # ボード設定を取得
            board_config = self._get_board_config(sketch.board_type or "esp32")
            fqbn = board_config.get('fqbn', 'esp32:esp32:esp32')
            
            # ビルド実行
            build_result = await self._compile_sketch(sketch_build_dir, fqbn)
            
            # ビルド時間を計算
            build_time = asyncio.get_event_loop().time() - start_time
            
            if build_result['success']:
                # バイナリファイルを探す
                binary_path = await self._find_binary_file(sketch_build_dir, sketch.name)
                binary_size = 0
                
                if binary_path and Path(binary_path).exists():
                    binary_size = Path(binary_path).stat().st_size
                    self.logger.info(f"Build successful: {binary_path} ({binary_size} bytes)")
                    self.logger.log_build(f"Build completed successfully, size: {binary_size} bytes")
                else:
                    self.logger.warning("Build reported success but binary not found")
                
                return BuildResult(
                    success=True,
                    sketch_name=sketch.name,
                    binary_path=binary_path,
                    board_type=sketch.board_type or "esp32",
                    build_log=build_result['output'],
                    build_time=build_time,
                    binary_size=binary_size
                )
            else:
                self.logger.error(f"Build failed: {build_result['error']}")
                self.logger.log_build(f"Build failed: {build_result['error']}", "error")
                
                return BuildResult(
                    success=False,
                    sketch_name=sketch.name,
                    board_type=sketch.board_type or "esp32",
                    build_log=build_result['output'],
                    error_message=build_result['error'],
                    build_time=build_time
                )
                
        except Exception as e:
            build_time = asyncio.get_event_loop().time() - start_time
            error_msg = f"Build exception: {str(e)}"
            self.logger.error(error_msg)
            self.logger.log_build(error_msg, "error")
            
            return BuildResult(
                success=False,
                sketch_name=sketch.name,
                error_message=error_msg,
                build_time=build_time
            )
    
    async def _prepare_sketch(self, sketch: SketchInfo) -> Optional[Path]:
        """スケッチファイルをビルド用ディレクトリに準備"""
        try:
            if not sketch.ino_file:
                return None
            
            source_path = Path(sketch.ino_file)
            if not source_path.exists():
                return None
            
            # スケッチ用ディレクトリを作成
            sketch_build_dir = self.sketch_dir / sketch.name
            if sketch_build_dir.exists():
                shutil.rmtree(sketch_build_dir)
            sketch_build_dir.mkdir(parents=True)
            
            # メインの.inoファイルをコピー
            dest_ino = sketch_build_dir / f"{sketch.name}.ino"
            shutil.copy2(source_path, dest_ino)
            
            # 同じディレクトリの他のファイルもコピー
            source_dir = source_path.parent
            for file_path in source_dir.iterdir():
                if file_path.is_file() and file_path != source_path:
                    if file_path.suffix in ['.cpp', '.c', '.h', '.hpp']:
                        shutil.copy2(file_path, sketch_build_dir / file_path.name)
            
            self.logger.debug(f"Sketch prepared: {sketch_build_dir}")
            return sketch_build_dir
            
        except Exception as e:
            self.logger.error(f"Error preparing sketch: {e}")
            return None
    
    def _get_board_config(self, board_type: str) -> Dict[str, Any]:
        """ボード設定を取得"""
        boards = self.config.get('boards', {})
        return boards.get(board_type, boards.get('esp32', {'fqbn': 'esp32:esp32:esp32'}))
    
    async def _compile_sketch(self, sketch_dir: Path, fqbn: str) -> Dict[str, Any]:
        """スケッチをコンパイル"""
        try:
            # ビルドコマンドを構築
            cmd = [
                self.arduino_cli, "compile",
                "--fqbn", fqbn,
                "--output-dir", str(sketch_dir / "build"),
                str(sketch_dir)
            ]
            
            # ライブラリパスを追加
            if self.library_dir.exists() and any(self.library_dir.iterdir()):
                cmd.extend(["--libraries", str(self.library_dir)])
            
            self.logger.debug(f"Compile command: {' '.join(cmd)}")
            
            # コンパイル実行
            result = await self._run_command(cmd)
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'output': '',
                'error': str(e)
            }
    
    async def _find_binary_file(self, sketch_dir: Path, sketch_name: str) -> Optional[str]:
        """ビルド後のバイナリファイルを検索"""
        try:
            build_dir = sketch_dir / "build"
            if not build_dir.exists():
                return None
            
            # 一般的なバイナリファイル名パターン
            patterns = [
                f"{sketch_name}.ino.bin",
                f"{sketch_name}.bin",
                "*.bin"
            ]
            
            for pattern in patterns:
                files = list(build_dir.glob(pattern))
                if files:
                    return str(files[0])
            
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding binary file: {e}")
            return None
    
    async def _run_arduino_cli(self, args: List[str]) -> Dict[str, Any]:
        """Arduino CLI コマンドを実行"""
        cmd = [self.arduino_cli] + args
        return await self._run_command(cmd)
    
    async def _run_command(self, cmd: List[str]) -> Dict[str, Any]:
        """コマンドを非同期実行"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(self.build_dir)
            )
            
            stdout, stderr = await process.communicate()
            
            output = stdout.decode('utf-8', errors='ignore')
            error = stderr.decode('utf-8', errors='ignore')
            
            success = process.returncode == 0
            
            if not success:
                self.logger.debug(f"Command failed: {' '.join(cmd)}")
                self.logger.debug(f"Error output: {error}")
            
            return {
                'success': success,
                'output': output,
                'error': error,
                'returncode': process.returncode
            }
            
        except Exception as e:
            return {
                'success': False,
                'output': '',
                'error': str(e),
                'returncode': -1
            }
    
    def cleanup_build_files(self, sketch_name: str):
        """ビルドファイルをクリーンアップ"""
        try:
            sketch_build_dir = self.sketch_dir / sketch_name
            if sketch_build_dir.exists():
                shutil.rmtree(sketch_build_dir)
                self.logger.debug(f"Cleaned up build files for {sketch_name}")
        except Exception as e:
            self.logger.error(f"Error cleaning up build files: {e}")
    
    def get_build_info(self) -> Dict[str, Any]:
        """ビルド環境の情報を取得"""
        info = {
            'arduino_cli_available': False,
            'build_dir': str(self.build_dir),
            'cores_installed': [],
            'libraries_available': []
        }
        
        try:
            # Arduino CLI バージョン確認
            result = subprocess.run([self.arduino_cli, "version"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                info['arduino_cli_available'] = True
                info['version'] = result.stdout.strip()
            
            # インストール済みコア一覧
            result = subprocess.run([self.arduino_cli, "core", "list"], 
                                  capture_output=True, text=True, timeout=10)
            if result.returncode == 0:
                info['cores_installed'] = result.stdout.strip().split('\n')
            
        except Exception as e:
            self.logger.error(f"Error getting build info: {e}")
        
        return info