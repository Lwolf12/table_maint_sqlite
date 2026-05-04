"""Non-blocking message UI (spec §4.1 / §10 — avoid modal QMessageBox.exec)."""

from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget


def show_non_blocking(
    parent: QWidget | None,
    title: str,
    text: str,
    icon: QMessageBox.Icon = QMessageBox.Icon.Information,
) -> None:
    """Show a message window that does not block interaction with other windows."""
    box = QMessageBox(parent)
    box.setWindowTitle(title)
    box.setText(text)
    box.setIcon(icon)
    box.setStandardButtons(QMessageBox.StandardButton.Ok)
    box.setModal(False)
    box.setWindowModality(Qt.WindowModality.NonModal)
    box.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
    box.show()


def show_warning(parent: QWidget | None, title: str, text: str) -> None:
    show_non_blocking(parent, title, text, QMessageBox.Icon.Warning)


def confirm_yes_default(parent: QWidget | None, title: str, text: str) -> bool:
    """Modal Yes/No question; default button is Yes. Returns True if user chose Yes."""
    m = QMessageBox(parent)
    m.setIcon(QMessageBox.Icon.Question)
    m.setWindowTitle(title)
    m.setText(text)
    m.setStandardButtons(
        QMessageBox.StandardButton.Yes | QMessageBox.StandardButton.No
    )
    m.setDefaultButton(QMessageBox.StandardButton.Yes)
    return m.exec() == QMessageBox.StandardButton.Yes
