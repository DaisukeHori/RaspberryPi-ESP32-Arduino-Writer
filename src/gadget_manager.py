"""
USB Gadget マネージャーモジュール - Mass Storage デバイスとしての動作制御
"""
import asyncio
import os
import subprocess
from pathlib import Path
from typing import Dict, Any, Optional
import yaml
import time

from .logger import get_logger

class GadgetManager:
    """USB Gadget (Mass Storage) 管理"""
    
    def __init__(self, config_path: str = "/opt/esp32_writer/config/ui.yaml"):
        self.logger = get_logger()
        self.config = self._load_config(config_path)
        
        # Gadget 設定
        self.gadget_name = "esp32writer"
        self.gadget_path = f"/sys/kernel/config/usb_gadget/{self.gadget_name}"
        
        # Mass Storage 設定
        self.storage_dir = Path("/opt/esp32_writer")
        self.storage_image = self.storage_dir / "msd.img"
        self.storage_size_mb = 256
        
        # 状態管理
        self.is_enabled = False
        self.is_readonly = False
        self.pc_connected = False
        
        self.logger.info("Gadget Manager initialized")
    
    def _load_config(self, config_path: str) -> Dict[str, Any]:
        """設定ファイルを読み込み"""
        try:
            with open(config_path, 'r', encoding='utf-8') as f:
                return yaml.safe_load(f)
        except Exception as e:
            self.logger.error(f"Failed to load config: {e}")
            return {}
    
    async def setup_gadget(self) -> bool:
        """USB Gadget をセットアップ"""
        try:
            self.logger.info("Setting up USB Gadget")
            
            # Mass Storage イメージファイルを作成
            if not await self._create_storage_image():
                return False
            
            # Gadget 設定を作成
            if not await self._configure_gadget():
                return False
            
            self.logger.info("USB Gadget setup completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to setup gadget: {e}")
            return False
    
    async def _create_storage_image(self) -> bool:
        """Mass Storage イメージファイルを作成"""
        try:
            if self.storage_image.exists():
                self.logger.info(f"Storage image already exists: {self.storage_image}")
                return True
            
            self.logger.info(f"Creating storage image: {self.storage_image} ({self.storage_size_mb}MB)")
            
            # ディレクトリ作成
            self.storage_dir.mkdir(parents=True, exist_ok=True)
            
            # 空のイメージファイルを作成
            cmd = [
                "dd", "if=/dev/zero", f"of={self.storage_image}",
                f"bs=1M", f"count={self.storage_size_mb}"
            ]
            
            result = await self._run_command(cmd)
            if not result['success']:
                self.logger.error(f"Failed to create storage image: {result['error']}")
                return False
            
            # FAT32 ファイルシステムを作成
            cmd = ["mkfs.vfat", str(self.storage_image)]
            result = await self._run_command(cmd)
            if not result['success']:
                self.logger.error(f"Failed to format storage image: {result['error']}")
                return False
            
            self.logger.info("Storage image created and formatted")
            return True
            
        except Exception as e:
            self.logger.error(f"Error creating storage image: {e}")
            return False
    
    async def _configure_gadget(self) -> bool:
        """USB Gadget を設定"""
        try:
            # libcomposite モジュールをロード
            await self._run_command(["modprobe", "libcomposite"])
            
            # Gadget ディレクトリを作成
            gadget_dir = Path(self.gadget_path)
            if gadget_dir.exists():
                await self._cleanup_gadget()
            
            os.makedirs(self.gadget_path, exist_ok=True)
            
            # 基本設定
            await self._write_gadget_file("idVendor", "0x1d6b")    # Linux Foundation
            await self._write_gadget_file("idProduct", "0x0104")   # Multifunction Gadget
            await self._write_gadget_file("bcdDevice", "0x0100")
            await self._write_gadget_file("bcdUSB", "0x0200")
            
            # 文字列設定
            strings_dir = f"{self.gadget_path}/strings/0x409"
            os.makedirs(strings_dir, exist_ok=True)
            
            await self._write_gadget_file("strings/0x409/serialnumber", "esp32-writer-001")
            await self._write_gadget_file("strings/0x409/manufacturer", "RooLab")
            await self._write_gadget_file("strings/0x409/product", "ESP32 Writer")
            
            # 設定
            config_dir = f"{self.gadget_path}/configs/c.1"
            os.makedirs(config_dir, exist_ok=True)
            os.makedirs(f"{config_dir}/strings/0x409", exist_ok=True)
            
            await self._write_gadget_file("configs/c.1/strings/0x409/configuration", "Mass Storage")
            
            # Mass Storage 機能
            function_dir = f"{self.gadget_path}/functions/mass_storage.ms1"
            os.makedirs(function_dir, exist_ok=True)
            
            await self._write_gadget_file("functions/mass_storage.ms1/stall", "1")
            await self._write_gadget_file("functions/mass_storage.ms1/lun.0/cdrom", "0")
            await self._write_gadget_file("functions/mass_storage.ms1/lun.0/ro", "0")
            await self._write_gadget_file("functions/mass_storage.ms1/lun.0/file", str(self.storage_image))
            
            # 機能をコンフィグにリンク
            link_src = f"{self.gadget_path}/functions/mass_storage.ms1"
            link_dst = f"{self.gadget_path}/configs/c.1/mass_storage.ms1"
            
            if not os.path.exists(link_dst):
                os.symlink(link_src, link_dst)
            
            self.logger.info("USB Gadget configured")
            return True
            
        except Exception as e:
            self.logger.error(f"Error configuring gadget: {e}")
            return False
    
    async def _write_gadget_file(self, path: str, value: str):
        """Gadget 設定ファイルに書き込み"""
        try:
            full_path = f"{self.gadget_path}/{path}"
            with open(full_path, 'w') as f:
                f.write(value)
        except Exception as e:
            self.logger.error(f"Error writing gadget file {path}: {e}")
            raise
    
    async def enable_gadget(self) -> bool:
        """USB Gadget を有効化"""
        try:
            if self.is_enabled:
                return True
            
            self.logger.info("Enabling USB Gadget")
            
            # UDC を取得
            udc_list = await self._get_udc_list()
            if not udc_list:
                self.logger.error("No UDC available")
                return False
            
            udc = udc_list[0]
            await self._write_gadget_file("UDC", udc)
            
            self.is_enabled = True
            self.logger.info(f"USB Gadget enabled with UDC: {udc}")
            
            # 接続状態を監視開始
            asyncio.create_task(self._monitor_connection())
            
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to enable gadget: {e}")
            return False
    
    async def disable_gadget(self) -> bool:
        """USB Gadget を無効化"""
        try:
            if not self.is_enabled:
                return True
            
            self.logger.info("Disabling USB Gadget")
            
            # UDC を空にして無効化
            await self._write_gadget_file("UDC", "")
            
            self.is_enabled = False
            self.pc_connected = False
            
            self.logger.info("USB Gadget disabled")
            return True
            
        except Exception as e:
            self.logger.error(f"Failed to disable gadget: {e}")
            return False
    
    async def set_readonly(self, readonly: bool) -> bool:
        """読み取り専用モードを設定"""
        try:
            if self.is_readonly == readonly:
                return True
            
            self.logger.info(f"Setting Mass Storage to {'readonly' if readonly else 'readwrite'}")
            
            # 一時的に無効化が必要な場合のフォールバック
            if self.is_enabled:
                # まず ro フラグの直接変更を試行
                try:
                    ro_value = "1" if readonly else "0"
                    await self._write_gadget_file("functions/mass_storage.ms1/lun.0/ro", ro_value)
                    self.is_readonly = readonly
                    self.logger.info(f"Mass Storage ro flag set to {ro_value}")
                    return True
                except Exception as e:
                    self.logger.warning(f"Direct ro flag change failed: {e}")
                    # フォールバック: 無効化→再有効化
                    return await self._fallback_readonly_change(readonly)
            else:
                # Gadget が無効の場合は直接設定
                ro_value = "1" if readonly else "0"
                await self._write_gadget_file("functions/mass_storage.ms1/lun.0/ro", ro_value)
                self.is_readonly = readonly
                return True
                
        except Exception as e:
            self.logger.error(f"Failed to set readonly mode: {e}")
            return False
    
    async def _fallback_readonly_change(self, readonly: bool) -> bool:
        """読み取り専用変更のフォールバック（無効化→再有効化）"""
        try:
            self.logger.info("Using fallback method for readonly change")
            
            # 無効化
            if not await self.disable_gadget():
                return False
            
            await asyncio.sleep(0.5)
            
            # ro フラグを設定
            ro_value = "1" if readonly else "0"
            await self._write_gadget_file("functions/mass_storage.ms1/lun.0/ro", ro_value)
            
            # 再有効化
            if not await self.enable_gadget():
                return False
            
            self.is_readonly = readonly
            self.logger.info("Fallback readonly change completed")
            return True
            
        except Exception as e:
            self.logger.error(f"Fallback readonly change failed: {e}")
            return False
    
    async def _get_udc_list(self) -> list:
        """利用可能な UDC 一覧を取得"""
        try:
            udc_dir = Path("/sys/class/udc")
            if not udc_dir.exists():
                return []
            
            return [item.name for item in udc_dir.iterdir() if item.is_dir()]
            
        except Exception as e:
            self.logger.error(f"Error getting UDC list: {e}")
            return []
    
    async def _monitor_connection(self):
        """PC 接続状態を監視"""
        try:
            while self.is_enabled:
                # VBUS 状態をチェック（実装は環境依存）
                connected = await self._check_pc_connection()
                
                if connected != self.pc_connected:
                    self.pc_connected = connected
                    if connected:
                        self.logger.info("PC connected to USB Gadget")
                    else:
                        self.logger.info("PC disconnected from USB Gadget")
                
                await asyncio.sleep(1)
                
        except asyncio.CancelledError:
            pass
        except Exception as e:
            self.logger.error(f"Error monitoring connection: {e}")
    
    async def _check_pc_connection(self) -> bool:
        """PC 接続状態をチェック"""
        try:
            # 簡易的な接続チェック（実際の実装では VBUS 監視など）
            # ここでは UDC の状態ファイルをチェック
            udc_list = await self._get_udc_list()
            if not udc_list:
                return False
            
            # UDC の状態を確認
            udc_state_file = f"/sys/class/udc/{udc_list[0]}/state"
            if os.path.exists(udc_state_file):
                with open(udc_state_file, 'r') as f:
                    state = f.read().strip()
                    return state in ['configured', 'suspended']
            
            return False
            
        except Exception:
            return False
    
    async def mount_storage_image(self, mount_point: str = "/mnt/esp32_writer") -> bool:
        """Storage イメージをマウント（ファイル操作用）"""
        try:
            mount_path = Path(mount_point)
            mount_path.mkdir(parents=True, exist_ok=True)
            
            # 既にマウントされているかチェック
            result = await self._run_command(["mountpoint", "-q", str(mount_path)])
            if result['success']:
                return True
            
            # マウント実行
            cmd = ["mount", "-o", "loop", str(self.storage_image), str(mount_path)]
            result = await self._run_command(cmd)
            
            if result['success']:
                self.logger.info(f"Storage image mounted at {mount_point}")
                return True
            else:
                self.logger.error(f"Failed to mount storage image: {result['error']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error mounting storage image: {e}")
            return False
    
    async def unmount_storage_image(self, mount_point: str = "/mnt/esp32_writer") -> bool:
        """Storage イメージをアンマウント"""
        try:
            cmd = ["umount", mount_point]
            result = await self._run_command(cmd)
            
            if result['success']:
                self.logger.info(f"Storage image unmounted from {mount_point}")
                return True
            else:
                self.logger.warning(f"Failed to unmount storage image: {result['error']}")
                return False
                
        except Exception as e:
            self.logger.error(f"Error unmounting storage image: {e}")
            return False
    
    async def _run_command(self, cmd: list) -> Dict[str, Any]:
        """コマンドを非同期実行"""
        try:
            process = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE
            )
            
            stdout, stderr = await process.communicate()
            
            return {
                'success': process.returncode == 0,
                'output': stdout.decode('utf-8', errors='ignore'),
                'error': stderr.decode('utf-8', errors='ignore'),
                'returncode': process.returncode
            }
            
        except Exception as e:
            return {
                'success': False,
                'output': '',
                'error': str(e),
                'returncode': -1
            }
    
    async def _cleanup_gadget(self):
        """既存の Gadget 設定をクリーンアップ"""
        try:
            # UDC を無効化
            if os.path.exists(f"{self.gadget_path}/UDC"):
                await self._write_gadget_file("UDC", "")
            
            # シンボリックリンクを削除
            link_path = f"{self.gadget_path}/configs/c.1/mass_storage.ms1"
            if os.path.exists(link_path):
                os.unlink(link_path)
            
            # ディレクトリを削除
            if os.path.exists(self.gadget_path):
                import shutil
                shutil.rmtree(self.gadget_path)
            
        except Exception as e:
            self.logger.error(f"Error cleaning up gadget: {e}")
    
    def get_gadget_info(self) -> Dict[str, Any]:
        """Gadget 情報を取得"""
        return {
            'enabled': self.is_enabled,
            'readonly': self.is_readonly,
            'pc_connected': self.pc_connected,
            'storage_image': str(self.storage_image),
            'storage_size_mb': self.storage_size_mb,
            'gadget_path': self.gadget_path
        }
    
    async def cleanup(self):
        """リソースのクリーンアップ"""
        try:
            await self.disable_gadget()
            await self._cleanup_gadget()
            self.logger.info("Gadget Manager cleaned up")
            
        except Exception as e:
            self.logger.error(f"Error during gadget cleanup: {e}")