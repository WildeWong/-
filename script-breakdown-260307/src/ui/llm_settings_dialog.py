"""LLM configuration dialog."""
from __future__ import annotations

from PyQt6.QtWidgets import (
    QDialog, QVBoxLayout, QHBoxLayout, QFormLayout,
    QComboBox, QLineEdit, QPushButton, QLabel, QGroupBox,
    QDoubleSpinBox, QSpinBox, QMessageBox,
)
from PyQt6.QtCore import Qt

from ..llm.base import LLMConfig, BaseLLM
from ..llm.claude_adapter import ClaudeAdapter
from ..llm.openai_adapter import OpenAIAdapter
from ..llm.ollama_adapter import OllamaAdapter


class LLMSettingsDialog(QDialog):
    """Dialog for configuring LLM provider settings."""

    def __init__(self, parent=None, config: LLMConfig | None = None):
        super().__init__(parent)
        self.setWindowTitle("LLM 设置")
        self.setMinimumWidth(480)
        self._config = config or LLMConfig()
        self._init_ui()
        self._load_config()

    def _init_ui(self):
        layout = QVBoxLayout(self)

        # Provider selection
        provider_group = QGroupBox("LLM 提供方")
        provider_layout = QFormLayout()

        self.provider_combo = QComboBox()
        self.provider_combo.addItems(["Claude (Anthropic)", "OpenAI", "Ollama (本地)"])
        self.provider_combo.currentIndexChanged.connect(self._on_provider_changed)
        provider_layout.addRow("提供方:", self.provider_combo)

        provider_group.setLayout(provider_layout)
        layout.addWidget(provider_group)

        # Connection settings
        conn_group = QGroupBox("连接设置")
        conn_layout = QFormLayout()

        self.api_key_edit = QLineEdit()
        self.api_key_edit.setEchoMode(QLineEdit.EchoMode.Password)
        self.api_key_edit.setPlaceholderText("输入 API Key...")
        conn_layout.addRow("API Key:", self.api_key_edit)

        self.model_edit = QLineEdit()
        self.model_edit.setPlaceholderText("模型名称")
        conn_layout.addRow("模型:", self.model_edit)

        self.base_url_edit = QLineEdit()
        self.base_url_edit.setPlaceholderText("http://localhost:11434")
        conn_layout.addRow("Base URL:", self.base_url_edit)

        conn_group.setLayout(conn_layout)
        layout.addWidget(conn_group)

        # Parameters
        param_group = QGroupBox("参数")
        param_layout = QFormLayout()

        self.temperature_spin = QDoubleSpinBox()
        self.temperature_spin.setRange(0.0, 2.0)
        self.temperature_spin.setSingleStep(0.1)
        self.temperature_spin.setValue(0.3)
        param_layout.addRow("Temperature:", self.temperature_spin)

        self.max_tokens_spin = QSpinBox()
        self.max_tokens_spin.setRange(256, 32768)
        self.max_tokens_spin.setSingleStep(256)
        self.max_tokens_spin.setValue(4096)
        param_layout.addRow("Max Tokens:", self.max_tokens_spin)

        param_group.setLayout(param_layout)
        layout.addWidget(param_group)

        # Buttons
        btn_layout = QHBoxLayout()

        self.test_btn = QPushButton("测试连接")
        self.test_btn.clicked.connect(self._test_connection)
        btn_layout.addWidget(self.test_btn)

        btn_layout.addStretch()

        self.ok_btn = QPushButton("确定")
        self.ok_btn.clicked.connect(self.accept)
        btn_layout.addWidget(self.ok_btn)

        self.cancel_btn = QPushButton("取消")
        self.cancel_btn.clicked.connect(self.reject)
        btn_layout.addWidget(self.cancel_btn)

        layout.addLayout(btn_layout)

    def _load_config(self):
        provider_map = {"claude": 0, "openai": 1, "ollama": 2}
        idx = provider_map.get(self._config.provider, 0)
        self.provider_combo.setCurrentIndex(idx)
        self.api_key_edit.setText(self._config.api_key)
        self.model_edit.setText(self._config.model_name)
        self.base_url_edit.setText(self._config.base_url)
        self.temperature_spin.setValue(self._config.temperature)
        self.max_tokens_spin.setValue(self._config.max_tokens)
        self._on_provider_changed(idx)

    def _on_provider_changed(self, index: int):
        is_ollama = index == 2
        self.api_key_edit.setEnabled(not is_ollama)
        self.base_url_edit.setEnabled(is_ollama)

        defaults = {
            0: ("claude-sonnet-4-5-20250929", ""),
            1: ("gpt-4o", ""),
            2: ("llama3", "http://localhost:11434"),
        }
        model, url = defaults.get(index, ("", ""))
        if not self.model_edit.text():
            self.model_edit.setText(model)
        if is_ollama and not self.base_url_edit.text():
            self.base_url_edit.setText(url)

    def get_config(self) -> LLMConfig:
        provider_names = ["claude", "openai", "ollama"]
        return LLMConfig(
            provider=provider_names[self.provider_combo.currentIndex()],
            model_name=self.model_edit.text().strip(),
            api_key=self.api_key_edit.text().strip(),
            base_url=self.base_url_edit.text().strip(),
            temperature=self.temperature_spin.value(),
            max_tokens=self.max_tokens_spin.value(),
        )

    def _test_connection(self):
        config = self.get_config()
        self.test_btn.setEnabled(False)
        self.test_btn.setText("测试中...")

        try:
            llm = create_llm(config)
            ok = llm.test_connection()
            if ok:
                QMessageBox.information(self, "成功", "LLM 连接成功！")
            else:
                QMessageBox.warning(self, "失败", "连接测试失败，请检查设置。")
        except Exception as e:
            QMessageBox.critical(self, "错误", f"连接错误:\n{e}")
        finally:
            self.test_btn.setEnabled(True)
            self.test_btn.setText("测试连接")


def create_llm(config: LLMConfig) -> BaseLLM:
    """Factory function to create an LLM adapter from config."""
    adapters = {
        "claude": ClaudeAdapter,
        "openai": OpenAIAdapter,
        "ollama": OllamaAdapter,
    }
    cls = adapters.get(config.provider)
    if cls is None:
        raise ValueError(f"Unknown LLM provider: {config.provider}")
    return cls(config)
