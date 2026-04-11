from PyQt5 import QtWidgets, QtGui
from PyQt5.QtCore import QThread, pyqtSignal
import cv2
import numpy as np
import pyautogui
import time
from PIL import ImageGrab
import win32gui
from PyQt5.QtWidgets import QMessageBox

class CaptureThread(QThread):
    update_status = pyqtSignal(str)

    def __init__(self, parent=None):
        super().__init__(parent)
        self.running = False
        self.selected_window = None

    def set_window(self, hwnd):
        self.selected_window = hwnd

    def run(self):
        self.running = True
        self.update_status.emit("正在执行...")

        # 定义颜色范围
        green_lower = np.array([0, 225, 0])
        green_upper = np.array([30, 255, 30])
        blue_lower = np.array([225, 94, 0])
        blue_upper = np.array([255, 154, 30])
        yellow_lower = np.array([0, 185, 195])
        yellow_upper = np.array([30, 245, 255])

        drag_count = 0
        click_positions = [(0.8, 0.9), (0.81, 0.97), (0.85, 0.7)]  # 使用比例

        try:
            while self.running:
                if not self.selected_window:
                    self.update_status.emit("未选择窗口")
                    time.sleep(1)
                    continue

                # 截取窗口画面
                rect = win32gui.GetWindowRect(self.selected_window)
                screenshot = ImageGrab.grab(bbox=rect)
                img = cv2.cvtColor(np.array(screenshot), cv2.COLOR_RGB2BGR)

                # 查找颜色框
                green_center = self.find_colored_box(img, green_lower, green_upper, rect)
                yellow_center = self.find_colored_box(img, yellow_lower, yellow_upper, rect)
                blue_center = self.find_colored_box(img, blue_lower, blue_upper, rect)

                if green_center and blue_center:
                    self.drag_box(green_center, blue_center)
                    drag_count += 1
                elif yellow_center and blue_center:
                    self.drag_box(yellow_center, blue_center)
                    drag_count += 1

                if drag_count >= 5:
                    self.perform_clicks(rect, click_positions)
                    drag_count = 0

                time.sleep(0.5)
        except Exception as e:
            self.update_status.emit(f"错误: {str(e)}")

    def stop(self):
        self.running = False

    def find_colored_box(self, img, lower, upper, rect):
        mask = cv2.inRange(img, lower, upper)
        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        if not contours:
            return None

        largest_contour = max(contours, key=cv2.contourArea)
        x, y, w, h = cv2.boundingRect(largest_contour)
        center_x = rect[0] + x + w // 2
        center_y = rect[1] + y + h // 2
        return (center_x, center_y)

    def drag_box(self, start, end):
        pyautogui.moveTo(start[0], start[1], duration=0.1)
        pyautogui.mouseDown()
        pyautogui.moveTo(end[0], end[1], duration=0.3)
        pyautogui.mouseUp()

    def perform_clicks(self, rect, positions):
        for x_ratio, y_ratio in positions:
            x = rect[0] + int((rect[2] - rect[0]) * x_ratio)
            y = rect[1] + int((rect[3] - rect[1]) * y_ratio)
            pyautogui.click(x, y)

class MainWindow(QtWidgets.QWidget):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("画面捕捉工具")
        self.setGeometry(100, 100, 400, 200)

        self.layout = QtWidgets.QVBoxLayout()

        # 添加 QTextEdit 控件并显示提示信息
        self.info_box = QtWidgets.QTextEdit()
        self.info_box.setReadOnly(True)
        self.info_box.setText("本程序需搭配卫月插件使用")
        self.layout.addWidget(self.info_box)

        self.start_button = QtWidgets.QPushButton("选择窗口并开始检测")
        self.start_button.clicked.connect(self.start_detection)
        self.layout.addWidget(self.start_button)

        self.status_label = QtWidgets.QLabel("状态: 等待开始")
        self.layout.addWidget(self.status_label)

        self.setLayout(self.layout)

        self.capture_thread = CaptureThread()
        self.capture_thread.update_status.connect(self.update_status)

    def start_detection(self):
        hwnd = self.select_window()
        if hwnd:
            self.capture_thread.set_window(hwnd)
            self.capture_thread.start()

    def select_window(self):
        def enum_windows(hwnd, result):
            if win32gui.IsWindowVisible(hwnd):
                result.append((hwnd, win32gui.GetWindowText(hwnd)))

        windows = []
        win32gui.EnumWindows(enum_windows, windows)
        items = [(hwnd, title) for hwnd, title in windows if title]

        item, ok = QtWidgets.QInputDialog.getItem(self, "选择窗口", "请选择一个窗口:", [title for _, title in items], 0, False)
        if ok and item:
            for hwnd, title in items:
                if title == item:
                    return hwnd
        return None

    def update_status(self, message):
        self.status_label.setText(f"状态: {message}")

    def closeEvent(self, event):
        self.capture_thread.stop()
        self.capture_thread.wait()
        event.accept()

if __name__ == "__main__":
    app = QtWidgets.QApplication([])
    window = MainWindow()
    window.show()
    app.exec_()
