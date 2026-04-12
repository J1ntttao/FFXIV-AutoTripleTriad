import sys
import time
import ctypes
import configparser
from pathlib import Path
import pyautogui
from PyQt5.QtCore import QThread, pyqtSignal, Qt, QTimer
from PyQt5.QtGui import QFont
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget, QTextEdit, QMessageBox

from drag_module import grab_screen, to_bgr, find_color_boxes, drag_to_target, click_point

CONFIG_PATH = Path(__file__).parent / "conf.ini"
CONFIG_SECTION = "click_positions"


def load_positions():
    config = configparser.ConfigParser()
    if not CONFIG_PATH.exists():
        return []
    config.read(CONFIG_PATH, encoding="utf-8")
    if CONFIG_SECTION not in config:
        return []
    positions = []
    for i in range(1, 4):
        key = f"pos{i}"
        if key in config[CONFIG_SECTION]:
            try:
                x, y = config[CONFIG_SECTION][key].split(",")
                positions.append((int(x), int(y)))
            except ValueError:
                continue
    return positions


def save_positions(positions):
    config = configparser.ConfigParser()
    config[CONFIG_SECTION] = {}
    for i, (x, y) in enumerate(positions, start=1):
        config[CONFIG_SECTION][f"pos{i}"] = f"{x},{y}"
    with open(CONFIG_PATH, "w", encoding="utf-8") as f:
        config.write(f)


def is_left_mouse_down():
    return bool(ctypes.windll.user32.GetAsyncKeyState(0x01) & 0x8000)


class StatusOverlay(QLabel):
    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 200);"
            "padding: 10px 16px; border-radius: 12px; font-size: 14px;"
        )
        self.setAlignment(Qt.AlignCenter)
        self.setWindowFlag(Qt.WindowDoesNotAcceptFocus)
        self.setText("状态：等待启动")
        self.adjustSize()
        self.show()

    def update_text(self, text):
        self.setText(text)
        self.adjustSize()
        screen = QApplication.primaryScreen()
        if screen:
            geo = screen.geometry()
            x = geo.x() + (geo.width() - self.width()) // 2
            y = geo.y() + 120
            self.move(x, y)


class FlowWorker(QThread):
    log_signal = pyqtSignal(str)
    finished_signal = pyqtSignal()

    def __init__(self, positions):
        super().__init__()
        self.positions = positions
        self._running = True

    def stop(self):
        self._running = False

    def run(self):
        self.log_signal.emit("开始执行流程")

        while self._running:
            drag_count = 0
            while drag_count < 5 and self._running:
                screenshot = grab_screen()
                frame = to_bgr(screenshot)
                blue_boxes = [b for b in find_color_boxes(frame) if b.color_name == "blue"]
                other_boxes = [b for b in find_color_boxes(frame) if b.color_name != "blue"]

                if not blue_boxes:
                    self.log_signal.emit("未检测到蓝色方框，继续检测...")
                    time.sleep(0.5)
                    continue

                if not other_boxes:
                    self.log_signal.emit("检测到蓝色方框，但未检测到其它颜色方框，继续检测...")
                    time.sleep(0.5)
                    continue

                target_center = blue_boxes[0].center
                for box in other_boxes:
                    if drag_count >= 5 or not self._running:
                        break
                    drag_count += 1
                    self.log_signal.emit(f"第 {drag_count} 次拖动：{box.color_name} 方框")
                    drag_to_target(box.center, target_center)
                    time.sleep(0.2)

            if not self._running:
                break

            self.log_signal.emit("已完成 5 次拖动，开始点击录入位置")

            for idx, pos in enumerate(self.positions, start=1):
                if not self._running:
                    break
                click_point(pos)
                self.log_signal.emit(f"点击第 {idx} 个位置：{pos[0]},{pos[1]}")
                time.sleep(2)

            if not self._running:
                break

            self.log_signal.emit("已完成 3 次点击，返回继续检测蓝色方框")

        self.log_signal.emit("流程已停止")
        self.finished_signal.emit()


class FlowWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("流程执行器")
        self.setGeometry(150, 150, 820, 620)

        self.recorded_positions = load_positions()

        self.log_view = QTextEdit(self)
        self.log_view.setReadOnly(True)
        self.log_view.setFont(QFont("Consolas", 11))

        self.position_label = QLabel(self)
        self.position_label.setText(self._position_text())
        self.position_label.setWordWrap(True)

        self.record_button = QPushButton("录入位置", self)
        self.record_button.clicked.connect(self.record_position)

        self.start_button = QPushButton("开始流程", self)
        self.start_button.clicked.connect(self.start_flow)
        self.start_button.setEnabled(len(self.recorded_positions) == 3)

        self.stop_button = QPushButton("停止流程", self)
        self.stop_button.clicked.connect(self.stop_flow)
        self.stop_button.setEnabled(False)

        self.waiting_for_click = False
        self.click_ready = False
        self.click_timer = QTimer(self)
        self.click_timer.setInterval(50)
        self.click_timer.timeout.connect(self._poll_click_position)

        layout = QVBoxLayout()
        layout.addWidget(QLabel("配置点击位置（连续录入三次）：", self))
        layout.addWidget(self.position_label)
        layout.addWidget(self.record_button)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)
        layout.addWidget(QLabel("日志：", self))
        layout.addWidget(self.log_view)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.status_overlay = StatusOverlay()
        self.worker = None

    def _position_text(self):
        if not self.recorded_positions:
            return "当前无已录入位置。请按“录入位置”并移动鼠标到目标位置。"
        lines = [f"{i}. {pos[0]}, {pos[1]}" for i, pos in enumerate(self.recorded_positions, start=1)]
        return "已录入位置：\n" + "\n".join(lines)

    def record_position(self):
        if len(self.recorded_positions) >= 3:
            QMessageBox.information(self, "提示", "已录入 3 个位置，若要重新录入请先删除配置。")
            return

        self.record_button.setEnabled(False)
        self.waiting_for_click = True
        self.click_ready = False
        self.record_button.setText("请点击目标位置...")
        self.append_log(f"等待第 {len(self.recorded_positions) + 1} 个位置的鼠标点击")
        self.click_timer.start()

    def _poll_click_position(self):
        pressed = is_left_mouse_down()
        if not self.click_ready:
            if not pressed:
                self.click_ready = True
            return

        if pressed:
            pos = pyautogui.position()
            self.recorded_positions.append((pos.x, pos.y))
            save_positions(self.recorded_positions)
            self.position_label.setText(self._position_text())
            self.append_log(f"录入第 {len(self.recorded_positions)} 个位置：{pos.x}, {pos.y}")
            if len(self.recorded_positions) == 3:
                self.append_log("已完成位置录入，配置已保存到 conf.ini")

            self.click_timer.stop()
            self.waiting_for_click = False
            self.record_button.setText("录入位置")
            self.record_button.setEnabled(len(self.recorded_positions) < 3)
            self.start_button.setEnabled(len(self.recorded_positions) == 3)

    def start_flow(self):
        if len(self.recorded_positions) < 3:
            QMessageBox.warning(self, "配置不足", "请先录入 3 个点击位置，再开始流程。")
            return

        self.start_button.setEnabled(False)
        self.record_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.log_view.clear()
        self.append_log("流程已启动")
        self.status_overlay.update_text("状态：流程执行中")

        self.worker = FlowWorker(self.recorded_positions)
        self.worker.log_signal.connect(self.append_log)
        self.worker.log_signal.connect(self.status_overlay.update_text)
        self.worker.finished_signal.connect(self.flow_finished)
        self.worker.start()

    def stop_flow(self):
        if self.worker and self.worker.isRunning():
            self.worker.stop()
            self.append_log("停止流程请求已发送")
            self.stop_button.setEnabled(False)

    def append_log(self, text):
        self.log_view.append(text)

    def flow_finished(self):
        self.append_log("流程执行结束")
        self.status_overlay.update_text("状态：流程已结束")
        self.start_button.setEnabled(len(self.recorded_positions) == 3)
        self.record_button.setEnabled(True)
        self.stop_button.setEnabled(False)


def main():
    app = QApplication(sys.argv)
    window = FlowWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
