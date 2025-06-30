"""
GPIO Controller モジュールのテスト
"""
import unittest
from unittest.mock import Mock, patch, AsyncMock
import asyncio
import sys
from pathlib import Path

# プロジェクトルートをパスに追加
sys.path.insert(0, str(Path(__file__).parent.parent))

from src.gpio_controller import GPIOController, LEDColor, LEDMode


class TestGPIOController(unittest.TestCase):
    """GPIO Controller のテストクラス"""
    
    def setUp(self):
        """テストのセットアップ"""
        self.config_path = str(Path(__file__).parent.parent / "config" / "ui.yaml")
        
    def test_init(self):
        """初期化テスト"""
        controller = GPIOController(self.config_path)
        self.assertIsNotNone(controller)
        self.assertIsNotNone(controller.leds)
        self.assertIsNotNone(controller.button)
        
    def test_led_colors(self):
        """LED色の定義テスト"""
        self.assertEqual(LEDColor.RED.value, "red")
        self.assertEqual(LEDColor.GREEN.value, "green")
        self.assertEqual(LEDColor.ORANGE.value, "orange")
        self.assertEqual(LEDColor.BLUE.value, "blue")
        
    def test_led_modes(self):
        """LEDモードの定義テスト"""
        self.assertEqual(LEDMode.OFF.value, "off")
        self.assertEqual(LEDMode.ON.value, "on")
        self.assertEqual(LEDMode.BLINK.value, "blink")
        
    @patch('src.gpio_controller.gpiozero')
    def test_set_led_on(self, mock_gpiozero):
        """LED点灯テスト"""
        controller = GPIOController(self.config_path)
        
        # 非同期関数のテスト
        async def test_async():
            await controller.set_led(LEDColor.RED, LEDMode.ON)
            # MockLEDのon()が呼ばれることを確認
            controller.leds[LEDColor.RED].on.assert_called_once()
            
        asyncio.run(test_async())
        
    @patch('src.gpio_controller.gpiozero')
    def test_set_led_off(self, mock_gpiozero):
        """LED消灯テスト"""
        controller = GPIOController(self.config_path)
        
        async def test_async():
            await controller.set_led(LEDColor.GREEN, LEDMode.OFF)
            controller.leds[LEDColor.GREEN].off.assert_called_once()
            
        asyncio.run(test_async())
        
    @patch('src.gpio_controller.gpiozero')
    def test_all_leds_off(self, mock_gpiozero):
        """全LED消灯テスト"""
        controller = GPIOController(self.config_path)
        
        async def test_async():
            await controller.all_leds_off()
            for led in controller.leds.values():
                led.off.assert_called_once()
                
        asyncio.run(test_async())
        
    def test_button_callbacks(self):
        """ボタンコールバック設定テスト"""
        controller = GPIOController(self.config_path)
        
        mock_short_press = Mock()
        mock_long_press = Mock()
        
        controller.set_button_callbacks(
            on_short_press=mock_short_press,
            on_long_press=mock_long_press
        )
        
        self.assertEqual(controller.on_short_press_callback, mock_short_press)
        self.assertEqual(controller.on_long_press_callback, mock_long_press)
        
    def test_cleanup(self):
        """クリーンアップテスト"""
        controller = GPIOController(self.config_path)
        
        # クリーンアップが例外を投げないことを確認
        try:
            controller.cleanup()
        except Exception as e:
            self.fail(f"Cleanup raised exception: {e}")


class TestGPIOControllerIntegration(unittest.TestCase):
    """GPIO Controller の統合テスト"""
    
    @patch('src.gpio_controller.gpiozero')
    def test_led_blink_sequence(self, mock_gpiozero):
        """LED点滅シーケンステスト"""
        controller = GPIOController()
        
        async def test_sequence():
            # 赤LED点滅
            await controller.set_led(LEDColor.RED, LEDMode.BLINK, 0.5)
            await asyncio.sleep(0.1)
            
            # 緑LED点灯
            await controller.set_led(LEDColor.GREEN, LEDMode.ON)
            
            # 全消灯
            await controller.all_leds_off()
            
        asyncio.run(test_sequence())


if __name__ == '__main__':
    unittest.main()
