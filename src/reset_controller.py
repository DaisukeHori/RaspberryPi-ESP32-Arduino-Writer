"""
リセットコントローラーモジュール - ESP32の自動リセット制御
"""
import asyncio
import time
from typing import Optional, Dict, Any
import yaml
import serial

try:
    from gpiozero import OutputDevice
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False

from .logger import get_logger

class MockOutputDevice:
    """GPIO が利用できない場合のモック"""
    def __init__(self, pin: int):
        self.pin = pin
        self.value = False
    
    def on(self):
        self.value = True
        print(f"Mock GPIO {self.pin}: HIGH")
    
    def off(self):
        self.value = False
        print(f"Mock GPIO {self.pin}: LOW")

class ResetController:
    """ESP32 自動リセット制御"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/boards.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # GPIO ピン設定
        self.reset_pin = None
        self.boot_pin = None
        self._init_gpio()
        
        self.logger.info("Reset Controller initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {
                'gpio': {'reset_pin': 23, 'boot_pin': 24},
                'boards': {'esp32': {'reset_method': 'dtr_rts'}}
            }
    
    def _init_gpio(self):
        """GPIO ピンを初期化"""
        try:
            gpio_config = self.config.get('gpio', {})
            reset_pin_num = gpio_config.get('reset_pin', 23)
            boot_pin_num = gpio_config.get('boot_pin', 24)
            
            if GPIO_AVAILABLE:
                self.reset_pin = OutputDevice(reset_pin_num, initial_value=True)
                self.boot_pin = OutputDevice(boot_pin_num, initial_value=True)
            else:
                self.reset_pin = MockOutputDevice(reset_pin_num)
                self.boot_pin = MockOutputDevice(boot_pin_num)
                self.reset_pin.on()  # 初期値をHIGHに
                self.boot_pin.on()
            
            self.logger.debug(f"GPIO pins initialized: RESET={reset_pin_num}, BOOT={boot_pin_num}")
            
        except Exception as e:
            self.logger.error(f"Failed to initialize GPIO: {e}")
            # フォールバック
            self.reset_pin = MockOutputDevice(23)
            self.boot_pin = MockOutputDevice(24)
    
    async def reset_to_flash_mode(self, board_type: str = "esp32", 
                                 serial_port: Optional[serial.Serial] = None) -> bool:
        """ESP32をフラッシュモードにリセット"""
        try:
            board_config = self.config.get('boards', {}).get(board_type, {})
            reset_method = board_config.get('reset_method', 'dtr_rts')
            
            self.logger.info(f"Resetting ESP32 to flash mode using {reset_method}")
            
            if reset_method == 'dtr_rts' and serial_port:
                success = await self._reset_via_serial(serial_port)
            else:
                success = await self._reset_via_gpio()
            
            if success:
                self.logger.info("ESP32 reset to flash mode successful")
            else:
                self.logger.error("ESP32 reset failed")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error during reset: {e}")
            return False
    
    async def _reset_via_serial(self, serial_port: serial.Serial) -> bool:
        """シリアルポート経由でリセット（DTR/RTS制御）"""
        try:
            self.logger.debug("Performing DTR/RTS reset sequence")
            
            # ESP32のリセットシーケンス
            # DTR = EN (Reset), RTS = IO0 (Boot)
            
            # Step 1: IO0をLOWに（ブートモード）
            serial_port.rts = True  # RTS=True -> IO0=LOW
            await asyncio.sleep(0.01)
            
            # Step 2: ENをLOW->HIGHでリセット
            serial_port.dtr = True   # DTR=True -> EN=LOW (リセット)
            await asyncio.sleep(0.01)
            serial_port.dtr = False  # DTR=False -> EN=HIGH (リセット解除)
            
            # Step 3: 少し待機
            await asyncio.sleep(0.05)
            
            # Step 4: IO0をHIGHに戻す（通常動作用）
            serial_port.rts = False  # RTS=False -> IO0=HIGH
            
            self.logger.debug("DTR/RTS reset sequence completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Serial reset failed: {e}")
            return False
    
    async def _reset_via_gpio(self) -> bool:
        """GPIO経由でリセット"""
        try:
            if not self.reset_pin or not self.boot_pin:
                self.logger.error("GPIO pins not initialized")
                return False
            
            self.logger.debug("Performing GPIO reset sequence")
            
            # Step 1: IO0をLOWに（ブートモード）
            self.boot_pin.off()  # IO0 = LOW
            await asyncio.sleep(0.01)
            
            # Step 2: ENをLOW->HIGHでリセット
            self.reset_pin.off()  # EN = LOW (リセット)
            await asyncio.sleep(0.01)
            self.reset_pin.on()   # EN = HIGH (リセット解除)
            
            # Step 3: 少し待機
            await asyncio.sleep(0.05)
            
            # Step 4: IO0をHIGHに戻す
            self.boot_pin.on()    # IO0 = HIGH
            
            self.logger.debug("GPIO reset sequence completed")
            return True
            
        except Exception as e:
            self.logger.error(f"GPIO reset failed: {e}")
            return False
    
    async def reset_to_normal_mode(self, board_type: str = "esp32",
                                  serial_port: Optional[serial.Serial] = None) -> bool:
        """ESP32を通常モードにリセット"""
        try:
            board_config = self.config.get('boards', {}).get(board_type, {})
            reset_method = board_config.get('reset_method', 'dtr_rts')
            
            self.logger.info(f"Resetting ESP32 to normal mode using {reset_method}")
            
            if reset_method == 'dtr_rts' and serial_port:
                success = await self._normal_reset_via_serial(serial_port)
            else:
                success = await self._normal_reset_via_gpio()
            
            if success:
                self.logger.info("ESP32 reset to normal mode successful")
            else:
                self.logger.error("ESP32 normal reset failed")
            
            return success
            
        except Exception as e:
            self.logger.error(f"Error during normal reset: {e}")
            return False
    
    async def _normal_reset_via_serial(self, serial_port: serial.Serial) -> bool:
        """シリアル経由で通常リセット"""
        try:
            # IO0をHIGHに保つ（通常ブート）
            serial_port.rts = False  # RTS=False -> IO0=HIGH
            await asyncio.sleep(0.01)
            
            # リセットパルス
            serial_port.dtr = True   # DTR=True -> EN=LOW
            await asyncio.sleep(0.01)
            serial_port.dtr = False  # DTR=False -> EN=HIGH
            
            await asyncio.sleep(0.05)
            return True
            
        except Exception as e:
            self.logger.error(f"Serial normal reset failed: {e}")
            return False
    
    async def _normal_reset_via_gpio(self) -> bool:
        """GPIO経由で通常リセット"""
        try:
            if not self.reset_pin or not self.boot_pin:
                return False
            
            # IO0をHIGHに保つ
            self.boot_pin.on()
            await asyncio.sleep(0.01)
            
            # リセットパルス
            self.reset_pin.off()
            await asyncio.sleep(0.01)
            self.reset_pin.on()
            
            await asyncio.sleep(0.05)
            return True
            
        except Exception as e:
            self.logger.error(f"GPIO normal reset failed: {e}")
            return False
    
    def get_reset_method(self, board_type: str = "esp32") -> str:
        """指定されたボードのリセット方法を取得"""
        board_config = self.config.get('boards', {}).get(board_type, {})
        return board_config.get('reset_method', 'dtr_rts')
    
    def is_gpio_available(self) -> bool:
        """GPIO制御が利用可能かチェック"""
        return GPIO_AVAILABLE and self.reset_pin and self.boot_pin
    
    def cleanup(self):
        """リソースのクリーンアップ"""
        try:
            if self.reset_pin:
                if hasattr(self.reset_pin, 'close'):
                    self.reset_pin.close()
            if self.boot_pin:
                if hasattr(self.boot_pin, 'close'):
                    self.boot_pin.close()
            
            self.logger.info("Reset Controller cleaned up")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")