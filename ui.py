"""Landing Judge Desktop UI (PySide6)

- Edit `.env` configuration: port, AWS region, voice, format, TTS.
- Open the browser overlay and trigger votes 1–10.
- Optional: load voices from AWS Polly.

This UI complements the Flask app in `all_in_one.py` and provides a
simple control panel for local streaming setups.
"""
import sys
import webbrowser
from pathlib import Path

import requests
import boto3
from PySide6.QtCore import Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices
from PySide6.QtWidgets import (
    QApplication,
    QCheckBox,
    QComboBox,
    QFormLayout,
    QGridLayout,
    QGroupBox,
    QHBoxLayout,
    QLabel,
    QLineEdit,
    QMainWindow,
    QPushButton,
    QSpinBox,
    QVBoxLayout,
    QWidget,
)
from dotenv import dotenv_values, set_key


ENV_PATH = Path(".env")


def load_env():
    return dotenv_values(str(ENV_PATH))


def save_env_var(key: str, value: str):
    set_key(str(ENV_PATH), key, value)


class VotingUI(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("Landing Judge - Control Panel")
        self.env = load_env()

        # Defaults
        self.default_port = int(self.env.get("PORT", "5005") or 5005)
        self.default_region = self.env.get("AWS_REGION", "us-east-1")
        self.default_voice = self.env.get("POLLY_VOICE_ID", "Joanna")
        self.default_format = self.env.get("POLLY_OUTPUT_FORMAT", "mp3")
        self.default_tts = (self.env.get("ENABLE_TTS", "true").strip().lower() in {"1", "true", "yes", "on"})

        self._build_ui()

    def _build_ui(self):
        central = QWidget()
        self.setCentralWidget(central)

        root = QVBoxLayout()
        central.setLayout(root)

        # Settings group
        settings_group = QGroupBox("Settings (.env)")
        settings_layout = QFormLayout()
        settings_group.setLayout(settings_layout)

        # PORT
        self.port_spin = QSpinBox()
        self.port_spin.setRange(1024, 65535)
        self.port_spin.setValue(self.default_port)
        try:
            self.port_spin.setToolTip("Port for internal server and overlay. Restart required after change.")
        except Exception:
            pass
        settings_layout.addRow("Port", self.port_spin)

        # Timing controls removed (Banner Duration, Audio-end grace)

        # Region
        self.region_combo = QComboBox()
        regions = [
            "us-east-1",
            "us-east-2",
            "us-west-1",
            "us-west-2",
            "eu-west-1",
            "eu-central-1",
            "ap-south-1",
            "ap-southeast-1",
            "ap-southeast-2",
        ]
        self.region_combo.addItems(regions)
        idx = self.region_combo.findText(self.default_region)
        self.region_combo.setCurrentIndex(max(0, idx))
        try:
            self.region_combo.setToolTip("AWS region used for Amazon Polly Text-to-Speech.")
        except Exception:
            pass
        settings_layout.addRow("AWS Region", self.region_combo)

        # Voice + dynamic loader
        self.voice_combo = QComboBox()
        default_voices = [
            "Joanna", "Matthew", "Amy", "Brian", "Ivy", "Kendra",
            "Kimberly", "Salli", "Joey", "Justin", "Emma", "Nicole",
        ]
        self.voice_combo.addItems(default_voices)
        idx = self.voice_combo.findText(self.default_voice)
        self.voice_combo.setCurrentIndex(max(0, idx))
        self.load_voices_btn = QPushButton("Load Voices from AWS")
        try:
            self.voice_combo.setToolTip("Select the Amazon Polly voice used for TTS.")
            self.load_voices_btn.setToolTip("Fetch voices from AWS Polly and populate the list.")
        except Exception:
            pass
        voice_row = QHBoxLayout()
        voice_row.addWidget(self.voice_combo)
        voice_row.addWidget(self.load_voices_btn)
        settings_layout.addRow("Polly Voice", voice_row)

        # Output format
        self.format_combo = QComboBox()
        self.format_combo.addItems(["mp3", "wav"])
        idx = self.format_combo.findText(self.default_format)
        self.format_combo.setCurrentIndex(max(0, idx))
        try:
            self.format_combo.setToolTip("Audio output format for TTS clips.")
        except Exception:
            pass
        settings_layout.addRow("Audio Format", self.format_combo)

        # TTS enable
        self.tts_check = QCheckBox("Enable Text-to-Speech (Polly)")
        self.tts_check.setChecked(self.default_tts)
        try:
            self.tts_check.setToolTip("Enable spoken messages using Amazon Polly.")
        except Exception:
            pass
        settings_layout.addRow(self.tts_check)

        # AWS credentials
        self.key_id = QLineEdit(self.env.get("AWS_ACCESS_KEY_ID", ""))
        self.secret_key = QLineEdit(self.env.get("AWS_SECRET_ACCESS_KEY", ""))
        self.secret_key.setEchoMode(QLineEdit.Password)
        try:
            self.key_id.setToolTip("AWS Access Key ID used for Polly TTS.")
            self.secret_key.setToolTip("AWS Secret Access Key (stored in .env).")
        except Exception:
            pass
        settings_layout.addRow("AWS Access Key ID", self.key_id)
        settings_layout.addRow("AWS Secret Access Key", self.secret_key)

        # Save / overlay / status
        btn_row = QHBoxLayout()
        self.save_btn = QPushButton("Reset Defaults")
        self.open_overlay_btn = QPushButton("Open Overlay")
        try:
            self.save_btn.setToolTip("Restore default settings and persist to .env.")
            self.open_overlay_btn.setToolTip("Open the browser overlay page.")
        except Exception:
            pass
        btn_row.addWidget(self.save_btn)
        btn_row.addWidget(self.open_overlay_btn)
        settings_layout.addRow(btn_row)

        self.status_label = QLabel("")
        self.status_label.setWordWrap(True)
        try:
            self.status_label.setToolTip("Status and feedback messages.")
        except Exception:
            pass
        settings_layout.addRow(self.status_label)

        # Voting group
        vote_group = QGroupBox("Trigger Votes")
        vote_layout = QGridLayout()
        vote_group.setLayout(vote_layout)

        self.vote_buttons = []
        for i in range(1, 11):
            btn = QPushButton(str(i))
            try:
                btn.setToolTip(f"Trigger vote score {i}.")
            except Exception:
                pass
            btn.clicked.connect(lambda _=False, score=i: self.trigger_vote(score))
            self.vote_buttons.append(btn)
        # Arrange in grid 5 x 2
        for idx, btn in enumerate(self.vote_buttons):
            row = idx // 5
            col = idx % 5
            vote_layout.addWidget(btn, row, col)

        root.addWidget(settings_group)
        root.addWidget(vote_group)

        # Wire actions
        self.save_btn.clicked.connect(self.reset_defaults)
        self.open_overlay_btn.clicked.connect(self.open_overlay)
        self.load_voices_btn.clicked.connect(self.load_voices_from_aws)

        # Debounced auto-save for settings changes to avoid frequent disk writes
        try:
            self._autosave_timer = QTimer(self)
            self._autosave_timer.setInterval(750)
            self._autosave_timer.setSingleShot(True)
            self._autosave_timer.timeout.connect(self._autosave_settings)

            # Wire inputs to queue autosave
            self.port_spin.valueChanged.connect(self._queue_autosave)
            # Timing controls removed
            self.region_combo.currentIndexChanged.connect(self._queue_autosave)
            self.voice_combo.currentIndexChanged.connect(self._queue_autosave)
            self.format_combo.currentIndexChanged.connect(self._queue_autosave)
            self.tts_check.toggled.connect(self._queue_autosave)
            # Credentials: save when editing finished
            self.key_id.editingFinished.connect(self._queue_autosave)
            self.secret_key.editingFinished.connect(self._queue_autosave)
            # Also autosave on text changes with debounce, so focus loss is not required
            self.key_id.textChanged.connect(self._queue_autosave)
            self.secret_key.textChanged.connect(self._queue_autosave)
        except Exception:
            pass

    def base_url(self):
        return f"http://127.0.0.1:{self.port_spin.value()}"

    def save_settings(self):
        try:
            save_env_var("PORT", str(self.port_spin.value()))
            # Timing controls removed from persistence
            save_env_var("AWS_REGION", self.region_combo.currentText())
            save_env_var("POLLY_VOICE_ID", self.voice_combo.currentText())
            save_env_var("POLLY_OUTPUT_FORMAT", self.format_combo.currentText())
            save_env_var("ENABLE_TTS", "true" if self.tts_check.isChecked() else "false")
            save_env_var("AWS_ACCESS_KEY_ID", self.key_id.text().strip())
            save_env_var("AWS_SECRET_ACCESS_KEY", self.secret_key.text().strip())
            self.status_label.setText("Settings saved to .env. Restart the server to apply.")
        except Exception as e:
            self.status_label.setText(f"Error saving settings: {e}")

    def reset_defaults(self):
        """Reset UI controls and environment to opinionated defaults.
        Defaults:
        - Port: 5005
        - Banner duration: 8000 ms
        - AWS region: us-east-1
        - Voice: Joanna
        - Format: mp3
        - TTS: enabled
        - AWS keys: empty
        """
        try:
            # Update UI controls
            try:
                self.port_spin.setValue(5005)
            except Exception:
                pass
            # Timing controls removed from UI defaults
            try:
                idx = self.region_combo.findText("us-east-1")
                self.region_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                idx = self.voice_combo.findText("Joanna")
                self.voice_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                idx = self.format_combo.findText("mp3")
                self.format_combo.setCurrentIndex(max(0, idx))
            except Exception:
                pass
            try:
                self.tts_check.setChecked(True)
            except Exception:
                pass
            try:
                self.key_id.setText("")
                self.secret_key.setText("")
            except Exception:
                pass

            # Persist to .env
            try:
                save_env_var("PORT", "5005")
                # Timing controls removed from .env defaults
                save_env_var("AWS_REGION", "us-east-1")
                save_env_var("POLLY_VOICE_ID", "Joanna")
                save_env_var("POLLY_OUTPUT_FORMAT", "mp3")
                save_env_var("ENABLE_TTS", "true")
                save_env_var("AWS_ACCESS_KEY_ID", "")
                save_env_var("AWS_SECRET_ACCESS_KEY", "")
            except Exception:
                pass

            try:
                self.status_label.setText("Defaults restored. Some changes (like Port) require restart.")
            except Exception:
                pass
        except Exception as e:
            try:
                self.status_label.setText(f"Error resetting defaults: {e}")
            except Exception:
                pass

    def _queue_autosave(self):
        try:
            self._autosave_timer.stop()
            self._autosave_timer.start()
        except Exception:
            pass

    def _autosave_settings(self):
        try:
            save_env_var("PORT", str(self.port_spin.value()))
            # Timing controls removed from autosave
            save_env_var("AWS_REGION", self.region_combo.currentText())
            save_env_var("POLLY_VOICE_ID", self.voice_combo.currentText())
            save_env_var("POLLY_OUTPUT_FORMAT", self.format_combo.currentText())
            save_env_var("ENABLE_TTS", "true" if self.tts_check.isChecked() else "false")
            save_env_var("AWS_ACCESS_KEY_ID", self.key_id.text().strip())
            save_env_var("AWS_SECRET_ACCESS_KEY", self.secret_key.text().strip())
            self.status_label.setText("Settings auto-saved.")
        except Exception:
            self.status_label.setText("Auto-save failed.")

    def open_overlay(self):
        url = f"{self.base_url()}/overlay"
        try:
            # Prefer OS handler via Qt; more reliable than webbrowser on Windows
            opened = QDesktopServices.openUrl(QUrl(url))
            if not opened:
                # Fallback to Python's webbrowser
                webbrowser.open(url)
            try:
                self.status_label.setText(f"Opened overlay: {url}")
            except Exception:
                pass
        except Exception:
            try:
                self.status_label.setText("Could not open overlay. Copy URL into your browser: " + url)
            except Exception:
                pass

    def trigger_vote(self, score: int):
        url = f"{self.base_url()}/vote/{score}"
        try:
            resp = requests.get(url, timeout=5)
            if resp.status_code == 200:
                self.status_label.setText(f"Sent vote {score}. Overlay should update.")
            else:
                self.status_label.setText(f"Vote failed ({resp.status_code}). Is server running?")
        except Exception as e:
            self.status_label.setText(f"Vote error: {e}")

    def load_voices_from_aws(self):
        # Use current UI values (not just .env) so users can try creds before saving
        key_id = self.key_id.text().strip()
        secret = self.secret_key.text().strip()
        region = self.region_combo.currentText().strip()

        if not key_id or not secret:
            self.status_label.setText("Enter AWS credentials to load voices.")
            return

        try:
            polly = boto3.client(
                'polly',
                aws_access_key_id=key_id,
                aws_secret_access_key=secret,
                region_name=region,
            )
            voices = []
            next_token = None
            while True:
                if next_token:
                    resp = polly.list_voices(NextToken=next_token)
                else:
                    resp = polly.list_voices()
                for v in resp.get('Voices', []):
                    vid = v.get('Id')
                    if vid:
                        voices.append(vid)
                next_token = resp.get('NextToken')
                if not next_token:
                    break

            if not voices:
                self.status_label.setText("No voices returned. Check region or credentials.")
                return

            unique = sorted(set(voices))
            self.voice_combo.clear()
            self.voice_combo.addItems(unique)
            # Try to keep current selection if still present
            idx = self.voice_combo.findText(self.default_voice)
            if idx >= 0:
                self.voice_combo.setCurrentIndex(idx)
            self.status_label.setText(f"Loaded {len(unique)} voices from AWS Polly.")
        except Exception as e:
            self.status_label.setText(f"Error loading voices: {e}")


def main():
    app = QApplication(sys.argv)
    win = VotingUI()
    win.resize(640, 480)
    win.show()
    sys.exit(app.exec())


if __name__ == "__main__":
    main()