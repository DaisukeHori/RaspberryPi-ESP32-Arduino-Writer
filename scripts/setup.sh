#!/bin/bash
# ESP32 Writer セットアップスクリプト

set -e

echo "ESP32 Writer セットアップを開始します..."

# 変数設定
INSTALL_DIR="/opt/esp32_writer"
SERVICE_NAME="esp32-writer"
USER="pi"

# root権限チェック
if [[ $EUID -ne 0 ]]; then
   echo "このスクリプトはroot権限で実行してください (sudo ./setup.sh)" 
   exit 1
fi

# システムパッケージの更新とインストール
echo "システムパッケージを更新・インストール中..."
apt update
apt install -y \
    git \
    python3 \
    python3-venv \
    python3-pip \
    arduino-cli \
    esptool \
    python3-libgpiod \
    i2c-tools \
    usbutils \
    dosfstools

# インストールディレクトリ作成
echo "インストールディレクトリを作成中..."
mkdir -p $INSTALL_DIR
mkdir -p $INSTALL_DIR/logs
mkdir -p $INSTALL_DIR/ui/fonts
mkdir -p $INSTALL_DIR/ui/images

# プロジェクトファイルをコピー
echo "プロジェクトファイルをコピー中..."
cp -r src/ $INSTALL_DIR/
cp -r config/ $INSTALL_DIR/
cp -r bin/ $INSTALL_DIR/
cp requirements.txt $INSTALL_DIR/

# Python仮想環境作成
echo "Python仮想環境を作成中..."
python3 -m venv $INSTALL_DIR/venv
source $INSTALL_DIR/venv/bin/activate
pip install --upgrade pip
pip install -r $INSTALL_DIR/requirements.txt

# 追加のPythonパッケージ（ディスプレイ用）
pip install luma.oled luma.core

# Arduino CLI セットアップ
echo "Arduino CLI をセットアップ中..."
sudo -u $USER arduino-cli config init
sudo -u $USER arduino-cli core update-index
sudo -u $USER arduino-cli core install esp32:esp32

# 権限設定
echo "権限を設定中..."
chown -R $USER:$USER $INSTALL_DIR
chmod +x $INSTALL_DIR/bin/orchestrator.py

# I2C有効化
echo "I2Cを有効化中..."
if ! grep -q "dtparam=i2c_arm=on" /boot/config.txt; then
    echo "dtparam=i2c_arm=on" >> /boot/config.txt
fi

# GPIO アクセス権限設定
echo "GPIO アクセス権限を設定中..."
usermod -a -G gpio $USER

# USB OTG設定（Pi Zero/Pi 4用）
echo "USB OTG設定を追加中..."
if ! grep -q "dtoverlay=dwc2" /boot/config.txt; then
    echo "dtoverlay=dwc2" >> /boot/config.txt
fi

if ! grep -q "dwc2" /etc/modules; then
    echo "dwc2" >> /etc/modules
fi

# libcomposite モジュール設定
if ! grep -q "libcomposite" /etc/modules; then
    echo "libcomposite" >> /etc/modules
fi

# systemd サービス作成
echo "systemd サービスを作成中..."
cat > /etc/systemd/system/${SERVICE_NAME}.service << EOF
[Unit]
Description=ESP32 Writer Orchestrator
After=local-fs.target network.target
Wants=local-fs.target

[Service]
Type=simple
User=$USER
Group=$USER
WorkingDirectory=$INSTALL_DIR
Environment=PYTHONPATH=$INSTALL_DIR
ExecStart=$INSTALL_DIR/venv/bin/python $INSTALL_DIR/bin/orchestrator.py
Restart=on-failure
RestartSec=5
StandardOutput=journal
StandardError=journal

[Install]
WantedBy=multi-user.target
EOF

# systemd サービス有効化
echo "systemd サービスを有効化中..."
systemctl daemon-reload
systemctl enable ${SERVICE_NAME}.service

# Mass Storage イメージ作成用のスクリプト
cat > $INSTALL_DIR/scripts/create_storage.sh << 'EOF'
#!/bin/bash
# Mass Storage イメージ作成スクリプト

STORAGE_FILE="/opt/esp32_writer/msd.img"
STORAGE_SIZE_MB=256

if [ ! -f "$STORAGE_FILE" ]; then
    echo "Mass Storage イメージを作成中..."
    dd if=/dev/zero of="$STORAGE_FILE" bs=1M count=$STORAGE_SIZE_MB
    mkfs.vfat "$STORAGE_FILE"
    echo "Mass Storage イメージが作成されました: $STORAGE_FILE"
else
    echo "Mass Storage イメージは既に存在します: $STORAGE_FILE"
fi
EOF

chmod +x $INSTALL_DIR/scripts/create_storage.sh
mkdir -p $INSTALL_DIR/scripts

# udev ルール作成（USB デバイス検出用）
echo "udev ルールを作成中..."
cat > /etc/udev/rules.d/99-esp32-writer.rules << 'EOF'
# ESP32 Writer USB デバイス検出ルール
SUBSYSTEM=="block", ACTION=="add", ENV{ID_FS_TYPE}=="vfat", RUN+="/bin/systemctl --no-block restart esp32-writer.service"
EOF

udevadm control --reload-rules

# ログローテーション設定
echo "ログローテーション設定を作成中..."
cat > /etc/logrotate.d/esp32-writer << EOF
$INSTALL_DIR/logs/*.log {
    daily
    missingok
    rotate 7
    compress
    delaycompress
    notifempty
    copytruncate
}
EOF

echo ""
echo "==================================="
echo "ESP32 Writer セットアップ完了！"
echo "==================================="
echo ""
echo "次の手順を実行してください："
echo "1. システムを再起動: sudo reboot"
echo "2. サービス状態確認: sudo systemctl status esp32-writer"
echo "3. ログ確認: sudo journalctl -u esp32-writer -f"
echo ""
echo "設定ファイル: $INSTALL_DIR/config/"
echo "ログファイル: $INSTALL_DIR/logs/"
echo ""
echo "注意: 再起動後にI2CとUSB OTGが有効になります。"