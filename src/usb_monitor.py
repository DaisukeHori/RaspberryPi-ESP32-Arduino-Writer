"""
USB監視モジュール - USB挿抜の検出
"""
import asyncio
import os
import time
from pathlib import Path
from typing import Optional, Callable, List, Dict, Any
from watchdog.observers import Observer
from watchdog.events import FileSystemEventHandler
import psutil

from .logger import get_logger

class USBEventHandler(FileSystemEventHandler):
    """USB イベントハンドラー"""
    
    def __init__(self, callback: Callable):
        super().__init__()
        self.callback = callback
        self.logger = get_logger()
    
    def on_created(self, event):
        if event.is_directory and '/media/' in event.src_path:
            self.logger.info(f"USB device mounted: {event.src_path}")
            asyncio.create_task(self._call_callback('insert', event.src_path))
    
    def on_deleted(self, event):
        if event.is_directory and '/media/' in event.src_path:
            self.logger.info(f"USB device unmounted: {event.src_path}")
            asyncio.create_task(self._call_callback('remove', event.src_path))
    
    async def _call_callback(self, action: str, path: str):
        """コールバックを非同期で呼び出し"""
        try:
            if asyncio.iscoroutinefunction(self.callback):
                await self.callback(action, path)
            else:
                self.callback(action, path)
        except Exception as e:
            self.logger.error(f"Error in USB callback: {e}")

class USBMonitor:
    """USB デバイスの監視"""
    
    def __init__(self, mount_base: str = "/media"):
        self.logger = get_logger()
        self.mount_base = Path(mount_base)
        self.observer: Optional[Observer] = None
        self.event_handler: Optional[USBEventHandler] = None
        
        # コールバック
        self.on_usb_insert: Optional[Callable] = None
        self.on_usb_remove: Optional[Callable] = None
        
        # 現在マウントされているUSBデバイス
        self.mounted_devices: Dict[str, Dict[str, Any]] = {}
        
        self.logger.info("USB Monitor initialized")
    
    def set_callbacks(self, on_insert: Optional[Callable] = None, 
                     on_remove: Optional[Callable] = None):
        """コールバックを設定"""
        self.on_usb_insert = on_insert
        self.on_usb_remove = on_remove
    
    async def start_monitoring(self):
        """USB監視を開始"""
        try:
            # 既存のマウントデバイスをスキャン
            await self._scan_existing_devices()
            
            # ファイルシステム監視を開始
            self.event_handler = USBEventHandler(self._on_usb_event)
            self.observer = Observer()
            self.observer.schedule(self.event_handler, str(self.mount_base), recursive=True)
            self.observer.start()
            
            self.logger.info("USB monitoring started")
            
            # 定期的なスキャンタスクを開始
            asyncio.create_task(self._periodic_scan())
            
        except Exception as e:
            self.logger.error(f"Failed to start USB monitoring: {e}")
    
    async def stop_monitoring(self):
        """USB監視を停止"""
        if self.observer:
            self.observer.stop()
            self.observer.join()
            self.observer = None
        
        self.logger.info("USB monitoring stopped")
    
    async def _scan_existing_devices(self):
        """既存のマウントデバイスをスキャン"""
        try:
            if not self.mount_base.exists():
                self.logger.warning(f"Mount base {self.mount_base} does not exist")
                return
            
            for mount_point in self.mount_base.iterdir():
                if mount_point.is_dir() and self._is_usb_device(str(mount_point)):
                    device_info = await self._get_device_info(str(mount_point))
                    self.mounted_devices[str(mount_point)] = device_info
                    self.logger.info(f"Found existing USB device: {mount_point}")
                    
                    # 挿入イベントを発火
                    if self.on_usb_insert:
                        await self._call_callback(self.on_usb_insert, 'insert', str(mount_point))
        
        except Exception as e:
            self.logger.error(f"Error scanning existing devices: {e}")
    
    async def _periodic_scan(self):
        """定期的なUSBデバイススキャン（フォールバック）"""
        while True:
            try:
                await asyncio.sleep(5)  # 5秒間隔
                await self._check_device_changes()
            except asyncio.CancelledError:
                break
            except Exception as e:
                self.logger.error(f"Error in periodic scan: {e}")
    
    async def _check_device_changes(self):
        """デバイスの変更をチェック"""
        current_devices = set()
        
        try:
            if self.mount_base.exists():
                for mount_point in self.mount_base.iterdir():
                    if mount_point.is_dir() and self._is_usb_device(str(mount_point)):
                        current_devices.add(str(mount_point))
        except Exception as e:
            self.logger.error(f"Error checking device changes: {e}")
            return
        
        previous_devices = set(self.mounted_devices.keys())
        
        # 新しいデバイス
        new_devices = current_devices - previous_devices
        for device in new_devices:
            device_info = await self._get_device_info(device)
            self.mounted_devices[device] = device_info
            self.logger.info(f"New USB device detected: {device}")
            if self.on_usb_insert:
                await self._call_callback(self.on_usb_insert, 'insert', device)
        
        # 削除されたデバイス
        removed_devices = previous_devices - current_devices
        for device in removed_devices:
            del self.mounted_devices[device]
            self.logger.info(f"USB device removed: {device}")
            if self.on_usb_remove:
                await self._call_callback(self.on_usb_remove, 'remove', device)
    
    def _is_usb_device(self, path: str) -> bool:
        """USBデバイスかどうかを判定"""
        try:
            # マウントポイントの情報を取得
            for partition in psutil.disk_partitions():
                if partition.mountpoint == path:
                    # USB デバイスの特徴を確認
                    if 'usb' in partition.device.lower() or 'removable' in partition.opts:
                        return True
                    # ファイルシステムタイプでも判定
                    if partition.fstype in ['vfat', 'exfat', 'ntfs']:
                        return True
            
            # フォールバック: ディレクトリ名での判定
            path_name = Path(path).name.lower()
            if any(keyword in path_name for keyword in ['usb', 'disk', 'drive']):
                return True
                
            return False
        except Exception as e:
            self.logger.error(f"Error checking USB device: {e}")
            return False
    
    async def _get_device_info(self, path: str) -> Dict[str, Any]:
        """デバイス情報を取得"""
        try:
            path_obj = Path(path)
            stat = path_obj.stat()
            
            # ディスク使用量情報
            usage = psutil.disk_usage(path)
            
            return {
                'path': path,
                'name': path_obj.name,
                'mount_time': time.time(),
                'total_size': usage.total,
                'free_size': usage.free,
                'used_size': usage.used
            }
        except Exception as e:
            self.logger.error(f"Error getting device info for {path}: {e}")
            return {'path': path, 'name': Path(path).name, 'mount_time': time.time()}
    
    async def _on_usb_event(self, action: str, path: str):
        """USB イベントハンドラー"""
        if action == 'insert':
            if self._is_usb_device(path):
                device_info = await self._get_device_info(path)
                self.mounted_devices[path] = device_info
                if self.on_usb_insert:
                    await self._call_callback(self.on_usb_insert, action, path)
        
        elif action == 'remove':
            if path in self.mounted_devices:
                del self.mounted_devices[path]
            if self.on_usb_remove:
                await self._call_callback(self.on_usb_remove, action, path)
    
    async def _call_callback(self, callback: Callable, action: str, path: str):
        """コールバックを呼び出し"""
        try:
            if asyncio.iscoroutinefunction(callback):
                await callback(action, path)
            else:
                callback(action, path)
        except Exception as e:
            self.logger.error(f"Error in USB callback: {e}")
    
    def get_mounted_devices(self) -> List[Dict[str, Any]]:
        """マウントされているデバイス一覧を取得"""
        return list(self.mounted_devices.values())
    
    def is_device_mounted(self, path: str) -> bool:
        """指定パスのデバイスがマウントされているかチェック"""
        return path in self.mounted_devices
    
    async def wait_for_usb_insert(self, timeout: Optional[float] = None) -> Optional[str]:
        """USB挿入を待機"""
        insert_event = asyncio.Event()
        inserted_path = None
        
        async def on_insert(action: str, path: str):
            nonlocal inserted_path
            if action == 'insert':
                inserted_path = path
                insert_event.set()
        
        original_callback = self.on_usb_insert
        self.on_usb_insert = on_insert
        
        try:
            await asyncio.wait_for(insert_event.wait(), timeout=timeout)
            return inserted_path
        except asyncio.TimeoutError:
            return None
        finally:
            self.on_usb_insert = original_callback