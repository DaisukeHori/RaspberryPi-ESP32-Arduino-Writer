"""
オーケストレーターモジュール - システム全体の状態管理と制御
"""
import asyncio
import signal
import sys
from enum import Enum
from typing import Optional, List, Dict, Any
from pathlib import Path
import time

from .logger import init_logger, get_logger
from .gpio_controller import GPIOController, LEDColor, LEDMode
from .usb_monitor import USBMonitor
from .sketch_scanner import SketchScanner, SketchInfo
from .build_manager import BuildManager
from .flash_manager import FlashManager
from .ui_renderer import UIRenderer
from .gadget_manager import GadgetManager

class SystemState(Enum):
    """システム状態"""
    STARTING = "starting"
    STANDBY = "standby"
    PC_CONNECTED = "pc_connected"
    WAIT_USB = "wait_usb"
    SELECTING = "selecting"
    BUILDING = "building"
    FLASHING = "flashing"
    COMPLETE = "complete"
    ERROR = "error"
    SHUTDOWN = "shutdown"

class ESP32WriterOrchestrator:
    """ESP32 Writer システムオーケストレーター"""
    
    def __init__(self, config_dir: str = None):
        # デフォルト設定ディレクトリの決定
        if config_dir is None:
            # プロジェクトルートからの相対パス
            project_root = Path(__file__).parent.parent
            config_dir = str(project_root / "config")
            log_dir = str(project_root / "logs")
        else:
            # 設定ディレクトリが指定された場合、ログディレクトリも同じ親ディレクトリに設定
            log_dir = str(Path(config_dir).parent / "logs")
        
        # ロガー初期化
        self.logger = init_logger(log_dir=log_dir)
        
        # 設定ディレクトリ
        self.config_dir = Path(config_dir)
        
        # システム状態
        self.current_state = SystemState.STARTING
        self.previous_state = None
        
        # モジュール初期化
        self.gpio = GPIOController(str(self.config_dir / "ui.yaml"))
        self.usb_monitor = USBMonitor()
        self.sketch_scanner = SketchScanner(str(self.config_dir / "boards.yaml"))
        self.build_manager = BuildManager(str(self.config_dir / "boards.yaml"))
        self.flash_manager = FlashManager(str(self.config_dir / "boards.yaml"))
        self.ui = UIRenderer(str(self.config_dir / "ui.yaml"))
        self.gadget_manager = GadgetManager(str(self.config_dir / "ui.yaml"))
        
        # 現在の作業データ
        self.current_usb_path: Optional[str] = None
        self.available_sketches: List[SketchInfo] = []
        self.selected_sketch_index = 0
        self.selection_timeout_task: Optional[asyncio.Task] = None
        
        # システム制御
        self.running = False
        self.shutdown_event = asyncio.Event()
        
        self.logger.info("ESP32 Writer Orchestrator initialized")
    
    async def start(self):
        """システムを開始"""
        try:
            self.logger.info("Starting ESP32 Writer system")
            self.running = True
            
            # シグナルハンドラー設定
            signal.signal(signal.SIGINT, self._signal_handler)
            signal.signal(signal.SIGTERM, self._signal_handler)
            
            # 初期化
            await self._initialize_system()
            
            # メインループ開始
            await self._main_loop()
            
        except Exception as e:
            self.logger.error(f"System startup failed: {e}")
            await self._transition_to_error(str(e))
        finally:
            await self._cleanup()
    
    async def _initialize_system(self):
        """システム初期化"""
        try:
            # USB Gadget セットアップ
            if not await self.gadget_manager.setup_gadget():
                self.logger.warning("USB Gadget setup failed, continuing without it")
            
            # GPIO コールバック設定
            self.gpio.set_button_callbacks(
                on_short_press=self._on_button_short_press,
                on_long_press=self._on_button_long_press
            )
            
            # USB 監視コールバック設定
            self.usb_monitor.set_callbacks(
                on_insert=self._on_usb_insert,
                on_remove=self._on_usb_remove
            )
            
            # USB 監視開始
            await self.usb_monitor.start_monitoring()
            
            # 初期状態に遷移
            await self._transition_to_standby()
            
            self.logger.info("System initialization completed")
            
        except Exception as e:
            self.logger.error(f"System initialization failed: {e}")
            raise
    
    async def _main_loop(self):
        """メインループ"""
        try:
            while self.running:
                # 状態に応じた処理
                if self.current_state == SystemState.STANDBY:
                    await self._handle_standby()
                elif self.current_state == SystemState.PC_CONNECTED:
                    await self._handle_pc_connected()
                elif self.current_state == SystemState.WAIT_USB:
                    await self._handle_wait_usb()
                elif self.current_state == SystemState.SELECTING:
                    await self._handle_selecting()
                elif self.current_state == SystemState.ERROR:
                    await self._handle_error()
                
                # 短い待機
                await asyncio.sleep(0.1)
                
                # シャットダウンチェック
                if self.shutdown_event.is_set():
                    break
            
        except Exception as e:
            self.logger.error(f"Main loop error: {e}")
            await self._transition_to_error(str(e))
    
    async def _handle_standby(self):
        """待機状態の処理"""
        # PC 接続チェック
        if self.gadget_manager.pc_connected:
            await self._transition_to_pc_connected()
        
        # 既存 USB デバイスチェック
        mounted_devices = self.usb_monitor.get_mounted_devices()
        if mounted_devices:
            device = mounted_devices[0]
            await self._on_usb_insert('insert', device['path'])
    
    async def _handle_pc_connected(self):
        """PC 接続状態の処理"""
        # PC 切断チェック
        if not self.gadget_manager.pc_connected:
            await self._transition_to_standby()
    
    async def _handle_wait_usb(self):
        """USB 待機状態の処理"""
        # USB が取り外された場合
        if not self.current_usb_path or not self.usb_monitor.is_device_mounted(self.current_usb_path):
            await self._transition_to_standby()
    
    async def _handle_selecting(self):
        """スケッチ選択状態の処理"""
        # USB が取り外された場合
        if not self.current_usb_path or not self.usb_monitor.is_device_mounted(self.current_usb_path):
            await self._transition_to_standby()
    
    async def _handle_error(self):
        """エラー状態の処理"""
        # USB が取り外された場合は待機状態に戻る
        if not self.current_usb_path or not self.usb_monitor.is_device_mounted(self.current_usb_path):
            await self._transition_to_standby()
    
    async def _on_usb_insert(self, action: str, path: str):
        """USB 挿入イベント"""
        try:
            if action != 'insert':
                return
            
            self.logger.info(f"USB device inserted: {path}")
            self.current_usb_path = path
            
            # スケッチをスキャン
            sketches = await self.sketch_scanner.scan_usb_device(path)
            
            if not sketches:
                await self._transition_to_error("No sketches found on USB device")
                return
            
            # スケッチをソート
            self.available_sketches = self.sketch_scanner.sort_sketches(sketches)
            self.selected_sketch_index = 0
            
            if len(self.available_sketches) == 1:
                # スケッチが1つの場合は直接待機
                await self._transition_to_wait_usb()
            else:
                # 複数スケッチの場合は選択モード
                await self._transition_to_selecting()
            
        except Exception as e:
            self.logger.error(f"Error handling USB insert: {e}")
            await self._transition_to_error(str(e))
    
    async def _on_usb_remove(self, action: str, path: str):
        """USB 取り外しイベント"""
        try:
            if action != 'remove':
                return
            
            self.logger.info(f"USB device removed: {path}")
            
            if path == self.current_usb_path:
                self.current_usb_path = None
                self.available_sketches = []
                self.selected_sketch_index = 0
                
                # 選択タイムアウトタスクをキャンセル
                if self.selection_timeout_task:
                    self.selection_timeout_task.cancel()
                    self.selection_timeout_task = None
                
                await self._transition_to_standby()
            
        except Exception as e:
            self.logger.error(f"Error handling USB remove: {e}")
    
    async def _on_button_short_press(self):
        """ボタン短押しイベント"""
        try:
            if self.current_state == SystemState.SELECTING:
                # 次のスケッチを選択
                self.selected_sketch_index = (self.selected_sketch_index + 1) % len(self.available_sketches)
                await self._update_sketch_selection()
                
                # タイムアウトをリセット
                if self.selection_timeout_task:
                    self.selection_timeout_task.cancel()
                self.selection_timeout_task = asyncio.create_task(self._selection_timeout())
            
        except Exception as e:
            self.logger.error(f"Error handling button short press: {e}")
    
    async def _on_button_long_press(self):
        """ボタン長押しイベント"""
        try:
            if self.current_state == SystemState.WAIT_USB and self.available_sketches:
                # 単一スケッチの書き込み開始
                await self._start_flash_process(self.available_sketches[0])
            elif self.current_state == SystemState.SELECTING and self.available_sketches:
                # 選択されたスケッチの書き込み開始
                selected_sketch = self.available_sketches[self.selected_sketch_index]
                await self._start_flash_process(selected_sketch)
            
        except Exception as e:
            self.logger.error(f"Error handling button long press: {e}")
    
    async def _start_flash_process(self, sketch: SketchInfo):
        """フラッシュプロセスを開始"""
        try:
            # Mass Storage を読み取り専用に設定
            if self.gadget_manager.is_enabled:
                await self.gadget_manager.set_readonly(True)
            
            # スケッチの推奨アクションを確認
            action = self.sketch_scanner.get_recommended_action(sketch)
            
            if action == "build":
                await self._build_and_flash(sketch)
            elif action == "flash":
                await self._flash_binary(sketch)
            elif action == "choose":
                # ユーザー選択が必要（簡略化のため、ソースを優先）
                await self._build_and_flash(sketch)
            else:
                await self._transition_to_error(f"Invalid sketch: {sketch.name}")
            
        except Exception as e:
            self.logger.error(f"Error starting flash process: {e}")
            await self._transition_to_error(str(e))
    
    async def _build_and_flash(self, sketch: SketchInfo):
        """ビルドしてフラッシュ"""
        try:
            # ビルド状態に遷移
            await self._transition_to_building(sketch.name)
            
            # ビルド実行
            build_result = await self.build_manager.build_sketch(sketch, self.current_usb_path)
            
            if not build_result.success:
                await self._transition_to_error(f"Build failed: {build_result.error_message}")
                return
            
            # フラッシュ状態に遷移
            await self._transition_to_flashing(sketch.name)
            
            # フラッシュ実行
            flash_result = await self.flash_manager.flash_build_result(build_result)
            
            if flash_result.success:
                await self._transition_to_complete(sketch.name, flash_result.flash_time)
            else:
                await self._transition_to_error(f"Flash failed: {flash_result.error_message}")
            
        except Exception as e:
            self.logger.error(f"Error in build and flash: {e}")
            await self._transition_to_error(str(e))
    
    async def _flash_binary(self, sketch: SketchInfo):
        """バイナリを直接フラッシュ"""
        try:
            if not sketch.binary_file:
                await self._transition_to_error("No binary file available")
                return
            
            # フラッシュ状態に遷移
            await self._transition_to_flashing(sketch.name)
            
            # フラッシュ実行
            flash_result = await self.flash_manager.flash_binary(
                sketch.binary_file, sketch.name, sketch.board_type or "esp32"
            )
            
            if flash_result.success:
                await self._transition_to_complete(sketch.name, flash_result.flash_time)
            else:
                await self._transition_to_error(f"Flash failed: {flash_result.error_message}")
            
        except Exception as e:
            self.logger.error(f"Error in flash binary: {e}")
            await self._transition_to_error(str(e))
    
    async def _selection_timeout(self):
        """スケッチ選択タイムアウト"""
        try:
            await asyncio.sleep(30)  # 30秒待機
            if self.current_state == SystemState.SELECTING:
                await self._transition_to_wait_usb()
        except asyncio.CancelledError:
            pass
    
    async def _update_sketch_selection(self):
        """スケッチ選択表示を更新"""
        if self.available_sketches:
            sketch_names = [sketch.name for sketch in self.available_sketches]
            await self.ui.show_sketch_selection(sketch_names, self.selected_sketch_index)
    
    # 状態遷移メソッド
    async def _transition_to_standby(self):
        """待機状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.STANDBY
        
        await self.gpio.set_led(LEDColor.GREEN, LEDMode.ON)
        await self.ui.show_state("standby", "Ready - Insert USB")
        
        # Mass Storage を読み書き可能に戻す
        if self.gadget_manager.is_enabled:
            await self.gadget_manager.set_readonly(False)
        
        self.logger.info("Transitioned to STANDBY")
    
    async def _transition_to_pc_connected(self):
        """PC接続状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.PC_CONNECTED
        
        await self.gpio.set_led(LEDColor.GREEN, LEDMode.ON)
        await self.ui.show_state("pc_connected", "PC Connected")
        
        # USB Gadget を有効化
        if not self.gadget_manager.is_enabled:
            await self.gadget_manager.enable_gadget()
        
        self.logger.info("Transitioned to PC_CONNECTED")
    
    async def _transition_to_wait_usb(self):
        """USB待機状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.WAIT_USB
        
        await self.gpio.set_led(LEDColor.GREEN, LEDMode.ON)
        
        if self.available_sketches:
            sketch_name = self.available_sketches[0].name
            await self.ui.show_state("wait_usb", f"Ready: {sketch_name}")
        else:
            await self.ui.show_state("wait_usb", "Press button to flash")
        
        self.logger.info("Transitioned to WAIT_USB")
    
    async def _transition_to_selecting(self):
        """スケッチ選択状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.SELECTING
        
        await self.gpio.set_led(LEDColor.GREEN, LEDMode.BLINK, 0.5)
        await self._update_sketch_selection()
        
        # タイムアウトタスクを開始
        self.selection_timeout_task = asyncio.create_task(self._selection_timeout())
        
        self.logger.info("Transitioned to SELECTING")
    
    async def _transition_to_building(self, sketch_name: str):
        """ビルド状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.BUILDING
        
        await self.gpio.set_led(LEDColor.ORANGE, LEDMode.BLINK, 0.5)
        await self.ui.show_build_progress(sketch_name, 0)
        
        self.logger.info(f"Transitioned to BUILDING: {sketch_name}")
    
    async def _transition_to_flashing(self, sketch_name: str):
        """フラッシュ状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.FLASHING
        
        await self.gpio.set_led(LEDColor.ORANGE, LEDMode.BLINK, 0.3)
        await self.ui.show_flash_progress(sketch_name, 0)
        
        self.logger.info(f"Transitioned to FLASHING: {sketch_name}")
    
    async def _transition_to_complete(self, sketch_name: str, flash_time: float = 0):
        """完了状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.COMPLETE
        
        await self.gpio.set_led(LEDColor.BLUE, LEDMode.ON)
        await self.ui.show_success(sketch_name, flash_time)
        
        # Mass Storage を読み書き可能に戻す
        if self.gadget_manager.is_enabled:
            await self.gadget_manager.set_readonly(False)
        
        self.logger.info(f"Transitioned to COMPLETE: {sketch_name}")
        
        # 5秒後に待機状態に戻る
        await asyncio.sleep(5)
        if self.current_state == SystemState.COMPLETE:
            await self._transition_to_wait_usb()
    
    async def _transition_to_error(self, error_message: str):
        """エラー状態に遷移"""
        self.previous_state = self.current_state
        self.current_state = SystemState.ERROR
        
        await self.gpio.set_led(LEDColor.RED, LEDMode.ON)
        await self.ui.show_error(error_message)
        
        # Mass Storage を読み書き可能に戻す
        if self.gadget_manager.is_enabled:
            await self.gadget_manager.set_readonly(False)
        
        self.logger.error(f"Transitioned to ERROR: {error_message}")
    
    def _signal_handler(self, signum, frame):
        """シグナルハンドラー"""
        self.logger.info(f"Received signal {signum}, shutting down...")
        self.running = False
        self.shutdown_event.set()
    
    async def _cleanup(self):
        """システムクリーンアップ"""
        try:
            self.logger.info("Cleaning up system...")
            
            # 各モジュールのクリーンアップ
            await self.usb_monitor.stop_monitoring()
            await self.gadget_manager.cleanup()
            self.gpio.cleanup()
            self.flash_manager.cleanup()
            self.ui.cleanup()
            
            # 全LED消灯
            await self.gpio.all_leds_off()
            await self.ui.clear_display()
            
            self.logger.info("System cleanup completed")
            
        except Exception as e:
            self.logger.error(f"Error during cleanup: {e}")

async def main():
    """メイン関数"""
    orchestrator = ESP32WriterOrchestrator()
    await orchestrator.start()

if __name__ == "__main__":
    asyncio.run(main())