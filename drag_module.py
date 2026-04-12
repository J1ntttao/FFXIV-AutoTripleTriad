import cv2
import numpy as np
import pyautogui
from PIL import ImageGrab
from dataclasses import dataclass


@dataclass
class DetectedBox:
    color_name: str
    center: tuple
    bbox: tuple
    contour: np.ndarray


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


def find_boxes_by_size(frame_bgr, target_w, target_h, tolerance=10):
    gray = cv2.cvtColor(frame_bgr, cv2.COLOR_BGR2GRAY)
    blurred = cv2.GaussianBlur(gray, (5, 5), 0)
    _, thresh = cv2.threshold(blurred, 0, 255, cv2.THRESH_BINARY_INV + cv2.THRESH_OTSU)
    kernel = np.ones((3, 3), np.uint8)
    thresh = cv2.morphologyEx(thresh, cv2.MORPH_CLOSE, kernel, iterations=2)

    contours, _ = cv2.findContours(thresh, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    boxes = []
    for contour in contours:
        x, y, w, h = cv2.boundingRect(contour)
        if abs(w - target_w) <= tolerance and abs(h - target_h) <= tolerance:
            boxes.append((x, y, w, h))
    return boxes


try:
    import pytesseract
except ImportError:
    pytesseract = None


def ocr_text_from_region(frame_bgr, bbox):
    x, y, w, h = bbox
    roi = frame_bgr[y:y + h, x:x + w]
    gray = cv2.cvtColor(roi, cv2.COLOR_BGR2GRAY)
    _, thresh = cv2.threshold(gray, 0, 255, cv2.THRESH_BINARY + cv2.THRESH_OTSU)

    if pytesseract is None:
        raise RuntimeError("pytesseract is required for OCR. Install it with 'pip install pytesseract'.")

    text = pytesseract.image_to_string(thresh, lang='chi_sim+eng')
    return text.strip().replace(" ", "").replace("\n", "")


def click_point(point):
    if point is None:
        return
    pyautogui.PAUSE = 0.0
    pyautogui.FAILSAFE = False
    pyautogui.click(point[0], point[1], button='left')
