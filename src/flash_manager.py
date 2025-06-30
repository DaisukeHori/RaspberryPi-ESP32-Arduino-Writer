"""
フラッシュマネージャーモジュール - ESP32への書き込み制御
"""
import asyncio
import serial
import serial.tools.list_ports
from pathlib import Path
from typing import Optional, Dict, Any, List
from dataclasses import dataclass
import yaml
import time

from .logger import get_logger
from .reset_controller import ResetController
from .build_manager import BuildResult

@dataclass
class FlashResult:
    """フラッシュ結果"""
    success: bool
    sketch_name: str
    flash_time: float = 0.0
    bytes_written: int = 0
    flash_log: str = ""
    error_message: str = ""
    port: str = ""

class FlashManager:
    """ESP32フラッシュ書き込み管理"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/boards.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # リセットコントローラー
        self.reset_controller = ResetController(config_path)
        
        # シリアルポート設定
        self.serial_port: Optional[serial.Serial] = None
        self.current_port: Optional[str] = None
        
        # esptool設定
        self.esptool_cmd = "esptool.py"
        self.arduino_cli = "arduino-cli"
        
        self.logger.info("Flash Manager initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {
                'serial': {'baudrate': 115200, 'timeout': 10},
                'boards': {'esp32': {'upload_speed': 921600}}
            }
    
    async def find_esp32_port(self) -> Optional[str]:
        """ESP32のシリアルポートを検索"""
        try:
            ports = serial.tools.list_ports.comports()
            
            # ESP32の特徴的なVID/PIDやデバイス名を検索
            esp32_indicators = [
                'CP210',  # CP2102
                'CH340',  # CH340
                'FTDI',   # FTDI
                'ESP32',
                'Silicon Labs',
                'QinHeng'
            ]
            
            for port in ports:
                port_info = f"{port.device} - {port.description} - {port.manufacturer or ''}"
                self.logger.debug(f"Found port: {port_info}")
                
                # ESP32らしいポートを検索
                for indicator in esp32_indicators:
                    if indicator.lower() in port_info.lower():
                        self.logger.info(f"ESP32 port found: {port.device}")
                        return port.device
            
            # 見つからない場合は最初のUSBシリアルポートを使用
            for port in ports:
                if 'USB' in port.description.upper() or '/dev/ttyUSB' in port.device:
                    self.logger.warning(f"Using fallback port: {port.device}")
                    return port.device
            
            self.logger.error("No suitable serial port found")
            return None
            
        except Exception as e:
            self.logger.error(f"Error finding ESP32 port: {e}")
            return None
    
    async def connect_to_esp32(self, port: Optional[str] = None) -> bool:
        """ESP32に接続"""
        try:
            if not port:
                port = await self.find_esp32_port()
                if not port:
                    return False
            
            # 既存の接続をクローズ
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
            
            # シリアルポート設定
            serial_config = self.config.get('serial', {})
            baudrate = serial_config.get('baudrate', 115200)
            timeout = serial_config.get('timeout', 10)
            
            self.serial_port = serial.Serial(
                port=port,
                baudrate=baudrate,
                timeout=timeout,
                write_timeout=timeout
            )
            
            self.current_port = port
            self.logger.info(f"Connected to ESP32 on {port}")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to connect to ESP32: {e}")
            return False
    
    async def flash_binary(self, binary_path: str, sketch_name: str, 
                          board_type: str = "esp32") -> FlashResult:
        """バイナリファイルをフラッシュ"""
        start_time = time.time()
        
        try:
            self.logger.info(f"Flashing binary: {binary_path}")
            self.logger.log_flash(f"Starting flash for {sketch_name}")
            
            # バイナリファイルの存在確認
            binary_file = Path(binary_path)
            if not binary_file.exists():
                return FlashResult(
                    success=False,
                    sketch_name=sketch_name,
                    error_message=f"Binary file not found: {binary_path}"
                )
            
            # ESP32に接続
            if not await self.connect_to_esp32():
                return FlashResult(
                    success=False,
                    sketch_name=sketch_name,
                    error_message="Failed to connect to ESP32"
                )
            
            # フラッシュモードにリセット
            reset_success = await self.reset_controller.reset_to_flash_mode(
                board_type, self.serial_port
            )
            if not reset_success:
                self.logger.warning("Reset to flash mode failed, continuing anyway")
            
            # フラッシュ実行
            flash_result = await self._execute_flash(binary_path, board_type)
            
            # 通常モードにリセット
            await self.reset_controller.reset_to_normal_mode(
                board_type, self.serial_port
            )
            
            flash_time = time.time() - start_time
            
            if flash_result['success']:
                bytes_written = binary_file.stat().st_size
                self.logger.info(f"Flash successful: {bytes_written} bytes in {flash_time:.2f}s")
                self.logger.log_flash(f"Flash completed successfully: {bytes_written} bytes")
                
                return FlashResult(
                    success=True,
                    sketch_name=sketch_name,
                    flash_time=flash_time,
                    bytes_written=bytes_written,
                    flash_log=flash_result['output'],
                    port=self.current_port or ""
                )
            else:
                self.logger.error(f"Flash failed: {flash_result['error']}")
                self.logger.log_flash(f"Flash failed: {flash_result['error']}", "error")
                
                return FlashResult(
                    success=False,
                    sketch_name=sketch_name,
                    flash_time=flash_time,
                    flash_log=flash_result['output'],
                    error_message=flash_result['error'],
                    port=self.current_port or ""
                )
                
        except Exception as e:
            flash_time = time.time() - start_time
            error_msg = f"Flash exception: {str(e)}"
            self.logger.error(error_msg)
            self.logger.log_flash(error_msg, "error")
            
            return FlashResult(
                success=False,
                sketch_name=sketch_name,
                flash_time=flash_time,
                error_message=error_msg,
                port=self.current_port or ""
            )
    
    async def flash_build_result(self, build_result: BuildResult) -> FlashResult:
        """ビルド結果からフラッシュ"""
        if not build_result.success or not build_result.binary_path:
            return FlashResult(
                success=False,
                sketch_name=build_result.sketch_name,
                error_message="Build result is invalid or missing binary"
            )
        
        return await self.flash_binary(
            build_result.binary_path,
            build_result.sketch_name,
            build_result.board_type
        )
    
    async def _execute_flash(self, binary_path: str, board_type: str) -> Dict[str, Any]:
        """フラッシュを実行"""
        try:
            # ボード設定を取得
            board_config = self.config.get('boards', {}).get(board_type, {})
            upload_speed = board_config.get('upload_speed', 921600)
            
            # esptool.py を使用してフラッシュ
            cmd = [
                self.esptool_cmd,
                "--chip", "esp32",
                "--port", self.current_port,
                "--baud", str(upload_speed),
                "write_flash",
                "0x10000",  # ESP32のアプリケーション開始アドレス
                binary_path
            ]
            
            self.logger.debug(f"Flash command: {' '.join(cmd)}")
            
            # フラッシュ実行
            result = await self._run_command(cmd)
            
            return result
            
        except Exception as e:
            return {
                'success': False,
                'output': '',
                'error': str(e)
            }
    
    async def _run_command(self, cmd: List[str]) -> Dict[str, Any]:
        """コマンドを非同期実行"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
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
    
    async def verify_flash(self, binary_path: str) -> bool:
        """フラッシュの検証"""
        try:
            if not self.current_port:
                return False
            
            cmd = [
                self.esptool_cmd,
                "--chip", "esp32",
                "--port", self.current_port,
                "verify_flash",
                "0x10000",
                binary_path
            ]
            
            result = await self._run_command(cmd)
            
            if result['success']:
                self.logger.info("Flash verification successful")
                return True
            else:
                self.logger.warning(f"Flash verification failed: {result['error']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during flash verification: {e}")
            return False
    
    async def erase_flash(self) -> bool:
        """フラッシュを消去"""
        try:
            if not self.current_port:
                return False
            
            self.logger.info("Erasing ESP32 flash")
            
            cmd = [
                self.esptool_cmd,
                "--chip", "esp32",
                "--port", self.current_port,
                "erase_flash"
            ]
            
            result = await self._run_command(cmd)
            
            if result['success']:
                self.logger.info("Flash erase successful")
                return True
            else:
                self.logger.error(f"Flash erase failed: {result['error']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error during flash erase: {e}")
            return False
    
    def get_flash_info(self) -> Dict[str, Any]:
        """フラッシュ情報を取得"""
        info = {
            'esptool_available': False,
            'current_port': self.current_port,
            'connected': self.serial_port and self.serial_port.is_open if self.serial_port else False,
            'available_ports': []
        }
        
        try:
            # 利用可能なポート一覧
            ports = serial.tools.list_ports.comports()
            info['available_ports'] = [
                {'device': port.device, 'description': port.description}
                for port in ports
            ]
            
            # esptool.py の確認
            import subprocess
            result = subprocess.run([self.esptool_cmd, "version"], 
                                  capture_output=True, text=True, timeout=5)
            if result.returncode == 0:
                info['esptool_available'] = True
                info['esptool_version'] = result.stdout.strip()
            
        except Exception as e:
            self.logger.error(f"Error getting flash info: {e}")
        
        return info
    
    def disconnect(self):
        """ESP32から切断"""
        try:
            if self.serial_port and self.serial_port.is_open:
                self.serial_port.close()
                self.logger.info("Disconnected from ESP32")
            
            self.serial_port = None
            self.current_port = None
            
        except Exception as e:
            self.logger.error(f"Error during disconnect: {e}")
    
    def cleanup(self):
        """リソースのクリーンアップ"""
        self.disconnect()
        if self.reset_controller:
            self.reset_controller.cleanup()
        
        self.logger.info("Flash Manager cleaned up")