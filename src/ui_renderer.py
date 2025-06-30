"""
UI レンダラーモジュール - ディスプレイへの表示制御
"""
import asyncio
from typing import Dict, Any, Optional, List
from pathlib import Path
import yaml
from datetime import datetime

try:
    # OLED ディスプレイ用
    from luma.core.interface.serial import i2c
    from luma.core.render import canvas
    from luma.oled.device import ssd1306
    from PIL import Image, ImageDraw, ImageFont
    DISPLAY_AVAILABLE = True
except ImportError:
    DISPLAY_AVAILABLE = False

from .logger import get_logger

class MockDisplay:
    """ディスプレイが利用できない場合のモック"""
    def __init__(self, width=128, height=64):
        self.width = width
        self.height = height
        self.mode = "1"
    
    def display(self, image):
        print(f"Mock Display: Showing image {image.size}")

class UIRenderer:
    """UI 表示制御"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/ui.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # ディスプレイ設定
        self.display = None
        self.display_type = self.config.get('display', {}).get('type', 'oled')
        self.width = self.config.get('display', {}).get('width', 128)
        self.height = self.config.get('display', {}).get('height', 64)
        
        # フォント設定
        self.font_small = None
        self.font_medium = None
        self.font_large = None
        
        # 初期化
        self._init_display()
        self._init_fonts()
        
        # 現在の表示状態
        self.current_state = "standby"
        self.current_message = ""
        self.progress = 0
        
        self.logger.info(f"UI Renderer initialized ({self.display_type})")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {
                'display': {'type': 'oled', 'width': 128, 'height': 64, 'i2c_address': 0x3C},
                'messages': {}
            }
    
    def _init_display(self):
        """ディスプレイを初期化"""
        try:
            if self.display_type == 'oled' and DISPLAY_AVAILABLE:
                # I2C OLED ディスプレイ
                i2c_address = self.config.get('display', {}).get('i2c_address', 0x3C)
                serial = i2c(port=1, address=i2c_address)
                self.display = ssd1306(serial, width=self.width, height=self.height)
                self.logger.info(f"OLED display initialized: {self.width}x{self.height}")
            else:
                # モックディスプレイ
                self.display = MockDisplay(self.width, self.height)
                self.logger.warning("Using mock display")
                
        except Exception as e:
            self.logger.error(f"Failed to initialize display: {e}")
            self.display = MockDisplay(self.width, self.height)
    
    def _init_fonts(self):
        """フォントを初期化"""
        try:
            if DISPLAY_AVAILABLE:
                # システムフォントを使用
                self.font_small = ImageFont.load_default()
                self.font_medium = ImageFont.load_default()
                self.font_large = ImageFont.load_default()
            else:
                # モック用
                self.font_small = None
                self.font_medium = None
                self.font_large = None
                
        except Exception as e:
            self.logger.error(f"Failed to initialize fonts: {e}")
    
    async def show_state(self, state: str, message: str = "", progress: int = 0, 
                        extra_info: Optional[Dict[str, Any]] = None):
        """状態を表示"""
        try:
            self.current_state = state
            self.current_message = message
            self.progress = progress
            
            # メッセージ設定から表示テキストを取得
            messages = self.config.get('messages', {})
            display_message = messages.get(state, message or state.title())
            
            if self.display_type == 'oled':
                await self._render_oled(state, display_message, progress, extra_info)
            elif self.display_type == 'hdmi':
                await self._render_hdmi(state, display_message, progress, extra_info)
            else:
                await self._render_console(state, display_message, progress, extra_info)
                
        except Exception as e:
            self.logger.error(f"Error showing state: {e}")
    
    async def _render_oled(self, state: str, message: str, progress: int,
                          extra_info: Optional[Dict[str, Any]]):
        """OLED ディスプレイに描画"""
        if not DISPLAY_AVAILABLE:
            # ディスプレイライブラリが利用できない場合はコンソール出力
            print(f"OLED Display: {state.upper()} - {message}")
            if progress > 0:
                print(f"Progress: {progress}%")
            return
            
        try:
            # 画像を作成
            image = Image.new(self.display.mode, (self.display.width, self.display.height))
            draw = ImageDraw.Draw(image)
            
            # 背景をクリア
            draw.rectangle([(0, 0), (self.display.width, self.display.height)], fill=0)
            
            y_pos = 0
            
            # タイトル行
            title = f"ESP32 Writer"
            draw.text((2, y_pos), title, font=self.font_small, fill=1)
            y_pos += 12
            
            # 区切り線
            draw.line([(0, y_pos), (self.display.width, y_pos)], fill=1)
            y_pos += 4
            
            # 状態表示
            state_text = f"State: {state.upper()}"
            draw.text((2, y_pos), state_text, font=self.font_small, fill=1)
            y_pos += 12
            
            # メッセージ表示
            if message:
                # 長いメッセージは折り返し
                lines = self._wrap_text(message, 20)
                for line in lines[:2]:  # 最大2行
                    draw.text((2, y_pos), line, font=self.font_small, fill=1)
                    y_pos += 10
            
            # プログレスバー
            if progress > 0:
                bar_width = self.display.width - 8
                bar_height = 6
                bar_x = 4
                bar_y = self.display.height - bar_height - 4
                
                # 外枠
                draw.rectangle([(bar_x, bar_y), (bar_x + bar_width, bar_y + bar_height)], 
                             outline=1, fill=0)
                
                # プログレス
                progress_width = int((bar_width - 2) * progress / 100)
                if progress_width > 0:
                    draw.rectangle([(bar_x + 1, bar_y + 1), 
                                  (bar_x + 1 + progress_width, bar_y + bar_height - 1)], 
                                 fill=1)
                
                # パーセント表示
                percent_text = f"{progress}%"
                text_width = draw.textlength(percent_text, font=self.font_small)
                draw.text((self.display.width - text_width - 2, bar_y - 12), 
                         percent_text, font=self.font_small, fill=1)
            
            # 追加情報
            if extra_info:
                info_y = self.display.height - 24
                if 'sketch_count' in extra_info:
                    info_text = f"Sketches: {extra_info['sketch_count']}"
                    draw.text((2, info_y), info_text, font=self.font_small, fill=1)
                elif 'selected_sketch' in extra_info:
                    sketch_name = extra_info['selected_sketch']
                    if len(sketch_name) > 15:
                        sketch_name = sketch_name[:12] + "..."
                    draw.text((2, info_y), f">{sketch_name}", font=self.font_small, fill=1)
            
            # 時刻表示
            time_str = datetime.now().strftime("%H:%M")
            time_width = draw.textlength(time_str, font=self.font_small)
            draw.text((self.display.width - time_width - 2, 2), 
                     time_str, font=self.font_small, fill=1)
            
            # ディスプレイに表示
            self.display.display(image)
            
        except Exception as e:
            self.logger.error(f"Error rendering OLED: {e}")
    
    async def _render_hdmi(self, state: str, message: str, progress: int, 
                          extra_info: Optional[Dict[str, Any]]):
        """HDMI ディスプレイに描画（将来の拡張用）"""
        # 現在はコンソール出力にフォールバック
        await self._render_console(state, message, progress, extra_info)
    
    async def _render_console(self, state: str, message: str, progress: int, 
                             extra_info: Optional[Dict[str, Any]]):
        """コンソールに出力"""
        try:
            output_lines = [
                "=" * 40,
                f"ESP32 Writer - {datetime.now().strftime('%H:%M:%S')}",
                f"State: {state.upper()}",
                f"Message: {message}",
            ]
            
            if progress > 0:
                bar_length = 20
                filled_length = int(bar_length * progress / 100)
                bar = "█" * filled_length + "░" * (bar_length - filled_length)
                output_lines.append(f"Progress: [{bar}] {progress}%")
            
            if extra_info:
                for key, value in extra_info.items():
                    output_lines.append(f"{key.title()}: {value}")
            
            output_lines.append("=" * 40)
            
            print("\n".join(output_lines))
            
        except Exception as e:
            self.logger.error(f"Error rendering console: {e}")
    
    def _wrap_text(self, text: str, width: int) -> List[str]:
        """テキストを指定幅で折り返し"""
        words = text.split()
        lines = []
        current_line = ""
        
        for word in words:
            if len(current_line + " " + word) <= width:
                if current_line:
                    current_line += " " + word
                else:
                    current_line = word
            else:
                if current_line:
                    lines.append(current_line)
                current_line = word
        
        if current_line:
            lines.append(current_line)
        
        return lines
    
    async def show_sketch_selection(self, sketches: List[str], selected_index: int):
        """スケッチ選択画面を表示"""
        try:
            if not sketches:
                await self.show_state("error", "No sketches found")
                return
            
            selected_sketch = sketches[selected_index] if selected_index < len(sketches) else sketches[0]
            
            extra_info = {
                'sketch_count': len(sketches),
                'selected_sketch': selected_sketch,
                'index': f"{selected_index + 1}/{len(sketches)}"
            }
            
            await self.show_state("selecting", f"Select sketch ({selected_index + 1}/{len(sketches)})", 
                                extra_info=extra_info)
            
        except Exception as e:
            self.logger.error(f"Error showing sketch selection: {e}")
    
    async def show_build_progress(self, sketch_name: str, progress: int):
        """ビルド進捗を表示"""
        await self.show_state("building", f"Building {sketch_name}", progress)
    
    async def show_flash_progress(self, sketch_name: str, progress: int):
        """フラッシュ進捗を表示"""
        await self.show_state("flashing", f"Flashing {sketch_name}", progress)
    
    async def show_success(self, sketch_name: str, flash_time: float = 0):
        """成功画面を表示"""
        message = f"Success! {sketch_name}"
        if flash_time > 0:
            message += f" ({flash_time:.1f}s)"
        await self.show_state("complete", message)
    
    async def show_error(self, error_message: str):
        """エラー画面を表示"""
        await self.show_state("error", error_message)
    
    async def clear_display(self):
        """ディスプレイをクリア"""
        try:
            if self.display_type == 'oled' and DISPLAY_AVAILABLE:
                image = Image.new(self.display.mode, (self.display.width, self.display.height))
                self.display.display(image)
            else:
                print("\n" * 10)  # コンソールクリア
                
        except Exception as e:
            self.logger.error(f"Error clearing display: {e}")
    
    def get_display_info(self) -> Dict[str, Any]:
        """ディスプレイ情報を取得"""
        return {
            'type': self.display_type,
            'width': self.width,
            'height': self.height,
            'available': DISPLAY_AVAILABLE,
            'current_state': self.current_state,
            'current_message': self.current_message
        }
    
    def cleanup(self):
        """リソースのクリーンアップ"""
        try:
            if self.display and hasattr(self.display, 'cleanup'):
                self.display.cleanup()
            
            self.logger.info("UI Renderer cleaned up")
            
        except Exception as e:
            self.logger.error(f"Error during UI cleanup: {e}")