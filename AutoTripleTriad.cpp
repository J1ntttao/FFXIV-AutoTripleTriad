#include <QApplication>
#include <QMainWindow>
#include <QLabel>
#include <QPushButton>
#include <QVBoxLayout>
#include <QTimer>
#include <QScreen>
#include <QPixmap>
#include <QImage>
#include <QThread>
#include <opencv2/opencv.hpp>
#include <iostream>
#include <vector>
#include <string>

using namespace cv;

// DetectedBox structure
struct DetectedBox {
    std::string colorName;
    QPoint center;
    QRect bbox;
};

// Helper function to convert QImage to cv::Mat
cv::Mat QImageToCvMat(const QImage &image) {
    return cv::Mat(image.height(), image.width(), CV_8UC4, const_cast<uchar*>(image.bits()), image.bytesPerLine()).clone();
}

// Helper function to convert cv::Mat to QImage
QImage CvMatToQImage(const cv::Mat &mat) {
    cv::Mat rgb;
    cv::cvtColor(mat, rgb, cv::COLOR_BGR2RGB);
    return QImage(rgb.data, rgb.cols, rgb.rows, rgb.step, QImage::Format_RGB888).copy();
}

// Function to find color boxes
std::vector<DetectedBox> findColorBoxes(const cv::Mat &frameBGR) {
    cv::Mat hsv;
    cv::cvtColor(frameBGR, hsv, cv::COLOR_BGR2HSV);

    std::vector<DetectedBox> boxes;
    std::map<std::string, std::vector<std::pair<cv::Scalar, cv::Scalar>>> colorRanges = {
        {"blue", {{{90, 80, 70}, {130, 255, 255}}}},
        {"green", {{{45, 80, 70}, {85, 255, 255}}}},
        {"red", {{{0, 80, 70}, {10, 255, 255}}, {{160, 80, 70}, {180, 255, 255}}}},
        {"yellow", {{{18, 100, 100}, {35, 255, 255}}}}
    };

    for (const auto &[name, ranges] : colorRanges) {
        cv::Mat mask;
        for (const auto &[lower, upper] : ranges) {
            cv::Mat partMask;
            cv::inRange(hsv, lower, upper, partMask);
            if (mask.empty())
                mask = partMask;
            else
                cv::bitwise_or(mask, partMask, mask);
        }

        cv::morphologyEx(mask, mask, cv::MORPH_CLOSE, cv::getStructuringElement(cv::MORPH_RECT, {7, 7}));
        cv::morphologyEx(mask, mask, cv::MORPH_OPEN, cv::getStructuringElement(cv::MORPH_RECT, {5, 5}));

        std::vector<std::vector<cv::Point>> contours;
        cv::findContours(mask, contours, cv::RETR_EXTERNAL, cv::CHAIN_APPROX_SIMPLE);

        for (const auto &contour : contours) {
            double area = cv::contourArea(contour);
            if (area < 3000)
                continue;

            cv::Rect rect = cv::boundingRect(contour);
            if (!((120 <= rect.width && rect.width <= 190 && 130 <= rect.height && rect.height <= 190) ||
                  (120 <= rect.height && rect.height <= 190 && 130 <= rect.width && rect.width <= 190)))
                continue;

            double rectArea = rect.width * rect.height;
            if (rectArea <= 0 || area / rectArea < 0.4)
                continue;

            double peri = cv::arcLength(contour, true);
            std::vector<cv::Point> approx;
            cv::approxPolyDP(contour, approx, 0.02 * peri, true);
            if (approx.size() < 4 || approx.size() > 10)
                continue;

            QPoint center(rect.x + rect.width / 2, rect.y + rect.height / 2);
            boxes.push_back({name, center, QRect(rect.x, rect.y, rect.width, rect.height)});
        }
    }

    return boxes;
}

// Main window class
class ScreenCaptureWindow : public QMainWindow {
    Q_OBJECT

public:
    ScreenCaptureWindow() {
        setWindowTitle("自动幻卡AutoTripleTriad");
        setGeometry(100, 100, 900, 700);

        imageLabel = new QLabel(this);
        imageLabel->setAlignment(Qt::AlignCenter);
        imageLabel->setMinimumSize(800, 600);

        statusLabel = new QLabel("状态：等待启动", this);
        startButton = new QPushButton("开始检测", this);
        stopButton = new QPushButton("停止检测", this);
        stopButton->setEnabled(false);

        QVBoxLayout *layout = new QVBoxLayout();
        layout->addWidget(imageLabel);
        layout->addWidget(statusLabel);
        layout->addWidget(startButton);
        layout->addWidget(stopButton);

        QWidget *container = new QWidget();
        container->setLayout(layout);
        setCentralWidget(container);

        timer = new QTimer(this);
        connect(startButton, &QPushButton::clicked, this, &ScreenCaptureWindow::startDetection);
        connect(stopButton, &QPushButton::clicked, this, &ScreenCaptureWindow::stopDetection);
        connect(timer, &QTimer::timeout, this, &ScreenCaptureWindow::updateFrame);
    }

private slots:
    void startDetection() {
        running = true;
        startButton->setEnabled(false);
        stopButton->setEnabled(true);
        statusLabel->setText("状态：正在检测，每秒截图一次");
        timer->start(1000);
    }

    void stopDetection() {
        running = false;
        startButton->setEnabled(true);
        stopButton->setEnabled(false);
        statusLabel->setText("状态：已停止");
        timer->stop();
    }

    void updateFrame() {
        if (!running)
            return;

        QScreen *screen = QGuiApplication::primaryScreen();
        if (!screen)
            return;

        QPixmap screenshot = screen->grabWindow(0);
        QImage image = screenshot.toImage();
        cv::Mat frame = QImageToCvMat(image);

        auto boxes = findColorBoxes(frame);
        for (const auto &box : boxes) {
            cv::rectangle(frame, cv::Rect(box.bbox.x(), box.bbox.y(), box.bbox.width(), box.bbox.height()),
                          cv::Scalar(255, 0, 0), 3);
        }

        QImage resultImage = CvMatToQImage(frame);
        imageLabel->setPixmap(QPixmap::fromImage(resultImage).scaled(imageLabel->size(), Qt::KeepAspectRatio));
    }

private:
    QLabel *imageLabel;
    QLabel *statusLabel;
    QPushButton *startButton;
    QPushButton *stopButton;
    QTimer *timer;
    bool running = false;
};

int main(int argc, char *argv[]) {
    QApplication app(argc, argv);
    ScreenCaptureWindow window;
    window.show();
    return app.exec();
}