import sys
import os
import math
import random
import socket
import threading
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QMenu, QGraphicsOpacityEffect, QSystemTrayIcon
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal, QPropertyAnimation, QEasingCurve, QRect
from PyQt6.QtGui import QPixmap, QCursor, QAction, QIcon
import win32gui
import win32con

SPRITE_DIR = os.path.join(os.path.dirname(__file__), "sprites")
UDP_PORT = 55555
IDLE_SLEEP_MS = 5 * 60 * 1000  # 5 minutes idle timeout

class AvatarWindow(QWidget):
    speaking_signal = pyqtSignal(bool)
    sleep_signal = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        
        self.dragging = False
        self.offset = QPoint()
        self.click_through = False
        
        # States
        self.is_speaking = False
        self.is_sleeping = False
        self.is_patting = False
        self.current_sprite_name = "idle.png"
        self.talk_toggle = False
        
        self.init_ui()
        self.load_sprites()
        self.setup_animations()
        self.setup_timers()
        self.start_udp_listener()
        
        self.speaking_signal.connect(self.handle_speaking_state)
        self.sleep_signal.connect(self.handle_sleep_state)
        
    def init_ui(self):
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        # Setup two labels for crossfading
        self.label_bottom = QLabel(self)
        self.label_bottom.setScaledContents(True)
        
        self.label_top = QLabel(self)
        self.label_top.setScaledContents(True)
        
        self.opacity_effect = QGraphicsOpacityEffect()
        self.label_top.setGraphicsEffect(self.opacity_effect)
        self.opacity_effect.setOpacity(1.0)
        
        self.resize(250, 250)
        self.label_bottom.resize(250, 250)
        self.label_top.resize(250, 250)
        
        # System Tray Icon
        self.tray_icon = QSystemTrayIcon(self)
        self.tray_icon.setIcon(self.style().standardIcon(self.style().StandardPixmap.SP_ComputerIcon))
        
        tray_menu = QMenu()
        show_action = QAction("Show Avatar", self)
        show_action.triggered.connect(self.show_avatar)
        tray_menu.addAction(show_action)
        quit_action = QAction("Quit", self)
        quit_action.triggered.connect(QApplication.instance().quit)
        tray_menu.addAction(quit_action)
        
        self.tray_icon.setContextMenu(tray_menu)
        self.tray_icon.show()
        
        self.show()

    def load_sprites(self):
        self.sprites = {}
        expected = [
            "idle.png", "blink.png", "talk_open.png", "talk_closed.png",
            "look_up.png", "look_down.png", "look_left.png", "look_right.png",
            "happy.png", "sleep.png"
        ]
        for name in expected:
            path = os.path.join(SPRITE_DIR, name)
            if os.path.exists(path):
                self.sprites[name] = QPixmap(path)
                
        if "idle.png" in self.sprites:
            self.tray_icon.setIcon(QIcon(os.path.join(SPRITE_DIR, "idle.png")))
            
        self.label_bottom.setPixmap(self.sprites.get("idle.png", QPixmap()))
        self.label_top.setPixmap(self.sprites.get("idle.png", QPixmap()))

    def setup_animations(self):
        # Crossfade animation
        self.fade_anim = QPropertyAnimation(self.opacity_effect, b"opacity")
        self.fade_anim.setDuration(150)
        self.fade_anim.setStartValue(0.0)
        self.fade_anim.setEndValue(1.0)
        self.fade_anim.setEasingCurve(QEasingCurve.Type.InOutQuad)
        
        # Breathing animation (moves the window Y slightly)
        self.breath_anim = QPropertyAnimation(self, b"pos")
        self.breath_anim.setDuration(3000)
        self.breath_anim.setEasingCurve(QEasingCurve.Type.InOutSine)

    def setup_timers(self):
        # 60fps physics/eye tracking loop
        self.physics_timer = QTimer(self)
        self.physics_timer.timeout.connect(self.physics_loop)
        self.physics_timer.start(16)
        
        # Lip sync toggler
        self.lip_sync_timer = QTimer(self)
        self.lip_sync_timer.timeout.connect(self.lip_sync_tick)
        
        # Random blinker
        self.blink_timer = QTimer(self)
        self.blink_timer.timeout.connect(self.do_blink)
        self.blink_timer.start(random.randint(3000, 7000))
        self.is_blinking = False
        
        # Idle sleep timer
        self.idle_timer = QTimer(self)
        self.idle_timer.timeout.connect(lambda: self.handle_sleep_state(True))
        self.idle_timer.start(IDLE_SLEEP_MS)
        
        # Breathing loop trigger
        self.breath_loop_timer = QTimer(self)
        self.breath_loop_timer.timeout.connect(self.trigger_breath)
        self.breath_loop_timer.start(3000)
        self.base_pos = self.pos()

    def trigger_breath(self):
        if self.dragging: return
        
        dur = 4000 if self.is_sleeping else 3000
        depth = 4 if self.is_sleeping else 2
        
        self.breath_anim.setDuration(dur)
        self.breath_anim.setStartValue(self.base_pos)
        self.breath_anim.setKeyValueAt(0.5, QPoint(self.base_pos.x(), self.base_pos.y() - depth))
        self.breath_anim.setEndValue(self.base_pos)
        self.breath_anim.start()
        
        self.breath_loop_timer.setInterval(dur)

    def transition_sprite(self, target_name, instant=False):
        if target_name not in self.sprites or target_name == self.current_sprite_name:
            return
            
        if instant:
            self.label_top.setPixmap(self.sprites[target_name])
            self.opacity_effect.setOpacity(1.0)
            self.current_sprite_name = target_name
            return
            
        # Smooth crossfade
        self.label_bottom.setPixmap(self.sprites[self.current_sprite_name])
        self.label_top.setPixmap(self.sprites[target_name])
        self.current_sprite_name = target_name
        
        self.fade_anim.stop()
        self.fade_anim.start()

    def physics_loop(self):
        if self.is_sleeping or self.is_patting or self.is_blinking:
            return
            
        mouse_pos = QCursor.pos()
        center = self.geometry().center()
        
        dx = mouse_pos.x() - center.x()
        dy = mouse_pos.y() - center.y()
        
        if abs(dx) > 5 or abs(dy) > 5:
            self.idle_timer.start(IDLE_SLEEP_MS)
            
        if self.is_speaking:
            return
            
        if abs(dx) < 100 and abs(dy) < 100:
            self.transition_sprite("idle.png")
        else:
            angle = math.degrees(math.atan2(dy, dx))
            if -45 <= angle <= 45:
                self.transition_sprite("look_right.png")
            elif 45 < angle < 135:
                self.transition_sprite("look_down.png")
            elif -135 < angle < -45:
                self.transition_sprite("look_up.png")
            else:
                self.transition_sprite("look_left.png")

    def lip_sync_tick(self):
        self.talk_toggle = not self.talk_toggle
        target = "talk_open.png" if self.talk_toggle else "talk_closed.png"
        self.transition_sprite(target, instant=True)

    def do_blink(self):
        if self.is_sleeping or self.is_patting:
            return
        self.is_blinking = True
        prev = self.current_sprite_name
        self.transition_sprite("blink.png", instant=True)
        
        def restore():
            self.is_blinking = False
            self.transition_sprite(prev, instant=True)
            self.blink_timer.start(random.randint(3000, 7000))
            
        QTimer.singleShot(150, restore)

    def handle_speaking_state(self, is_speaking):
        self.is_speaking = is_speaking
        if is_speaking:
            if self.is_sleeping:
                self.handle_sleep_state(False)
            self.lip_sync_timer.start(150)
            self.talk_toggle = True
            self.transition_sprite("talk_open.png", instant=True)
        else:
            self.lip_sync_timer.stop()
            self.transition_sprite("idle.png")

    def handle_sleep_state(self, is_sleeping):
        self.is_sleeping = is_sleeping
        if is_sleeping:
            self.transition_sprite("sleep.png")
            self.lip_sync_timer.stop()
        else:
            self.transition_sprite("idle.png")
            self.idle_timer.start(IDLE_SLEEP_MS)

    def show_avatar(self):
        self.show()
        self.setWindowState(self.windowState() & ~Qt.WindowState.WindowMinimized | Qt.WindowState.WindowActive)
        self.activateWindow()

    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            if event.position().y() < self.height() * 0.3:
                self.is_patting = True
                self.handle_sleep_state(False)
                self.transition_sprite("happy.png", instant=False)
            else:
                self.dragging = True
                self.offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
                
    def mouseMoveEvent(self, event):
        if self.dragging:
            new_pos = event.globalPosition().toPoint() - self.offset
            self.move(new_pos)
            self.base_pos = new_pos
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False
            if self.is_patting:
                self.is_patting = False
                self.transition_sprite("idle.png")

    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        sleep_act = QAction("Wake Up" if self.is_sleeping else "Go to Sleep", self)
        sleep_act.triggered.connect(lambda: self.handle_sleep_state(not self.is_sleeping))
        menu.addAction(sleep_act)
        
        click_act = QAction("Toggle Click-Through", self)
        click_act.triggered.connect(self.toggle_clickthrough)
        menu.addAction(click_act)
        
        hide_act = QAction("Hide Avatar (To Tray)", self)
        hide_act.triggered.connect(self.hide)
        menu.addAction(hide_act)
        
        quit_act = QAction("Quit Avatar", self)
        quit_act.triggered.connect(QApplication.instance().quit)
        menu.addAction(quit_act)
        
        menu.exec(event.globalPos())

    def toggle_clickthrough(self):
        hwnd = int(self.winId())
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        if self.click_through:
            ex_style &= ~win32con.WS_EX_TRANSPARENT
            self.click_through = False
        else:
            ex_style |= win32con.WS_EX_TRANSPARENT
            self.click_through = True
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    def start_udp_listener(self):
        def listener():
            sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            sock.bind(('127.0.0.1', UDP_PORT))
            while True:
                try:
                    data, _ = sock.recvfrom(1024)
                    msg = data.decode('utf-8').strip()
                    if msg == "SPEAK_START":
                        self.speaking_signal.emit(True)
                    elif msg == "SPEAK_STOP":
                        self.speaking_signal.emit(False)
                    elif msg == "SLEEP_START":
                        self.sleep_signal.emit(True)
                    elif msg == "SLEEP_STOP":
                        self.sleep_signal.emit(False)
                except Exception as e:
                    print(f"UDP Error: {e}")
        
        t = threading.Thread(target=listener, daemon=True)
        t.start()

if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AvatarWindow()
    sys.exit(app.exec())
