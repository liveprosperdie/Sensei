import sys
import os
import math
import socket
import threading
from PyQt6.QtWidgets import QApplication, QWidget, QLabel, QMenu
from PyQt6.QtCore import Qt, QPoint, QTimer, pyqtSignal
from PyQt6.QtGui import QPixmap, QCursor, QAction
import win32gui
import win32con

# Config
SPRITE_DIR = os.path.join(os.path.dirname(__file__), "sensei-avatar", "src", "assets")
DEFAULT_SPRITE = "akira.png"
UDP_PORT = 55555

class AvatarWindow(QWidget):
    speaking_signal = pyqtSignal(bool)

    def __init__(self):
        super().__init__()
        
        self.dragging = False
        self.offset = QPoint()
        self.click_through = False
        self.is_speaking = False
        
        self.init_ui()
        self.load_sprites()
        self.start_udp_listener()
        
        # Connect UDP signal to UI update
        self.speaking_signal.connect(self.handle_speaking_state)
        
        # Eye tracking timer (60 FPS)
        self.tracking_timer = QTimer(self)
        self.tracking_timer.timeout.connect(self.update_eyes)
        self.tracking_timer.start(16)
        
    def init_ui(self):
        # Frameless, transparent, stays on top, tool window (hides from taskbar)
        self.setWindowFlags(
            Qt.WindowType.FramelessWindowHint | 
            Qt.WindowType.WindowStaysOnTopHint | 
            Qt.WindowType.Tool
        )
        self.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        
        self.label = QLabel(self)
        self.label.setScaledContents(True)
        
        # Default size, will be updated by sprite
        self.resize(300, 300)
        self.label.resize(300, 300)
        
        self.show()

    def load_sprites(self):
        """Pre-load all requested sprites."""
        self.sprites = {}
        expected = [
            "idle.png", "blink.png", "talk_open.png", "talk_closed.png",
            "look_up.png", "look_down.png", "look_left.png", "look_right.png",
            DEFAULT_SPRITE
        ]
        
        for name in expected:
            path = os.path.join(SPRITE_DIR, name)
            if os.path.exists(path):
                self.sprites[name] = QPixmap(path)
                
        # Set default
        if "idle.png" in self.sprites:
            self.current_sprite_name = "idle.png"
        elif DEFAULT_SPRITE in self.sprites:
            self.current_sprite_name = DEFAULT_SPRITE
        else:
            print(f"[avatar] WARNING: No sprites found in {SPRITE_DIR}")
            self.current_sprite_name = None
            
        self.update_sprite(self.current_sprite_name)
        
    def update_sprite(self, name):
        if not name or name not in self.sprites:
            return
        
        pixmap = self.sprites[name]
        self.label.setPixmap(pixmap)
        
        # Auto-resize window to match first loaded sprite
        if self.width() != pixmap.width():
            self.resize(pixmap.width(), pixmap.height())
            self.label.resize(pixmap.width(), pixmap.height())
            
    def handle_speaking_state(self, is_speaking):
        self.is_speaking = is_speaking
        if is_speaking:
            # We would normally alternate rapidly using a timer, but for now just open mouth
            self.update_sprite("talk_open.png" if "talk_open.png" in self.sprites else self.current_sprite_name)
        else:
            self.update_sprite("idle.png" if "idle.png" in self.sprites else self.current_sprite_name)

    def update_eyes(self):
        if self.is_speaking:
            return # Don't look around while talking for now to avoid logic clash
            
        # Get global mouse pos
        mouse_pos = QCursor.pos()
        center = self.geometry().center()
        
        dx = mouse_pos.x() - center.x()
        dy = mouse_pos.y() - center.y()
        
        # Deadzone so she stares forward if mouse is close or right on her
        if abs(dx) < 100 and abs(dy) < 100:
            target = "idle.png"
        else:
            angle = math.degrees(math.atan2(dy, dx))
            # Convert angle to 4 directions
            if -45 <= angle <= 45:
                target = "look_right.png"
            elif 45 < angle < 135:
                target = "look_down.png"
            elif -135 < angle < -45:
                target = "look_up.png"
            else:
                target = "look_left.png"
                
        if target not in self.sprites:
            target = "idle.png" if "idle.png" in self.sprites else DEFAULT_SPRITE
            
        if not self.is_speaking:
            self.update_sprite(target)
            
    # -- Dragging Logic --
    def mousePressEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = True
            self.offset = event.globalPosition().toPoint() - self.frameGeometry().topLeft()
            
    def mouseMoveEvent(self, event):
        if self.dragging:
            self.move(event.globalPosition().toPoint() - self.offset)
            
    def mouseReleaseEvent(self, event):
        if event.button() == Qt.MouseButton.LeftButton:
            self.dragging = False

    # -- Context Menu --
    def contextMenuEvent(self, event):
        menu = QMenu(self)
        
        toggle_click_action = QAction("Toggle Click-Through", self)
        toggle_click_action.triggered.connect(self.toggle_clickthrough)
        menu.addAction(toggle_click_action)
        
        quit_action = QAction("Quit Avatar", self)
        quit_action.triggered.connect(self.close)
        menu.addAction(quit_action)
        
        menu.exec(event.globalPos())

    def toggle_clickthrough(self):
        hwnd = int(self.winId())
        ex_style = win32gui.GetWindowLong(hwnd, win32con.GWL_EXSTYLE)
        
        if self.click_through:
            # Turn off
            ex_style &= ~win32con.WS_EX_TRANSPARENT
            self.click_through = False
            print("[avatar] Click-through OFF")
        else:
            # Turn on
            ex_style |= win32con.WS_EX_TRANSPARENT
            self.click_through = True
            print("[avatar] Click-through ON")
            
        win32gui.SetWindowLong(hwnd, win32con.GWL_EXSTYLE, ex_style)

    # -- UDP Listener for Sensei integration --
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
                except Exception as e:
                    print(f"UDP Error: {e}")
        
        t = threading.Thread(target=listener, daemon=True)
        t.start()


if __name__ == "__main__":
    app = QApplication(sys.argv)
    window = AvatarWindow()
    sys.exit(app.exec())
