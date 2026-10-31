"""Prevent page scrolling from changing controls the user has not clicked."""

from __future__ import annotations

import weakref

from PySide6.QtCore import QEvent, QObject, QPointF, Qt
from PySide6.QtGui import QWheelEvent
from PySide6.QtWidgets import (
    QApplication, QAbstractScrollArea, QAbstractSlider, QAbstractSpinBox, QComboBox, QDateTimeEdit,
    QScrollBar, QWidget,
)


_RELEVANT_EVENTS = {QEvent.Type.Polish, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel}


def _is_editor(widget) -> bool:
    return isinstance(widget, (QAbstractSpinBox, QComboBox, QAbstractSlider)) and not isinstance(widget, QScrollBar)


def _editor_for(widget):
    while isinstance(widget, QWidget):
        if _is_editor(widget):
            return widget
        widget = widget.parentWidget()
    return None


class WheelFocusGuard(QObject):
    def __init__(self, app):
        super().__init__(app)
        self._clicked = None

    def eventFilter(self, watched, event):
        kind = event.type()
        if kind not in _RELEVANT_EVENTS:
            return False
        if kind == QEvent.Type.Polish and _is_editor(watched):
            watched.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
        elif kind == QEvent.Type.MouseButtonPress:
            editor = _editor_for(watched)
            self._clicked = weakref.ref(editor) if editor is not None else None
        elif kind == QEvent.Type.Wheel:
            editor = _editor_for(watched)
            if editor is None:
                return False
            # Once opened by the user, popup lists/calendars retain normal scrolling.
            if isinstance(editor, QComboBox) and editor.view().isVisible():
                return False
            if isinstance(editor, QDateTimeEdit) and editor.calendarPopup() and editor.calendarWidget().isVisible():
                return False
            clicked = self._clicked() if self._clicked is not None else None
            if clicked is editor and editor.hasFocus():
                return False
            # Qt does not always propagate a filtered wheel event. Deliver a
            # position-correct copy to the enclosing viewport exactly once.
            parent = editor.parentWidget()
            while parent is not None:
                if isinstance(parent, QAbstractScrollArea):
                    viewport = parent.viewport()
                    forwarded = QWheelEvent(
                        QPointF(viewport.mapFromGlobal(event.globalPosition().toPoint())),
                        event.globalPosition(), event.pixelDelta(), event.angleDelta(),
                        event.buttons(), event.modifiers(), event.phase(), event.inverted(), event.source(),
                    )
                    QApplication.sendEvent(viewport, forwarded)
                    event.accept()
                    return True
                parent = parent.parentWidget()
            event.ignore()
            return True
        return False


def install_wheel_focus_guard():
    app = QApplication.instance()
    if app is None:
        return None
    guard = getattr(app, '_plugin_wheel_focus_guard', None)
    if guard is None:
        guard = WheelFocusGuard(app)
        app._plugin_wheel_focus_guard = guard
        app.installEventFilter(guard)
        for widget in app.allWidgets():
            if _is_editor(widget):
                widget.setFocusPolicy(Qt.FocusPolicy.ClickFocus)
    return guard
