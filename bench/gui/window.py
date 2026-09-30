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
from PySide6.QtWidgets import (QApplication, QHBoxLayout, QHeaderView, QLabel, QMainWindow,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
                               QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget)

from bench import db, round_view, rounds, session
from bench.config import ROOT

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
        self.tabs.addTab(self.build_round_tab(), "Round")
        self.tabs.addTab(self.build_results_tab(), "Results")
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

    # --- The Round tab ---------------------------------------------------------------

    def build_round_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        buttons = QHBoxLayout()
        for label, name in (("Open candidates.yaml", "candidates.yaml"), ("Open prompts folder", "prompts"),
                            ("Open settings.yaml", "settings.yaml")):
            b = QPushButton(label)
            b.clicked.connect(lambda _=False, n=name: os.startfile(ROOT / n))
            buttons.addWidget(b)
        reload_button = QPushButton("Reload")
        reload_button.clicked.connect(self.refresh_round)
        new_button = QPushButton("New round")
        new_button.clicked.connect(self.new_round)
        buttons.addStretch(1)
        buttons.addWidget(reload_button)
        buttons.addWidget(new_button)
        layout.addLayout(buttons)
        self.round_problems = QLabel()
        self.round_problems.setWordWrap(True)
        layout.addWidget(self.round_problems)
        self.asr_table = self.make_table(["ASR", "source", "languages", "baseline", "why", "risks"])
        self.translator_table = self.make_table(["translator", "source", "baseline", "why"])
        self.excluded_table = self.make_table(["left out", "why"])
        self.prompt_table = self.make_table(["prompt", "what it changes", "why"])
        for title, table in (("Speech recognizers", self.asr_table), ("Translators", self.translator_table),
                             ("Prompts", self.prompt_table), ("Considered and left out", self.excluded_table)):
            layout.addWidget(QLabel(f"<b>{title}</b>"))
            layout.addWidget(table)
        layout.addWidget(QLabel("<b>What New round would record</b>"))
        self.pending_view = QPlainTextEdit()
        self.pending_view.setReadOnly(True)
        layout.addWidget(self.pending_view)
        self.refresh_round()
        return tab

    @staticmethod
    def make_table(headers: list) -> QTableWidget:
        table = QTableWidget(0, len(headers))
        table.setHorizontalHeaderLabels(headers)
        table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        table.horizontalHeader().setStretchLastSection(True)
        table.setEditTriggers(QTableWidget.NoEditTriggers)
        table.verticalHeader().setVisible(False)
        return table

    @staticmethod
    def fill(table: QTableWidget, rows: list, keys: list) -> None:
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, key in enumerate(keys):
                table.setItem(r, c, QTableWidgetItem(str(row.get(key, ""))))
        table.resizeRowsToContents()
        height = table.horizontalHeader().height() + 4
        height += sum(table.rowHeight(r) for r in range(table.rowCount())) or table.verticalHeader().defaultSectionSize()
        table.setFixedHeight(height)

    def refresh_round(self):
        v = round_view.build()
        self.round_label.setText(f"Round {v.number}" if v.number else "Round —")
        if v.problems:
            self.round_problems.setText("<span style='color:#c0392b'><b>Problems:</b><br>"
                                        + "<br>".join(v.problems) + "</span>")
        else:
            self.round_problems.setText("<span style='color:#2e8b57'>The files are sound.</span>")
        self.fill(self.asr_table, v.asr, ["id", "source", "languages", "baseline", "why", "risks"])
        self.fill(self.translator_table, v.translators, ["id", "source", "baseline", "why"])
        self.fill(self.prompt_table, v.prompts, ["name", "changes", "why"])
        self.fill(self.excluded_table, v.excluded or [{"id": "(none)", "why": ""}], ["id", "why"])
        self.pending_view.setPlainText(v.pending)

    def new_round(self):
        answer = QMessageBox.question(self, "New round",
                                      "Snapshot candidates.yaml, prompts/ and settings.yaml as a new round, "
                                      "and draft its changelog?")
        if answer == QMessageBox.Yes:
            n = rounds.new_round()
            os.startfile(rounds.folder(n) / "changelog.md")
            self.refresh_round()

    # --- The Results tab --------------------------------------------------------------

    RESULT_COLUMNS = [
        ("direction", "direction"), ("asr", "ASR"), ("translator", "translator"), ("items", "items"),
        ("cer", "CER %"), ("cer_range", "CER 95%"), ("chrf", "chrF"), ("chrf_range", "chrF 95%"),
        ("refused", "refused"), ("failed", "failed"), ("dialect", "Iraqi"), ("latency_median", "median s"),
        ("latency_p90", "p90 s"), ("memory_gb", "memory GB"), ("fits", "fits laptop"),
        ("vs_baseline", "vs baseline"), ("warnings", "warnings"),
    ]

    def build_results_tab(self) -> QWidget:
        tab = QWidget()
        layout = QVBoxLayout(tab)
        top = QHBoxLayout()
        self.results_note = QLabel()
        refresh = QPushButton("Refresh")
        refresh.clicked.connect(self.refresh_results)
        top.addWidget(self.results_note, 1)
        top.addWidget(refresh)
        layout.addLayout(top)
        self.results_table = QTableWidget(0, len(self.RESULT_COLUMNS))
        self.results_table.setHorizontalHeaderLabels([h for _, h in self.RESULT_COLUMNS])
        self.results_table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeToContents)
        self.results_table.horizontalHeader().setStretchLastSection(True)
        self.results_table.setEditTriggers(QTableWidget.NoEditTriggers)
        self.results_table.setSortingEnabled(True)
        self.results_table.verticalHeader().setVisible(False)
        layout.addWidget(self.results_table)
        return tab

    def refresh_results(self):
        from PySide6.QtGui import QBrush, QColor

        from bench import results
        from bench.results_view import rows_for_table

        try:
            rows = rows_for_table(results.compute())
        except Exception as e:  # noqa: BLE001 - show why, rather than crash the window
            self.results_note.setText(f"Results can't be shown yet: {e}")
            return
        table = self.results_table
        table.setSortingEnabled(False)
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (key, _) in enumerate(self.RESULT_COLUMNS):
                value = row[key]
                item = QTableWidgetItem()
                if isinstance(value, (int, float)) and not isinstance(value, bool):
                    item.setData(Qt.DisplayRole, value)   # sorts as a number
                else:
                    item.setText(str(value))
                if row["baseline"]:
                    item.setBackground(QBrush(QColor(60, 80, 110)))
                table.setItem(r, c, item)
        table.setSortingEnabled(True)
        self.results_note.setText(f"{len(rows)} configurations; baseline rows highlighted. Selection split, with "
                                  "95% intervals; 'vs baseline' is paired on the same sentences.")

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
