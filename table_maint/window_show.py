"""Show top-level windows without the native white-flash on Windows.

The flash is the OS painting the HWND client area before Qt's first paint
event arrives. Trick: create the window invisible (opacity 0), let Qt paint
once, then make it opaque. The intermediate frames are not on screen.
"""

from __future__ import annotations

from PySide6.QtWidgets import QApplication, QWidget


def show_smoothly(widget: QWidget, *, raise_: bool = False, activate: bool = False) -> None:
    """Show a top-level widget without a one-frame white flash."""
    widget.setWindowOpacity(0.0)
    widget.show()
    QApplication.processEvents()
    widget.setWindowOpacity(1.0)
    if raise_:
        widget.raise_()
    if activate:
        widget.activateWindow()
