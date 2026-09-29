"""The window: drawing only. Everything it shows comes from bench.session,
which reads state/bench.db; the window keeps no state of its own and never
runs a job itself. Start launches the runner as a separate process, so the
window can't freeze, and closing it doesn't have to stop the work.
"""

import os
import subprocess
import sys
import time

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QLabel, QMainWindow, QMessageBox,
                               QPlainTextEdit, QPushButton, QTabWidget, QVBoxLayout, QWidget)

from bench import db, session

REFRESH_MS = 500


class Window(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("model-bench")
        self.resize(1100, 700)
        self.conn = db.connect()
        self.started_runner = None      # the runner process this window launched, if any
        self.last_log_id = None

        self.start_button = QPushButton("Start")
        self.pause_button = QPushButton("Pause")
        self.retry_button = QPushButton("Retry failed")
        self.start_button.clicked.connect(self.start)
        self.pause_button.clicked.connect(self.pause)
        self.retry_button.clicked.connect(self.retry)
        self.round_label = QLabel("Round —")
        self.status_label = QLabel()
        bold = QFont()
        bold.setBold(True)
        self.status_label.setFont(bold)
        self.running_label = QLabel()
        self.counts_label = QLabel()
        self.estimate_label = QLabel()
        self.viewer_label = QLabel("Viewer: the queue is running from another window or the command line")
        self.viewer_label.setStyleSheet("color: #b36b00;")

        bar = QHBoxLayout()
        for w in (self.start_button, self.pause_button, self.retry_button, self.round_label,
                  self.status_label):
            bar.addWidget(w)
        bar.addStretch(1)
        bar.addWidget(self.counts_label)
        bar2 = QHBoxLayout()
        bar2.addWidget(QLabel("Now:"))
        bar2.addWidget(self.running_label, 1)
        bar2.addWidget(QLabel("Time left:"))
        bar2.addWidget(self.estimate_label)

        self.log_view = QPlainTextEdit()
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 10))
        self.tabs = QTabWidget()
        self.tabs.addTab(self.log_view, "Log")

        layout = QVBoxLayout()
        layout.addLayout(bar)
        layout.addLayout(bar2)
        layout.addWidget(self.viewer_label)
        layout.addWidget(self.tabs, 1)
        central = QWidget()
        central.setLayout(layout)
        self.setCentralWidget(central)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(REFRESH_MS)
        self.refresh()

    # --- Drawing ------------------------------------------------------------------

    def refresh(self):
        s = session.read(self.conn)
        mine = bool(self.started_runner and self.started_runner.poll() is None
                    and s.runner_pid == self.started_runner.pid)
        b = session.buttons(s, mine)
        self.start_button.setEnabled(b.start)
        self.pause_button.setEnabled(b.pause)
        self.retry_button.setEnabled(b.retry_failed)
        self.viewer_label.setVisible(b.viewer)
        self.status_label.setText(session.status_words(s))
        self.running_label.setText(session.now_running(s))
        self.counts_label.setText(session.counts_words(s))
        self.estimate_label.setText(session.estimate(s))
        text = "\n".join(f"{time.strftime('%H:%M:%S', time.localtime(l['ts']))}  {l['level']:5}  "
                         f"{l['message']}" for l in s.log)
        if text != self.log_view.toPlainText():
            at_bottom = (self.log_view.verticalScrollBar().value()
                         >= self.log_view.verticalScrollBar().maximum() - 4)
            self.log_view.setPlainText(text)
            if at_bottom:
                self.log_view.verticalScrollBar().setValue(self.log_view.verticalScrollBar().maximum())

    # --- Actions ------------------------------------------------------------------

    def start(self):
        flags = subprocess.CREATE_NEW_PROCESS_GROUP if os.name == "nt" else 0
        self.started_runner = subprocess.Popen(
            [sys.executable, "-m", "bench.cli", "start", "--no-window"], cwd=db.ROOT,
            creationflags=flags, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        self.refresh()

    def pause(self):
        db.set_flag(self.conn, "pause")
        self.refresh()

    def retry(self):
        db.retry_failed(self.conn)
        self.refresh()

    def closeEvent(self, event):
        s = session.read(self.conn, log_lines=1)
        if not session.close_question(s):
            event.accept()
            return
        box = QMessageBox(self)
        box.setWindowTitle("Jobs are running")
        box.setText("Jobs are still running. What should happen to them?")
        pause = box.addButton("Pause after the current job", QMessageBox.AcceptRole)
        stop = box.addButton("Stop now", QMessageBox.DestructiveRole)
        box.addButton("Cancel", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is pause:
            db.set_flag(self.conn, "pause")
            event.accept()
        elif box.clickedButton() is stop:
            db.set_flag(self.conn, "stop")
            event.accept()
        else:
            event.ignore()


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    app.setLayoutDirection(Qt.LeftToRight)
    window = Window()
    window.show()
    return app.exec()
