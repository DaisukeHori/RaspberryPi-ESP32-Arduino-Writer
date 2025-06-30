"""
GPIO制御モジュール - LED とボタンの制御
"""
import asyncio
import time
from enum import Enum
from typing import Optional, Callable, Dict, Any
import yaml
from pathlib import Path

try:
    from gpiozero import LED, Button, Device
    from gpiozero.pins.pigpio import PiGPIOFactory
    # より安定したピンファクトリーを使用
    Device.pin_factory = PiGPIOFactory()
    GPIO_AVAILABLE = True
except ImportError:
    GPIO_AVAILABLE = False
    print("Warning: gpiozero not available, using mock GPIO")

from .logger import get_logger

class LEDColor(Enum):
    RED = "red"
    GREEN = "green"
    ORANGE = "orange"
    BLUE = "blue"

class LEDMode(Enum):
    OFF = "off"
    ON = "on"
    BLINK = "blink"

class MockLED:
    """GPIO が利用できない場合のモックLED"""
    def __init__(self, pin: int):
        self.pin = pin
        self.is_lit = False
    
    def on(self):
        self.is_lit = True
        print(f"Mock LED {self.pin}: ON")
    
    def off(self):
        self.is_lit = False
        print(f"Mock LED {self.pin}: OFF")
    
    def blink(self, on_time=1, off_time=1, n=None, background=True):
        print(f"Mock LED {self.pin}: BLINK")

class MockButton:
    """GPIO が利用できない場合のモックボタン"""
    def __init__(self, pin: int, pull_up: bool = True):
        self.pin = pin
        self.pull_up = pull_up
        self.when_pressed = None
        self.when_released = None
        self.when_held = None
        self.hold_time = 2
    
    def wait_for_press(self, timeout=None):
        print(f"Mock Button {self.pin}: Waiting for press")
        time.sleep(1)  # モック用の待機

class GPIOController:
    def __init__(self, config_path: str = "/opt/esp32_writer/config/ui.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # LED の初期化
        self.leds: Dict[LEDColor, Any] = {}
        self._init_leds()
        
        # ボタンの初期化
        self.button = None
        self._init_button()
        
        # 点滅タスクの管理
        self.blink_tasks: Dict[LEDColor, Optional[asyncio.Task]] = {
            color: None for color in LEDColor
        }
        
        # ボタンコールバック
        self.on_short_press: Optional[Callable] = None
        self.on_long_press: Optional[Callable] = None
        
        self.logger.info("GPIO Controller initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            # デフォルト設定
            return {
                'leds': {'red': 17, 'green': 27, 'orange': 22, 'blue': 5},
                'button': {'pin': 6, 'pull_up': True, 'short_press_time': 0.1, 'long_press_time': 2.0}
            }
    
    def _init_leds(self):
        """LED を初期化"""
        led_config = self.config.get('leds', {})
        
        for color in LEDColor:
            pin = led_config.get(color.value)
            if pin is not None:
                try:
                    if GPIO_AVAILABLE:
                        self.leds[color] = LED(pin)
                    else:
                        self.leds[color] = MockLED(pin)
                    self.logger.debug(f"LED {color.value} initialized on pin {pin}")
                except Exception as e:
                    self.logger.error(f"Failed to initialize LED {color.value}: {e}")
                    self.leds[color] = MockLED(pin)
    
    def _init_button(self):
        """ボタンを初期化"""
        button_config = self.config.get('button', {})
        pin = button_config.get('pin', 6)
        pull_up = button_config.get('pull_up', True)
        
        try:
            if GPIO_AVAILABLE:
                self.button = Button(pin, pull_up=pull_up)
                self.button.hold_time = button_config.get('long_press_time', 2.0)
                
                # コールバック設定
                self.button.when_pressed = self._on_button_pressed
                self.button.when_held = self._on_button_held
            else:
                self.button = MockButton(pin, pull_up)
                self.button.hold_time = button_config.get('long_press_time', 2.0)
            
            self.logger.debug(f"Button initialized on pin {pin}")
        except Exception as e:
            self.logger.error(f"Failed to initialize button: {e}")
            self.button = MockButton(pin, pull_up)
    
    def _on_button_pressed(self):
        """ボタン押下時のコールバック"""
        if self.on_short_press:
            asyncio.create_task(self._call_async_callback(self.on_short_press))
    
    def _on_button_held(self):
        """ボタン長押し時のコールバック"""
        if self.on_long_press:
            asyncio.create_task(self._call_async_callback(self.on_long_press))
    
    async def _call_async_callback(self, callback: Callable):
        """非同期コールバックを呼び出し"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback()
            else:
                callback()
        except Exception as e:
            self.logger.error(f"Error in button callback: {e}")
    
    async def set_led(self, color: LEDColor, mode: LEDMode, blink_interval: float = 0.5):
        """LED の状態を設定"""
        if color not in self.leds:
            self.logger.warning(f"LED {color.value} not available")
            return
        
        led = self.leds[color]
        
        # 既存の点滅タスクを停止
        if self.blink_tasks[color]:
            self.blink_tasks[color].cancel()
            self.blink_tasks[color] = None
        
        try:
            if mode == LEDMode.OFF:
                led.off()
            elif mode == LEDMode.ON:
                led.on()
            elif mode == LEDMode.BLINK:
                self.blink_tasks[color] = asyncio.create_task(
                    self._blink_led(led, blink_interval)
                )
            
            self.logger.debug(f"LED {color.value} set to {mode.value}")
        except Exception as e:
            self.logger.error(f"Failed to set LED {color.value}: {e}")
    
    async def _blink_led(self, led, interval: float):
        """LED を点滅させる"""
        try:
            while True:
                led.on()
                await asyncio.sleep(interval)
                led.off()
                await asyncio.sleep(interval)
        except asyncio.CancelledError:
            led.off()
            raise
    
    async def all_leds_off(self):
        """全ての LED を消灯"""
        for color in LEDColor:
            await self.set_led(color, LEDMode.OFF)
    
    def set_button_callbacks(self, on_short_press: Optional[Callable] = None, 
                           on_long_press: Optional[Callable] = None):
        """ボタンコールバックを設定"""
        self.on_short_press = on_short_press
        self.on_long_press = on_long_press
    
    async def wait_for_button_press(self, timeout: Optional[float] = None) -> bool:
        """ボタン押下を待機（非同期）"""
        try:
            if GPIO_AVAILABLE and hasattr(self.button, 'wait_for_press'):
                loop = asyncio.get_event_loop()
                await loop.run_in_executor(None, self.button.wait_for_press, timeout)
                return True
            else:
                # モック用の待機
                await asyncio.sleep(1)
                return True
        except Exception as e:
            self.logger.error(f"Error waiting for button press: {e}")
            return False
    
    def cleanup(self):
        """リソースのクリーンアップ"""
        # 点滅タスクを停止
        for task in self.blink_tasks.values():
            if task and not task.done():
                task.cancel()
        
        # LED を消灯
        asyncio.create_task(self.all_leds_off())
        
        self.logger.info("GPIO Controller cleaned up")