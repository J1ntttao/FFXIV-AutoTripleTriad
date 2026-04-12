import sys
import threading
import time
from dataclasses import dataclass

import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab, ImageQt
from PyQt5.QtCore import QTimer, Qt
from PyQt5.QtGui import QImage, QPixmap
from PyQt5.QtWidgets import QApplication, QLabel, QMainWindow, QPushButton, QVBoxLayout, QWidget


def qimage_from_pil(pil_image):
    return QImage(ImageQt.ImageQt(pil_image))


@dataclass
class DetectedBox:
    color_name: str
    center: tuple
    bbox: tuple
    contour: np.ndarray


class StatusOverlay(QLabel):
    def __init__(self):
        super().__init__(None, Qt.Window | Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setStyleSheet(
            "color: white; background-color: rgba(0, 0, 0, 180); "
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


def grab_screen():
    return ImageGrab.grab()


def to_bgr(pil_image):
    rgb = np.array(pil_image)
    return cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR)


def find_color_boxes(frame_bgr):
    hsv = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2HSV)
    color_hsv_ranges = {
        "blue": [((90, 80, 70), (130, 255, 255))],
        "green": [((45, 80, 70), (85, 255, 255))],
        "red": [((0, 80, 70), (10, 255, 255)), ((160, 80, 70), (180, 255, 255))],
        "yellow": [((18, 100, 100), (35, 255, 255))],
    }
    boxes = []

    for name, ranges in color_hsv_ranges.items():
        mask = None
        for lower, upper in ranges:
            lower_np = np.array(lower, dtype=np.uint8)
            upper_np = np.array(upper, dtype=np.uint8)
            part_mask = cv2.inRange(hsv, lower_np, upper_np)
            mask = part_mask if mask is None else cv2.bitwise_or(mask, part_mask)

        mask = cv2.morphologyEx(mask, cv2.MORPH_CLOSE, np.ones((7, 7), np.uint8))
        mask = cv2.morphologyEx(mask, cv2.MORPH_OPEN, np.ones((5, 5), np.uint8))

        contours, _ = cv2.findContours(mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
        for contour in contours:
            area = cv2.contourArea(contour)
            if area < 3000:
                continue

            x, y, w, h = cv2.boundingRect(contour)
            if not ((120 <= w <= 190 and 130 <= h <= 190) or (120 <= h <= 190 and 130 <= w <= 190)):
                continue

            rect_area = w * h
            if rect_area <= 0 or area / rect_area < 0.4:
                continue

            peri = cv2.arcLength(contour, True)
            approx = cv2.approxPolyDP(contour, 0.02 * peri, True)
            if len(approx) < 4 or len(approx) > 10:
                continue

            center = (x + w // 2, y + h // 2)
            boxes.append(DetectedBox(name, center, (x, y, w, h), contour))

    return boxes


def draw_boxes(frame_bgr, boxes):
    overlay = frame_bgr.copy()
    colors = {
        "blue": (255, 0, 0),
        "green": (0, 255, 0),
        "red": (0, 0, 255),
        "yellow": (0, 215, 255),
    }
    for box in boxes:
        x, y, w, h = box.bbox
        cv2.rectangle(overlay, (x, y), (x + w, y + h), colors.get(box.color_name, (255, 255, 255)), 3)
        cv2.circle(overlay, box.center, 5, (255, 255, 255), -1)
        cv2.putText(overlay, box.color_name, (x, y - 10), cv2.FONT_HERSHEY_SIMPLEX, 0.7, colors.get(box.color_name, (255, 255, 255)), 2)
    return overlay


def drag_to_target(non_blue_center, blue_center):
    if non_blue_center is None or blue_center is None:
        return
    px, py = non_blue_center
    tx, ty = blue_center
    pyautogui.PAUSE = 0.0
    pyautogui.FAILSAFE = False
    pyautogui.moveTo(px, py, duration=0.3)
    pyautogui.mouseDown()
    pyautogui.moveTo(tx, ty, duration=0.3)
    pyautogui.mouseUp()


class ScreenCaptureWindow(QMainWindow):
    def __init__(self):
        super().__init__()
        self.setWindowTitle("屏幕检测与拖拽")
        self.setGeometry(100, 100, 900, 700)

        self.image_label = QLabel(self)
        self.image_label.setAlignment(Qt.AlignCenter)
        self.image_label.setMinimumSize(800, 600)

        self.status_label = QLabel("状态：等待启动", self)
        self.start_button = QPushButton("开始检测", self)
        self.stop_button = QPushButton("停止检测", self)
        self.stop_button.setEnabled(False)

        layout = QVBoxLayout()
        layout.addWidget(self.image_label)
        layout.addWidget(self.status_label)
        layout.addWidget(self.start_button)
        layout.addWidget(self.stop_button)

        container = QWidget()
        container.setLayout(layout)
        self.setCentralWidget(container)

        self.start_button.clicked.connect(self.start_detection)
        self.stop_button.clicked.connect(self.stop_detection)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.update_frame)
        self.running = False
        self.last_action = ""
        self.lock = threading.Lock()
        self.status_overlay = StatusOverlay()

    def start_detection(self):
        self.running = True
        self.start_button.setEnabled(False)
        self.stop_button.setEnabled(True)
        self.status_label.setText("状态：正在检测，每秒截图一次")
        self.timer.start(1000)

    def stop_detection(self):
        self.running = False
        self.start_button.setEnabled(True)
        self.stop_button.setEnabled(False)
        self.status_label.setText("状态：已停止")
        self.timer.stop()

    def update_frame(self):
        if not self.running:
            return

        screenshot = grab_screen()
        frame = to_bgr(screenshot)
        boxes = find_color_boxes(frame)
        overlay = draw_boxes(frame, boxes)

        blue_boxes = [b for b in boxes if b.color_name == "blue"]
        other_boxes = [b for b in boxes if b.color_name != "blue"]

        if blue_boxes and other_boxes:
            target_center = blue_boxes[0].center
            for box in other_boxes:
                self.last_action = f"拖动 {box.color_name} 方框到蓝色中心"
                # 执行拖动动作时先释放锁并在单独线程完成，避免 UI 阻塞
                threading.Thread(target=drag_to_target, args=(box.center, target_center), daemon=True).start()
        elif not blue_boxes:
            self.last_action = "未检测到蓝色方框"
        else:
            self.last_action = "未检测到其他颜色方框"

        self.status_overlay.update_text(f"状态：{self.last_action}")
        height, width, _ = overlay.shape
        bytes_per_line = 3 * width
        qt_image = QImage(overlay.data, width, height, bytes_per_line, QImage.Format_BGR888)
        pixmap = QPixmap.fromImage(qt_image).scaled(self.image_label.size(), Qt.KeepAspectRatio, Qt.SmoothTransformation)
        self.image_label.setPixmap(pixmap)
        self.status_label.setText(f"状态：{self.last_action}")


def main():
    app = QApplication(sys.argv)
    window = ScreenCaptureWindow()
    window.show()
    sys.exit(app.exec_())


if __name__ == "__main__":
    main()
