#!/bin/bash

# Renkli çıktı için ANSI kodları
GREEN='\033[0;325m'
BLUE='\033[0;34m'
RED='\033[0;31m'
NC='\033[0m' # Color Reset

echo -e "${BLUE}=== KryonImageWriter Otomatik Kurulum Aracı ===${NC}"

# 1. Gerekli sistem araçlarının kontrolü
for cmd in git python3 pip; do
    if ! command -v "$cmd" &> /dev/null; then
        echo -e "${RED}[!] Hata: '$cmd' komutu bulunamadı. Lütfen sisteminize yükleyin.${NC}"
        exit 1
    fi
done

INSTALL_DIR="$HOME/.local/share/KryonImageWriter"

# 2. Projeyi klonlama veya güncelleme
if [ -d "$INSTALL_DIR" ]; then
    echo -e "${BLUE}[*] Mevcut kurulum güncelleniyor...${NC}"
    cd "$INSTALL_DIR"
    git pull
else
    echo -e "${BLUE}[*] Proje GitHub'dan klonlanıyor...${NC}"
    git clone https://github.com/anileneserden/KryonImageWriter.git "$INSTALL_DIR"
    cd "$INSTALL_DIR"
fi

# 3. Sanal ortam oluşturma ve bağımlılıkları kurma
echo -e "${BLUE}[*] Python sanal ortamı hazırlanıyor ve paketler yükleniyor...${NC}"
python3 -m venv venv
source venv/bin/activate
pip install --upgrade pip
pip install PyQt6 pyinstaller

# 4. PyInstaller ile derleme
echo -e "${BLUE}[*] KryonImageWriter derleniyor...${NC}"
pyinstaller kryon_writer.spec

# 5. Çalıştırılabilir dosyayı /usr/local/bin altına bağlama (Root yetkisi ister)
echo -e "${BLUE}[*] Sistem yoluna (/usr/local/bin) ekleniyor...${NC}"
sudo ln -sf "$INSTALL_DIR/dist/KryonImageWriter" /usr/local/bin/KryonImageWriter

# 6. Başlat menüsü (.desktop) kısayolunu oluşturma
DESKTOP_DIR="$HOME/.local/share/applications"
mkdir -p "$DESKTOP_DIR"

cat << EOF > "$DESKTOP_DIR/kryon-image-writer.desktop"
[Desktop Entry]
Type=Application
Name=KryonImageWriter
Comment=Lightweight and modular OS image flashing tool
Exec=/usr/local/bin/KryonImageWriter
Icon=drive-removable-media
Categories=System;Utility;
Terminal=false
EOF

echo -e "${GREEN}[+] Kurulum başarıyla tamamlandı! KryonImageWriter artık başlat menünüzde ve terminalde hazır!${NC}"
