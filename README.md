# ESP32 Writer

Raspberry Pi ベースの ESP32 スケッチ書き込みシステム

## 概要

USB メモリに入れた Arduino スケッチ(.ino) またはビルド済みバイナリ(.bin/.hex) を、Raspberry Pi ベースのハンディ機材が自動検出し、ESP32 へ書き込むシステムです。

## 主な機能

- ✅ USB メモリ内のスケッチ自動検出
- ✅ Arduino CLI による自動ビルド
- ✅ ESP32 への自動書き込み（USB-Serial 経由）
- ✅ 4色LED による状態表示（赤=エラー、緑=待機、橙=処理中、青=完了）
- ✅ OLED/TFT ディスプレイでの進捗表示
- ✅ ハードウェアボタンによる操作
- ✅ 複数スケッチ選択機能
- ✅ USB Mass Storage としての動作（PC 接続時）
- ✅ 外部ライブラリの自動インストール
- ✅ ビルド済みバイナリの直接書き込み

## ハードウェア要件

### 推奨構成A（低コスト）
- Raspberry Pi Zero 2 W
- 0.96" I2C OLED ディスプレイ (SSD1306)
- LED 4個（赤、緑、橙、青）+ 330Ω抵抗
- タクトスイッチ 1個
- USB-Serial 変換モジュール (CP2102/CH340)

### 推奨構成B（高性能）
- Raspberry Pi 4 Model B (2GB)
- 2.4" SPI TFT または 5" HDMI ディスプレイ
- 同上の LED・ボタン・USB-Serial

### GPIO 配線

| 機能 | GPIO | 備考 |
|------|------|------|
| 赤LED | 17 | 330Ω抵抗経由 |
| 緑LED | 27 | 330Ω抵抗経由 |
| 橙LED | 22 | 330Ω抵抗経由 |
| 青LED | 5 | 330Ω抵抗経由 |
| ボタン | 6 | プルアップ入力 |
| リセット制御 | 23 | ESP32 EN (オプション) |
| ブート制御 | 24 | ESP32 IO0 (オプション) |

## ソフトウェア要件

- Raspberry Pi OS (Bullseye 以降)
- Python 3.9+
- Arduino CLI
- esptool.py

## インストール

### 1. リポジトリのクローン

```bash
git clone https://github.com/your-repo/esp32-writer.git
cd esp32-writer
```

### 2. セットアップスクリプト実行

```bash
chmod +x scripts/setup.sh
sudo ./scripts/setup.sh
```

### 3. システム再起動

```bash
sudo reboot
```

## 使用方法

### 基本的な使い方

1. **USB メモリの準備**
   ```
   /
   ├── my_project.ino          # Arduino スケッチ
   ├── another_project.ino     # 別のスケッチ
   ├── build/                  # ビルド済みバイナリ（オプション）
   │   ├── my_project.bin
   │   └── another_project.bin
   └── libraries/              # 外部ライブラリ（オプション）
       ├── WiFiManager/
       └── ArduinoJson/
   ```

2. **USB メモリを挿入**
   - 緑LED が点灯し、スケッチが検出されます

3. **スケッチ選択**（複数ある場合）
   - ボタン短押し：次のスケッチを選択
   - OLED にスケッチ名が表示されます

4. **書き込み開始**
   - ボタン長押し（2秒）：書き込み開始
   - 橙LED 点滅：ビルド・書き込み中
   - 青LED 点灯：完了

### PC との連携

1. **PC に接続**
   - USB-C ケーブルで PC と接続
   - Mass Storage デバイスとして認識されます

2. **ファイル転送**
   - スケッチファイルをドラッグ＆ドロップ
   - ビルド済みバイナリも配置可能

3. **書き込み実行**
   - PC から切断後、ボタン操作で書き込み

## 設定

### ボード設定 (`config/boards.yaml`)

```yaml
boards:
  esp32:
    fqbn: "esp32:esp32:esp32"
    upload_speed: 921600
    reset_method: "dtr_rts"
  
  esp32s3:
    fqbn: "esp32:esp32:esp32s3"
    upload_speed: 921600
    reset_method: "dtr_rts"
```

### UI設定 (`config/ui.yaml`)

```yaml
display:
  type: "oled"  # oled, tft, hdmi
  width: 128
  height: 64
  i2c_address: 0x3C

leds:
  red: 17
  green: 27
  orange: 22
  blue: 5

button:
  pin: 6
  long_press_time: 2.0
```

## トラブルシューティング

### サービス状態確認

```bash
sudo systemctl status esp32-writer
```

### ログ確認

```bash
# システムログ
sudo journalctl -u esp32-writer -f

# 専用ログ
tail -f /opt/esp32_writer/logs/system.log
tail -f /opt/esp32_writer/logs/build.log
tail -f /opt/esp32_writer/logs/flash.log
```

### 手動実行

```bash
cd /opt/esp32_writer
source venv/bin/activate
python bin/orchestrator.py
```

### よくある問題

1. **LED が点灯しない**
   - GPIO 配線を確認
   - 抵抗値を確認（330Ω推奨）

2. **OLED に何も表示されない**
   - I2C 配線を確認
   - I2C アドレスを確認（通常 0x3C）

3. **ESP32 が検出されない**
   - USB-Serial ドライバーを確認
   - ケーブル接続を確認

4. **ビルドが失敗する**
   - Arduino CLI の設定を確認
   - 必要なライブラリがインストールされているか確認

## 開発

### 開発環境セットアップ

```bash
python3 -m venv venv
source venv/bin/activate
pip install -r requirements.txt
```

### テスト実行

```bash
# 単体テスト
python -m pytest tests/

# 統合テスト
python tests/integration_test.py
```

### モジュール構成

```
src/
├── orchestrator.py      # メイン制御
├── gpio_controller.py   # LED・ボタン制御
├── usb_monitor.py       # USB 監視
├── sketch_scanner.py    # スケッチ検出
├── build_manager.py     # ビルド制御
├── flash_manager.py     # 書き込み制御
├── reset_controller.py  # ESP32 リセット制御
├── ui_renderer.py       # ディスプレイ制御
├── gadget_manager.py    # USB Gadget 制御
└── logger.py           # ログ管理
```

## ライセンス

MIT License

## 貢献

プルリクエストやイシューの報告を歓迎します。

## 作者

RooLab - ESP32 Writer Project

---

## 更新履歴

### v1.0.0 (2025-06-30)
- 初回リリース
- 基本的な書き込み機能
- USB Mass Storage 対応
- 複数スケッチ選択機能
- 外部ライブラリ自動インストール