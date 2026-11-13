import sys
import os
import json
import subprocess
import tempfile
import shutil
from PyQt6.QtWidgets import (
    QApplication, QMainWindow, QWidget, QVBoxLayout, QHBoxLayout,
    QLabel, QPushButton, QComboBox, QFileDialog, QProgressBar, QMessageBox,
    QCheckBox, QTabWidget, QLineEdit, QGroupBox
)
from PyQt6.QtCore import Qt, QThread, pyqtSignal
from PyQt6.QtGui import QPalette, QColor


class FlashWorker(QThread):
    progress = pyqtSignal(int, str)
    finished = pyqtSignal(bool, str)

    def __init__(self, mode, device_path, params):
        super().__init__()
        self.mode = mode
        self.device_path = device_path
        self.params = params

    def run(self):
        try:
            if self.mode == "iso":
                self._flash_iso()
            elif self.mode == "custom":
                self._flash_lenoros_custom()
        except subprocess.CalledProcessError as e:
            err_msg = e.stderr if e.stderr else str(e)
            self.finished.emit(False, f"İşlem başarısız oldu:\n{err_msg}")
        except Exception as e:
            self.finished.emit(False, f"Beklenmeyen hata:\n{str(e)}")

    def _flash_iso(self):
        file_path = self.params["iso_path"]
        use_partitioning = self.params["use_partitioning"]

        self.progress.emit(15, "Bağlı bölümler ayrılıyor...")
        unmount_cmd = f"umount {self.device_path}* 2>/dev/null || true"
        subprocess.run(f"pkexec bash -c '{unmount_cmd}'", shell=True)

        if use_partitioning:
            self.progress.emit(35, "ISO yazılıyor ve veri bölümü oluşturuluyor...")
            script_commands = f"""
            set -e
            wipefs -a {self.device_path} >/dev/null 2>&1 || true
            dd if='{file_path}' of={self.device_path} bs=4M conv=fsync
            sync
            echo ",,0xc" | sfdisk --append {self.device_path} >/dev/null 2>&1 || true
            partprobe {self.device_path} || true
            sleep 2
            mkfs.vfat -F32 -n "LENOR_DATA" {self.device_path}2
            sync
            """
            subprocess.run(["pkexec", "bash", "-c", script_commands], check=True, text=True, capture_output=True)
        else:
            self.progress.emit(45, "İmaj diske yazılıyor...")
            dd_cmd = f"dd if='{file_path}' of={self.device_path} bs=4M conv=fsync && sync"
            subprocess.run(["pkexec", "bash", "-c", dd_cmd], check=True, text=True, capture_output=True)

        self.progress.emit(100, "Tamamlandı!")
        self.finished.emit(True, "Yazma işlemi başarıyla tamamlandı!")

    def _flash_lenoros_custom(self):
        bin_path = self.params["bin_path"]
        grub_cfg_path = self.params["grub_cfg_path"]
        sysroot_dir = self.params["sysroot_dir"]
        lfs_tool_path = self.params["lfs_tool_path"]
        boot_size_gb = self.params["boot_size_gb"]

        custom_cfg_content = ""
        if grub_cfg_path and os.path.exists(grub_cfg_path):
            with open(grub_cfg_path, "r", encoding="utf-8") as f:
                custom_cfg_content = f.read()

        self.progress.emit(10, "Disk temizleniyor ve bölümleniyor (MBR: FAT32 + LNRFS)...")

        script = f"""
        set -e
        umount {self.device_path}* 2>/dev/null || true
        wipefs -a {self.device_path} >/dev/null 2>&1 || true

        # 1. MBR Bölümleme: Part 1 -> {boot_size_gb}G FAT32 (Bootable), Part 2 -> Kalan alan (LNRFS)
        sfdisk {self.device_path} << EOF
label: dos
,{boot_size_gb}G,0x0c,*
,,0x83,
EOF
        partprobe {self.device_path} || true
        sleep 2

        # 2. sda1 Formatla (FAT32)
        mkfs.vfat -F32 -n "LENOR_BOOT" {self.device_path}1
        sync
        sleep 1

        # UUID Al
        BOOT_UUID=$(blkid -s UUID -o value {self.device_path}1)

        # 3. sda1 Mount ve GRUB Kurulumu
        TMP_BOOT=$(mktemp -d /tmp/lenor_boot.XXXXXX)

        cleanup() {{
            umount "$TMP_BOOT" 2>/dev/null || true
            rmdir "$TMP_BOOT" 2>/dev/null || true
        }}
        trap cleanup EXIT

        mount {self.device_path}1 "$TMP_BOOT"
        mkdir -p "$TMP_BOOT/boot/grub"

        grub-install --target=i386-pc --boot-directory="$TMP_BOOT/boot" {self.device_path}
        grub-install --target=x86_64-efi --efi-directory="$TMP_BOOT" --boot-directory="$TMP_BOOT/boot" --removable {self.device_path}

        cp '{bin_path}' "$TMP_BOOT/boot/lenoros.bin"
        """

        if custom_cfg_content:
            script += f"""
            cat << 'GRUBEOF' > "$TMP_BOOT/boot/grub/grub.cfg"
{custom_cfg_content}
GRUBEOF
            sed -i "s/YOUR_UUID/$BOOT_UUID/g" "$TMP_BOOT/boot/grub/grub.cfg"
            """
        else:
            script += """
            cat << GRUBEOF > "$TMP_BOOT/boot/grub/grub.cfg"
set timeout=3
insmod all_video
insmod fat

menuentry "LenorOS UEFI/BIOS" {
    search --no-floppy --fs-uuid --set=root $BOOT_UUID
    multiboot /boot/lenoros.bin
    boot
}
GRUBEOF
            """

        script += """
        sync
        umount "$TMP_BOOT"
        """

        self.progress.emit(40, "GRUB kuruluyor ve sda2 LNRFS formatlanıyor...")
        
        # Önce pkexec ile disk bölümleri ve GRUB kurulumunu bitirelim
        subprocess.run(["pkexec", "bash", "-c", script], check=True, text=True, capture_output=True)

        # 4. sda2 bölümünü senin verdiğin format komutu ile biçimlendir
        if lfs_tool_path and os.path.exists(lfs_tool_path):
            self.progress.emit(70, "LNRFS dosya sistemi biçimlendiriliyor ve dosyalar aktarılıyor...")
            
            # Format komutu
            format_cmd = ["pkexec", lfs_tool_path, f"{self.device_path}2", "--format"]
            subprocess.run(format_cmd, check=True)

            # Eğer kullanıcı C:\ içine kopyalanacak bir sysroot klasörü seçtiyse, lfs aracı üzerinden mount edip kopyalayabiliriz
            # (Alternatif olarak lfs mount komutu varsa buraya eklenebilir)
            if sysroot_dir and os.path.exists(sysroot_dir):
                tmp_lnrfs = tempfile.mkdtemp(prefix="lenor_lnrfs_")
                try:
                    # Mount komutu (Eğer lfs -m /dev/sda2 /tmp/... şeklinde çalışıyorsa)
                    subprocess.run(["pkexec", lfs_tool_path, "-m", f"{self.device_path}2", tmp_lnrfs], check=True)
                    
                    # Dosyaları kopyala (terminal.lex, Desktop klasörü vb.)
                    copy_script = f"cp -r '{sysroot_dir}/.' '{tmp_lnrfs}/' && sync"
                    subprocess.run(["pkexec", "bash", "-c", copy_script], check=True)
                    
                    # Unmount et
                    subprocess.run(["pkexec", "umount", tmp_lnrfs], check=True)
                finally:
                    if os.path.exists(tmp_lnrfs):
                        os.rmdir(tmp_lnrfs)

        self.progress.emit(100, "LenorOS USB başarıyla hazırlandı!")
        self.finished.emit(True, "LenorOS Boot (FAT32) ve C:\\ (LNRFS) bölümleri başarıyla oluşturuldu ve dosyalar yazıldı!")


class LenorImageWriter(QMainWindow):
    def __init__(self):
        super().__init__()
        self.current_lang = "tr"
        self.translations = {}
        self.load_languages()
        self.initUI()
        self.load_drives()

    def load_languages(self):
        def resource_path(relative_path):
            try:
                base_path = sys._MEIPASS
            except Exception:
                base_path = os.path.abspath(".")
            return os.path.join(base_path, relative_path)

        lang_dir = resource_path("lang")

        self.translations["en"] = {
            "window_title": "LenorImageWriter",
            "step1": "1. Select Image File (.iso / .img):",
            "no_file": "No file selected...",
            "browse": "Browse",
            "step2": "2. Select Target Removable Drive:",
            "refresh": "Refresh",
            "no_drives": "No removable drives found",
            "start_flash": "Write Image to USB",
            "confirm_title": "Confirm Write",
            "confirm_msg": "All data on /dev/{device} will be ERASED! Are you sure?",
            "error_title": "Error",
            "select_file_warning": "Please select a valid file first.",
            "select_drive_warning": "Please select a valid target USB drive.",
            "success_title": "Success",
            "success_msg": "Operation completed successfully!"
        }

        self.translations["tr"] = {
            "window_title": "LenorImageWriter",
            "step1": "1. İmaj Dosyası Seçin (.iso / .img):",
            "no_file": "Seçilen dosya yok...",
            "browse": "Gözat",
            "step2": "2. Hedef Çıkarılabilir Sürücüyü Seçin:",
            "refresh": "Yenile",
            "no_drives": "Çıkarılabilir sürücü bulunamadı",
            "start_flash": "USB Belleğe Yazdır",
            "confirm_title": "Yazdırmayı Onayla",
            "confirm_msg": "/dev/{device} üzerindeki TÜM VERİLER SİLİNECEK! Emin misiniz?",
            "error_title": "Hata",
            "select_file_warning": "Lütfen önce geçerli bir dosya seçin.",
            "select_drive_warning": "Lütfen geçerli bir USB sürücü seçin.",
            "success_title": "Başarılı",
            "success_msg": "İşlem başarıyla tamamlandı!"
        }

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
        lang_dict = self.translations.get(self.current_lang, self.translations.get("en", {}))
        return lang_dict.get(key, key)

    def initUI(self):
        self.setWindowTitle(self.tr_text("window_title"))
        self.setFixedSize(600, 620)

        central_widget = QWidget(self)
        self.setCentralWidget(central_widget)
        main_layout = QVBoxLayout()
        main_layout.setContentsMargins(20, 20, 20, 20)
        main_layout.setSpacing(12)

        # Üst Kısım: Başlık ve Dil Seçici
        top_layout = QHBoxLayout()
        self.title_label = QLabel("LenorImageWriter", self)
        self.title_label.setStyleSheet("font-size: 20px; font-weight: bold; color: #3daee9;")

        self.lang_combo = QComboBox(self)
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

        # Ortak Hedef Sürücü Seçimi
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

        # Sekme Yapısı (Standart ISO vs LenorOS Custom Dev)
        self.tabs = QTabWidget(self)
        self.tabs.addTab(self._create_iso_tab(), "Standard ISO / IMG")
        self.tabs.addTab(self._create_custom_tab(), "LenorOS Custom (Dev)")
        main_layout.addWidget(self.tabs)

        # Durum Etiketi & İlerleme Çubuğu
        self.status_label = QLabel("Hazır", self)
        self.status_label.setStyleSheet("color: #bdc3c7; font-size: 12px;")
        main_layout.addWidget(self.status_label)

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
            QPushButton:disabled {
                background-color: #555555;
                color: #888888;
            }
        """)
        self.flash_btn.clicked.connect(self.start_flashing)
        main_layout.addWidget(self.flash_btn)

        central_widget.setLayout(main_layout)

    def _create_iso_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(15)

        self.step1_label = QLabel(self.tr_text("step1"), self)
        file_box_layout = QHBoxLayout()
        self.file_input_path = QLabel(self.tr_text("no_file"), self)
        self.file_input_path.setStyleSheet("color: #7f8c8d; background-color: #2a2e32; padding: 6px; border-radius: 4px;")

        self.select_file_btn = QPushButton(self.tr_text("browse"), self)
        self.select_file_btn.setFixedWidth(90)
        self.select_file_btn.clicked.connect(self.select_image_file)

        file_box_layout.addWidget(self.file_input_path, 1)
        file_box_layout.addWidget(self.select_file_btn)

        layout.addWidget(self.step1_label)
        layout.addLayout(file_box_layout)

        self.partition_checkbox = QCheckBox("Kalan alanı FAT32 veri bölümü olarak biçimlendir", self)
        self.partition_checkbox.setChecked(True)
        layout.addWidget(self.partition_checkbox)
        layout.addStretch()
        return tab

    def _create_custom_tab(self):
        tab = QWidget()
        layout = QVBoxLayout(tab)
        layout.setSpacing(10)

        # 1. lenoros.bin seçimi
        layout.addWidget(QLabel("Kernel Binary (lenoros.bin) [Zorunlu]:"))
        bin_row = QHBoxLayout()
        self.bin_path_edit = QLineEdit()
        self.bin_path_edit.setPlaceholderText("/home/anil/LenorOS/.../lenoros.bin")
        btn_bin = QPushButton("Gözat")
        btn_bin.setFixedWidth(80)
        btn_bin.clicked.connect(lambda: self._browse_file(self.bin_path_edit, "Binary Files (*.bin *.elf);;All Files (*)"))
        bin_row.addWidget(self.bin_path_edit)
        bin_row.addWidget(btn_bin)
        layout.addLayout(bin_row)

        # 2. grub.cfg seçimi (Opsiyonel)
        layout.addWidget(QLabel("GRUB Config (grub.cfg) [Boş bırakılırsa otomatik UUID'li üretilir]:"))
        cfg_row = QHBoxLayout()
        self.cfg_path_edit = QLineEdit()
        self.cfg_path_edit.setPlaceholderText("Opsiyonel - YOUR_UUID içeriyorsa otomatik güncellenir")
        btn_cfg = QPushButton("Gözat")
        btn_cfg.setFixedWidth(80)
        btn_cfg.clicked.connect(lambda: self._browse_file(self.cfg_path_edit, "GRUB Config (*.cfg);;All Files (*)"))
        cfg_row.addWidget(self.cfg_path_edit)
        cfg_row.addWidget(btn_cfg)
        layout.addLayout(cfg_row)

        # 3. lfs aracı yolu
        layout.addWidget(QLabel("LNRFS Userspace Aracı (lfs binary):"))
        lfs_row = QHBoxLayout()
        self.lfs_path_edit = QLineEdit()
        self.lfs_path_edit.setPlaceholderText("/home/anil/LenorOS/.../build/lfs")
        btn_lfs = QPushButton("Gözat")
        btn_lfs.setFixedWidth(80)
        btn_lfs.clicked.connect(lambda: self._browse_file(self.lfs_path_edit, "All Files (*)"))
        lfs_row.addWidget(self.lfs_path_edit)
        lfs_row.addWidget(btn_lfs)
        layout.addLayout(lfs_row)

        # 4. C:\ Kök dizin kaynak klasörü (Sysroot)
        layout.addWidget(QLabel("C:\\ (LNRFS) İçine Kopyalanacak Kaynak Klasör:"))
        sysroot_row = QHBoxLayout()
        self.sysroot_edit = QLineEdit()
        self.sysroot_edit.setPlaceholderText("Örn: Lenor/System32/terminal.lex ve Users/usbuser/Desktop içeren klasör")
        btn_sysroot = QPushButton("Klasör Seç")
        btn_sysroot.setFixedWidth(80)
        btn_sysroot.clicked.connect(self._browse_folder)
        sysroot_row.addWidget(self.sysroot_edit)
        sysroot_row.addWidget(btn_sysroot)
        layout.addLayout(sysroot_row)

        # 5. Boot Bölümü Boyutu
        size_row = QHBoxLayout()
        size_row.addWidget(QLabel("Boot Bölümü (FAT32) Boyutu (GB):"))
        self.boot_size_combo = QComboBox()
        self.boot_size_combo.addItems(["1", "2", "4", "8", "16", "25"])
        self.boot_size_combo.setCurrentText("4")
        size_row.addWidget(self.boot_size_combo)
        size_row.addStretch()
        layout.addLayout(size_row)

        return tab

    def _browse_file(self, line_edit, file_filter):
        path, _ = QFileDialog.getOpenFileName(self, "Dosya Seç", "/home/anil/LenorOS", file_filter)
        if path:
            line_edit.setText(path)

    def _browse_folder(self):
        folder = QFileDialog.getExistingDirectory(self, "C:\\ Kök Klasörünü Seç", "/home/anil/LenorOS")
        if folder:
            self.sysroot_edit.setText(folder)

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
            cmd = "lsblk -d -o NAME,SIZE,RM,MODEL | grep ' 1 '"
            output = subprocess.check_output(cmd, shell=True, text=True).strip()
            if not output:
                self.drive_combo.addItem(self.tr_text("no_drives"))
                return
            for line in output.split('\n'):
                self.drive_combo.addItem(line.strip())
        except Exception:
            self.drive_combo.addItem("Error scanning drives")

    def start_flashing(self):
        target_item = self.drive_combo.currentText()
        if "bulunamadı" in target_item or "No removable" in target_item or not target_item or "Error" in target_item:
            QMessageBox.warning(self, self.tr_text("error_title"), self.tr_text("select_drive_warning"))
            return

        target_device = target_item.split()[0]
        device_path = f"/dev/{target_device}"
        current_tab = self.tabs.currentIndex()

        if current_tab == 0:
            # Standart ISO Modu
            file_path = self.file_input_path.text()
            if "No file" in file_path or "Seçilen dosya" in file_path or not os.path.exists(file_path):
                QMessageBox.warning(self, self.tr_text("error_title"), self.tr_text("select_file_warning"))
                return
            mode = "iso"
            params = {
                "iso_path": file_path,
                "use_partitioning": self.partition_checkbox.isChecked()
            }
        else:
            # LenorOS Custom Modu
            bin_path = self.bin_path_edit.text().strip()
            if not bin_path or not os.path.exists(bin_path):
                QMessageBox.warning(self, self.tr_text("error_title"), "Lütfen geçerli bir lenoros.bin dosyası seçin.")
                return
            mode = "custom"
            params = {
                "bin_path": bin_path,
                "grub_cfg_path": self.cfg_path_edit.text().strip(),
                "lfs_tool_path": self.lfs_path_edit.text().strip(),
                "sysroot_dir": self.sysroot_edit.text().strip(),
                "boot_size_gb": self.boot_size_combo.currentText()
            }

        msg = self.tr_text("confirm_msg").format(device=target_device)
        reply = QMessageBox.question(
            self, self.tr_text("confirm_title"), msg,
            QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No,
            QMessageBox.StandardButton.No
        )

        if reply == QMessageBox.StandardButton.Yes:
            self.flash_btn.setEnabled(False)
            self.progress_bar.setValue(0)
            self.worker = FlashWorker(mode, device_path, params)
            self.worker.progress.connect(self.on_progress)
            self.worker.finished.connect(self.on_finished)
            self.worker.start()

    def on_progress(self, val, text):
        self.progress_bar.setValue(val)
        self.status_label.setText(text)

    def on_finished(self, success, message):
        self.flash_btn.setEnabled(True)
        if success:
            QMessageBox.information(self, self.tr_text("success_title"), message)
            self.progress_bar.setValue(0)
            self.status_label.setText("Hazır")
        else:
            QMessageBox.critical(self, self.tr_text("error_title"), message)
            self.progress_bar.setValue(0)
            self.status_label.setText("Hata oluştu.")


if __name__ == '__main__':
    app = QApplication(sys.argv)
    app.setStyle("Fusion")
    dark_palette = QPalette()
    dark_palette.setColor(QPalette.ColorRole.Window, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.WindowText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Base, QColor(35, 35, 35))
    dark_palette.setColor(QPalette.ColorRole.AlternateBase, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ToolTipBase, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.ToolTipText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Text, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.Button, QColor(53, 53, 53))
    dark_palette.setColor(QPalette.ColorRole.ButtonText, Qt.GlobalColor.white)
    dark_palette.setColor(QPalette.ColorRole.BrightText, Qt.GlobalColor.red)
    dark_palette.setColor(QPalette.ColorRole.Link, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.Highlight, QColor(42, 130, 218))
    dark_palette.setColor(QPalette.ColorRole.HighlightedText, Qt.GlobalColor.black)
    app.setPalette(dark_palette)

    window = LenorImageWriter()
    window.show()
    sys.exit(app.exec())