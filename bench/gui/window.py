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
from PySide6.QtGui import QKeySequence, QShortcut
from PySide6.QtWidgets import (QApplication, QComboBox, QFrame, QHBoxLayout, QHeaderView, QLabel,
                               QMainWindow, QMessageBox, QPlainTextEdit, QPushButton, QTableWidget,
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
        self.tabs.addTab(self.build_failures_tab(), "Failures")
        self.tabs.addTab(self.build_review_tab(), "Review")
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
        ("refused", "refused"), ("failed", "failed"), ("dialect", "Iraqi"), ("critical", "critical"),
        ("accepted", "you accepted"), ("latency_median", "median s"), ("latency_p90", "p90 s"), ("memory_gb", "memory GB"), ("fits", "fits laptop"),
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
            rows_raw = results.compute()
            rows = rows_for_table(rows_raw)
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
        agreement = rows_raw[0]["judge_agreement"].words() if rows_raw else ""
        self.results_note.setText(f"{len(rows)} configurations; baseline rows highlighted. Selection split, with "
                                  f"95% intervals; 'vs baseline' is paired on the same sentences.\nJudge: {agreement}")

    # --- The Failures tab -------------------------------------------------------------

    FAILURE_COLUMNS = [("item", "item"), ("checks", "automatic checks"), ("judge", "judge"),
                       ("source", "source"), ("output", "output"), ("reference", "reference")]

    def build_failures_tab(self) -> QWidget:
        from bench.results_view import FAILURE_KINDS

        tab = QWidget()
        layout = QVBoxLayout(tab)
        top = QHBoxLayout()
        self.failure_config = QComboBox()
        self.failure_kind = QComboBox()
        self.failure_kind.addItems(FAILURE_KINDS)
        load = QPushButton("Load")
        load.clicked.connect(self.load_failure_data)
        self.failure_config.currentIndexChanged.connect(self.show_failures)
        self.failure_kind.currentIndexChanged.connect(self.show_failures)
        for w in (QLabel("Configuration:"), self.failure_config, QLabel("Show:"), self.failure_kind):
            top.addWidget(w)
        top.addStretch(1)
        top.addWidget(load)
        layout.addLayout(top)
        self.failure_note = QLabel("Press Load to read the outputs.")
        layout.addWidget(self.failure_note)
        self.failure_table = self.make_table([h for _, h in self.FAILURE_COLUMNS])
        self.failure_table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.failure_table.setWordWrap(True)
        layout.addWidget(self.failure_table, 1)
        self.failure_data = []
        return tab

    def load_failure_data(self):
        from bench import results

        self.failure_data = results.compute(keep_items=True)
        self.failure_config.blockSignals(True)
        self.failure_config.clear()
        for r in self.failure_data:
            if r.get("mt_key"):
                self.failure_config.addItem(f"{r['direction']}: {r['asr'] or '(text)'} + {r['translator']}", r["config"])
        self.failure_config.blockSignals(False)
        self.show_failures()

    def show_failures(self):
        from bench.results_view import failure_rows

        config = self.failure_config.currentData()
        if not config:
            return
        rows = failure_rows(self.failure_data, config, self.failure_kind.currentText())
        table = self.failure_table
        table.setRowCount(len(rows))
        for r, row in enumerate(rows):
            for c, (key, _) in enumerate(self.FAILURE_COLUMNS):
                item = QTableWidgetItem(str(row[key]))
                table.setItem(r, c, item)
        for c, width in enumerate((110, 130, 100, 330, 330, 330)):
            table.setColumnWidth(c, width)
        table.resizeRowsToContents()
        self.failure_note.setText(f"{len(rows)} output(s). Arabic and Persian text reads right to left.")

    # --- The Review tab ---------------------------------------------------------------

    def build_review_tab(self) -> QWidget:
        from bench import judge

        tab = QWidget()
        layout = QVBoxLayout(tab)
        top = QHBoxLayout()
        self.packet_box = QComboBox()
        self.packet_box.currentIndexChanged.connect(self.pick_packet)
        load = QPushButton("Load packets")
        load.clicked.connect(self.load_packets)
        top.addWidget(QLabel("Packet:"))
        top.addWidget(self.packet_box, 1)
        top.addWidget(load)
        layout.addLayout(top)
        self.review_help = QLabel("Rate each output: is it an acceptable translation of the source? The reference is "
                                  "a professional translation, for help. Keys: 1 acceptable, 2 minor issue, "
                                  "3 critical error, arrows to move.")
        self.review_help.setWordWrap(True)
        layout.addWidget(self.review_help)
        self.review_fields = {}
        big = QFont()
        big.setPointSize(13)
        for name in ("source", "reference", "output"):
            layout.addWidget(QLabel(f"<b>{name.capitalize()}</b>"))
            label = QLabel()
            label.setWordWrap(True)
            label.setFont(big)
            label.setTextInteractionFlags(Qt.TextSelectableByMouse)
            label.setFrameShape(QFrame.StyledPanel)
            label.setMinimumHeight(56)
            layout.addWidget(label)
            self.review_fields[name] = label
        self.play_button = QPushButton("Play the clip")
        self.play_button.clicked.connect(self.play_clip)
        layout.addWidget(self.play_button)
        rate = QHBoxLayout()
        for text, value in (("1  Acceptable", "acceptable"), ("2  Minor issue", "minor"),
                            ("3  Critical error", "critical")):
            b = QPushButton(text)
            b.clicked.connect(lambda _=False, v=value: self.rate(v))
            rate.addWidget(b)
        self.category_box = QComboBox()
        self.category_box.addItem("(critical error: what kind?)", "")
        for key, severity, words in judge.CATEGORIES:
            if severity == "critical":
                self.category_box.addItem(words, key)
        rate.addWidget(self.category_box, 1)
        layout.addLayout(rate)
        nav = QHBoxLayout()
        prev_b, next_b, clear_b = QPushButton("< Previous"), QPushButton("Next >"), QPushButton("Clear rating")
        prev_b.clicked.connect(lambda: self.move_item(-1))
        next_b.clicked.connect(lambda: self.move_item(1))
        clear_b.clicked.connect(self.clear_rating)
        self.review_progress = QLabel()
        nav.addWidget(prev_b)
        nav.addWidget(next_b)
        nav.addWidget(clear_b)
        nav.addStretch(1)
        nav.addWidget(self.review_progress)
        layout.addLayout(nav)
        layout.addStretch(1)
        for key, action in (("1", lambda: self.rate("acceptable")), ("2", lambda: self.rate("minor")),
                            ("3", lambda: self.rate("critical")), ("Left", lambda: self.move_item(-1)),
                            ("Right", lambda: self.move_item(1))):
            shortcut = QShortcut(QKeySequence(key), tab)
            shortcut.setContext(Qt.WidgetWithChildrenShortcut)
            shortcut.activated.connect(action)
        self.packets, self.packet, self.item_index = [], None, 0
        self.show_item()
        return tab

    def load_packets(self):
        from bench import results, review

        self.packets = review.packets(self.conn, results.compute(self.conn, keep_items=True))
        self.packet_box.blockSignals(True)
        self.packet_box.clear()
        for p in self.packets:
            self.packet_box.addItem(f"{p.name}  ({p.rated()} of {len(p.items)} rated)")
        self.packet_box.blockSignals(False)
        self.pick_packet(0)

    def pick_packet(self, index: int):
        from bench import review

        self.packet = self.packets[index] if 0 <= index < len(self.packets) else None
        self.item_index = review.next_unrated(self.packet) if self.packet and self.packet.items else 0
        self.show_item()

    def current_item(self):
        if not self.packet or not self.packet.items:
            return None
        return self.packet.items[self.item_index]

    def show_item(self):
        from bench import review

        it = self.current_item()
        for name, label in self.review_fields.items():
            text = getattr(it, name) if it else ""
            if it and self.packet.kind == "asr" and name == "source":
                text = "(listen to the clip)"
            label.setText(text)
            rtl = review.right_to_left(text)
            label.setLayoutDirection(Qt.RightToLeft if rtl else Qt.LeftToRight)
            label.setAlignment((Qt.AlignRight if rtl else Qt.AlignLeft) | Qt.AlignVCenter)
        self.play_button.setVisible(bool(it and it.audio))
        if not it:
            self.review_progress.setText("Press Load packets.")
            return
        rating = it.rating + (f" ({it.category})" if it.category else "") if it.rating else "not rated"
        self.review_progress.setText(f"Item {self.item_index + 1} of {len(self.packet.items)}: {rating}. "
                                     f"{self.packet.rated()} of {len(self.packet.items)} rated.")
        i = self.category_box.findData(it.category)
        self.category_box.setCurrentIndex(max(i, 0))

    def rate(self, value: str):
        from bench import review

        it = self.current_item()
        if not it:
            return
        category = self.category_box.currentData() if value == "critical" else ""
        review.save_rating(self.conn, it.key, it.item, value, category, rater="window")
        it.rating, it.category = value, category
        self.packet_box.setItemText(self.packet_box.currentIndex(),
                                    f"{self.packet.name}  ({self.packet.rated()} of {len(self.packet.items)} rated)")
        self.item_index = review.next_unrated(self.packet, self.item_index)
        self.show_item()

    def clear_rating(self):
        from bench import review

        it = self.current_item()
        if it:
            review.clear_rating(self.conn, it.key, it.item)
            it.rating, it.category = "", ""
            self.show_item()

    def move_item(self, step: int):
        if self.packet and self.packet.items:
            self.item_index = (self.item_index + step) % len(self.packet.items)
            self.show_item()

    def play_clip(self):
        it = self.current_item()
        if it and it.audio:
            os.startfile(it.audio)

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
