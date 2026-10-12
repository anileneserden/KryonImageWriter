import sys
import os
import json
import subprocess
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFileDialog, QProgressBar, QMessageBox
)
from PyQt6.QtCore import Qt

class KryonImageWriter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = "en"  # Varsayılan dil İngilizce
        self.translations = {}
        self.load_languages()
        
        self.initUI()
        self.load_drives()

    def load_languages(self):
        # PyInstaller ile derlendiğinde geçici klasör yolunu bulur, normalde yerel dizini alır
        def resource_path(relative_path):
            try:
                base_path = sys._MEIPASS
            except Exception:
                base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)

        lang_dir = resource_path("lang")
        
        # Varsayılan İngilizce sözlük (yedek)
        self.translations["en"] = { ... } # (Önceki sözlük verileri)
        
        if os.path.exists(lang_dir):
            for filename in os.listdir(lang_dir):
                if filename.endswith(".json"):
                    lang_code = filename.split(".")[0]
                    try:
                        with open(os.path.join(lang_dir, filename), "r", encoding="utf-8") as f:
                            self.translations[lang_code] = json.load(f)
                    except Exception as e:
                        print(f"Dil dosyası okunamadı ({filename}): {e}")

    def tr_text(self, key):
        # Seçilen dilde anahtar yoksa İngilizceye düş
        lang_dict = self.translations.get(self.current_lang, self.translations.get("en", {}))
        return lang_dict.get(key, key)

    def initUI(self):
        self.setWindowTitle(self.tr_text("window_title"))
        self.setFixedSize(540, 440)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(15)

        # Üst Kısım: Başlık ve Sağ Üstte Dil Seçici
        top_layout = QHBoxLayout()
        
        self.title_label = QLabel("KryonImageWriter", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #3daee9;")
        
        self.lang_combo = QComboBox(self)
        # Mevcut dilleri combobox'a ekle
        for code in self.translations.keys():
            self.lang_combo.addItem(code.upper(), code)
        self.lang_combo.setCurrentText(self.current_lang.upper())
        self.lang_combo.setFixedWidth(80)
        self.lang_combo.currentIndexChanged.connect(self.change_language)

        top_layout.addWidget(self.title_label)
        top_layout.addStretch()
        top_layout.addWidget(QLabel("Lang:"))
        top_layout.addWidget(self.lang_combo)
        main_layout.addLayout(top_layout)

        # 1. Adım: İmaj Seçimi
        self.step1_label = QLabel(self.tr_text("step1"), self)
        file_box_layout = QHBoxLayout()
        self.file_input_path = QLabel(self.tr_text("no_file"), self)
        self.file_input_path.setStyleSheet("color: #7f8c8d; background-color: #2a2e32; padding: 6px; border-radius: 4px;")
        
        self.select_file_btn = QPushButton(self.tr_text("browse"), self)
        self.select_file_btn.setFixedWidth(90)
        self.select_file_btn.clicked.connect(self.select_image_file)
        
        file_box_layout.addWidget(self.file_input_path, 1)
        file_box_layout.addWidget(self.select_file_btn)
        
        main_layout.addWidget(self.step1_label)
        main_layout.addLayout(file_box_layout)

        # 2. Adım: Hedef Sürücü Seçimi
        self.step2_label = QLabel(self.tr_text("step2"), self)
        self.drive_combo = QComboBox(self)
        self.drive_combo.setStyleSheet("padding: 6px;")
        
        self.refresh_drives_btn = QPushButton(self.tr_text("refresh"), self)
        self.refresh_drives_btn.setFixedWidth(90)
        self.refresh_drives_btn.clicked.connect(self.load_drives)
        
        drive_box_layout = QHBoxLayout()
        drive_box_layout.addWidget(self.drive_combo, 1)
        drive_box_layout.addWidget(self.refresh_drives_btn)

        main_layout.addWidget(self.step2_label)
        main_layout.addLayout(drive_box_layout)

        # İlerleme Çubuğu
        self.progress_bar = QProgressBar(self)
        self.progress_bar.setValue(0)
        self.progress_bar.setTextVisible(True)
        main_layout.addWidget(self.progress_bar)

        # Yazma Butonu
        self.flash_btn = QPushButton(self.tr_text("start_flash"), self)
        self.flash_btn.setStyleSheet("""
            QPushButton {
                background-color: #3daee9;
                color: #ffffff;
                font-weight: bold;
                font-size: 14px;
                padding: 10px;
                border-radius: 5px;
            }
            QPushButton:hover {
                background-color: #2980b9;
            }
        """)
        self.flash_btn.clicked.connect(self.start_flashing)
        main_layout.addWidget(self.flash_btn)

        central_widget.setLayout(main_layout)

    def change_language(self):
        selected_code = self.lang_combo.currentData()
        if selected_code:
            self.current_lang = selected_code
            self.update_ui_texts()

    def update_ui_texts(self):
        self.setWindowTitle(self.tr_text("window_title"))
        self.step1_label.setText(self.tr_text("step1"))
        if "No file" in self.file_input_path.text() or "Seçilen dosya" in self.file_input_path.text():
            self.file_input_path.setText(self.tr_text("no_file"))
        self.select_file_btn.setText(self.tr_text("browse"))
        self.step2_label.setText(self.tr_text("step2"))
        self.refresh_drives_btn.setText(self.tr_text("refresh"))
        self.flash_btn.setText(self.tr_text("start_flash"))

    def select_image_file(self):
        file_path, _ = QFileDialog.getOpenFileName(
            self, "Select Image File", "", "Image Files (*.iso *.img);;All Files (*.*)"
        )
        if file_path:
            self.file_input_path.setText(file_path)
            self.file_input_path.setStyleSheet("color: #2ecc71; background-color: #2a2e32; padding: 6px; border-radius: 4px;")

    def load_drives(self):
        self.drive_combo.clear()
        try:
            # Sadece çıkarılabilir (RM=1) diskleri filtrele
            cmd = "lsblk -d -o NAME,SIZE,RM,MODEL | grep ' 1 '"
            output = subprocess.check_output(cmd, shell=True, text=True).strip()
            
            if not output:
                self.drive_combo.addItem(self.tr_text("no_drives"))
                return

            for line in output.split('\n'):
                self.drive_combo.addItem(line.strip())
        except Exception as e:
            self.drive_combo.addItem("Error scanning drives")

    def start_flashing(self):
        file_path = self.file_input_path.text()
        target_item = self.drive_combo.currentText()

        if "No file" in file_path or "Seçilen dosya" in file_path or not os.path.exists(file_path):
            QMessageBox.warning(self, self.tr_text("error_title"), self.tr_text("select_file_warning"))
            return
        
        if "bulunamadı" in target_item or "No removable" in target_item or not target_item:
            QMessageBox.warning(self, self.tr_text("error_title"), self.tr_text("select_drive_warning"))
            return

        # Sürücü adını ayıkla (Örn: "sdb   14.9G   1   SanDisk Cruzer" -> "sdb")
        target_device = target_item.split()[0]
        device_path = f"/dev/{target_device}"

        msg = self.tr_text("confirm_msg").format(device=target_device)
        reply = QMessageBox.question(
            self, self.tr_text("confirm_title"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            # pkexec ile root yetkisi alarak dd komutunu çalıştır
            # sync komutu verinin tamamen diske yazılmasını garantiler
            dd_cmd = f"pkexec dd if='{file_path}' of={device_path} bs=4M status=progress conv=fsync"
            
            try:
                self.progress_bar.setValue(50) # İşlem başlangıç göstergesi
                process = subprocess.run(dd_cmd, shell=True, check=True)
                self.progress_bar.setValue(100)
                QMessageBox.information(self, self.tr_text("success_title"), self.tr_text("success_msg"))
                self.progress_bar.setValue(0)
            except subprocess.CalledProcessError as e:
                self.progress_bar.setValue(0)
                QMessageBox.critical(self, self.tr_text("error_title"), f"Flashing failed: {e}")

if __name__ == '__main__':
    app = QApplication(sys.argv)
    window = KryonImageWriter()
    window.show()
    sys.exit(app.exec())