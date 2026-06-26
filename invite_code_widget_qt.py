import os
import re
import sys

from PySide6.QtCore import QTimer, Qt, QUrl
from PySide6.QtGui import QFont
from PySide6.QtWidgets import (
    QApplication,
    QHBoxLayout,
    QLabel,
    QMainWindow,
    QPushButton,
    QVBoxLayout,
    QWidget,
)
from PySide6.QtWebEngineCore import QWebEngineProfile, QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView


ADMIN_URL = "https://bonuspharma1.pythonanywhere.com/admin"
APP_NAME = "InviteCodeWidgetQT"


EXTRACT_JS = r"""
(() => {
  function toLatinDigits(s) {
    const map = {"٠":"0","١":"1","٢":"2","٣":"3","٤":"4","٥":"5","٦":"6","٧":"7","٨":"8","٩":"9"};
    return String(s || "").replace(/[٠-٩]/g, d => map[d] || d);
  }

  const labelNeedle = /كود\s*الدعوة/i;
  const labels = document.querySelectorAll("div,span,label,p");

  for (let i = 0; i < labels.length; i++) {
    const el = labels[i];
    const t = (el.textContent || "").trim();
    if (!labelNeedle.test(t)) continue;
    const container = el.closest("div") || el.parentElement;
    if (!container) continue;
    const candidates = container.querySelectorAll("div,span,p,strong,b");
    let best = "";
    for (let j = 0; j < candidates.length; j++) {
      const raw = toLatinDigits((candidates[j].textContent || "").trim());
      const m = raw.match(/(\d{4,12})/);
      if (!m) continue;
      const v = m[1];
      if (v.length > best.length) best = v;
    }
    if (best) return best;
  }
  return "";
})();
"""


CHANGE_JS = r"""
(() => {
  function norm(s){ return String(s || "").trim(); }
  const changeNeedles = ["تغيير","تجديد","تحديث","اعادة","إعادة","Refresh","Change","Generate"];
  const copyNeedles = ["نسخ","Copy"];
  function hasAny(text, arr){
    for (let i = 0; i < arr.length; i++) {
      if (text.indexOf(arr[i]) !== -1) return true;
    }
    return false;
  }

  const labelEls = document.querySelectorAll("div,span,label,p");
  for (let i = 0; i < labelEls.length; i++) {
    const el = labelEls[i];
    if (!/كود\s*الدعوة/i.test((el.textContent || "").trim())) continue;
    const container = el.closest("div") || el.parentElement;
    if (!container) continue;
    const btns = container.querySelectorAll("button,a");
    for (let j = 0; j < btns.length; j++) {
      const b = btns[j];
      const hay = norm(b.textContent) + " " + norm(b.getAttribute("title")) + " " + norm(b.getAttribute("aria-label"));
      if (hasAny(hay, copyNeedles)) continue;
      if (hasAny(hay, changeNeedles)) { b.click(); return true; }
    }
  }

  const allBtns = document.querySelectorAll("button,a");
  for (let k = 0; k < allBtns.length; k++) {
    const b = allBtns[k];
    const hay = norm(b.textContent) + " " + norm(b.getAttribute("title")) + " " + norm(b.getAttribute("aria-label"));
    if (hasAny(hay, copyNeedles)) continue;
    if (hasAny(hay, changeNeedles)) { b.click(); return true; }
  }
  return false;
})();
"""


class BrowserWindow(QMainWindow):
    def __init__(self, profile: QWebEngineProfile):
        super().__init__()
        self.setWindowTitle("InviteCodeWidget_scraper")
        self.resize(1100, 760)
        self.view = QWebEngineView(self)
        page = QWebEnginePage(profile, self.view)
        self.view.setPage(page)
        self.setCentralWidget(self.view)
        self.view.load(QUrl(ADMIN_URL))

    def load_admin(self):
        self.view.load(QUrl(ADMIN_URL))

    def run_js(self, code, callback=None):
        self.view.page().runJavaScript(code, callback)


class OverlayWidget(QWidget):
    def __init__(self, browser: BrowserWindow):
        super().__init__()
        self.browser = browser
        self.pinned = False  # disable top-most during login
        self.last_code = ""
        self.first_found = False

        self.setWindowTitle("InviteCodeWidget_overlay")
        self.setFixedSize(360, 190)
        self.setWindowFlags(
            Qt.Window | Qt.WindowCloseButtonHint | Qt.WindowMinimizeButtonHint
        )
        self.setStyleSheet(
            """
            QWidget { background: #0d1a2d; color: #ffffff; }
            #card { border: 1px solid rgba(255,255,255,0.18); border-radius: 14px; background: #0d1a2d; }
            QPushButton {
              border: 1px solid rgba(255,255,255,0.2);
              border-radius: 10px;
              padding: 6px 10px;
              background: rgba(255,255,255,0.08);
              color: #fff;
              font-weight: 600;
            }
            QPushButton:hover { background: rgba(255,255,255,0.16); }
            #changeBtn { background: rgba(66,165,245,0.22); border-color: rgba(66,165,245,0.45); }
            #titleLbl { font-size: 14px; font-weight: 700; }
            #codeLbl { font-size: 34px; font-weight: 800; }
            #hintLbl { font-size: 11px; color: rgba(255,255,255,0.75); }
            """
        )

        root = QVBoxLayout(self)
        root.setContentsMargins(8, 8, 8, 8)

        card = QWidget(self)
        card.setObjectName("card")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(12, 12, 12, 10)
        card_l.setSpacing(8)

        top = QHBoxLayout()
        self.title_lbl = QLabel("كود الدعوة")
        self.title_lbl.setObjectName("titleLbl")
        self.btn_close = QPushButton("X")
        self.btn_close.setFixedWidth(32)
        top.addWidget(self.title_lbl)
        top.addStretch(1)
        top.addWidget(self.btn_close)

        self.code_lbl = QLabel("....")
        self.code_lbl.setObjectName("codeLbl")
        self.code_lbl.setFont(QFont("Segoe UI", 18, QFont.Bold))

        actions = QHBoxLayout()
        self.btn_pin = QPushButton("PIN")
        self.btn_change = QPushButton("تغيير")
        self.btn_change.setObjectName("changeBtn")
        self.btn_show = QPushButton("إظهار")
        self.btn_reload = QPushButton("تحديث")
        actions.addWidget(self.btn_pin)
        actions.addWidget(self.btn_change)
        actions.addWidget(self.btn_show)
        actions.addWidget(self.btn_reload)

        self.hint_lbl = QLabel("تغيير الرقم يعمل نفس منطق الموقع")
        self.hint_lbl.setObjectName("hintLbl")

        card_l.addLayout(top)
        card_l.addWidget(self.code_lbl)
        card_l.addLayout(actions)
        card_l.addWidget(self.hint_lbl)
        root.addWidget(card)

        self.btn_close.clicked.connect(self.close_all)
        self.btn_pin.clicked.connect(self.toggle_pin)
        self.btn_change.clicked.connect(self.change_code)
        self.btn_show.clicked.connect(self.show_browser)
        self.btn_reload.clicked.connect(self.reload_browser)

        self.timer = QTimer(self)
        self.timer.timeout.connect(self.poll_code)
        self.timer.start(2000)

    def set_pin_state(self, pinned: bool):
        self.pinned = pinned
        self.setWindowFlag(Qt.WindowStaysOnTopHint, pinned)
        self.show()
        self.btn_pin.setText("PIN" if pinned else "UNPIN")

    def toggle_pin(self):
        self.set_pin_state(not self.pinned)

    def show_browser(self):
        self.browser.load_admin()
        self.browser.show()
        self.browser.raise_()
        self.browser.activateWindow()
        # avoid focus fighting while logging in
        self.set_pin_state(False)

    def reload_browser(self):
        self.browser.load_admin()
        self.browser.show()
        self.browser.raise_()
        self.browser.activateWindow()
        self.set_pin_state(False)
        self.code_lbl.setText("....")
        self.last_code = ""

    def change_code(self):
        self.browser.run_js(CHANGE_JS)
        self.code_lbl.setText("....")
        self.last_code = ""

    def close_all(self):
        self.timer.stop()
        self.browser.close()
        self.close()
        QApplication.instance().quit()

    def poll_code(self):
        def on_code(result):
            if not result:
                return
            code = str(result).strip()
            m = re.search(r"\d{4,12}", code)
            if not m:
                return
            code = m.group(0)
            if code == self.last_code:
                return
            self.last_code = code
            self.code_lbl.setText(code)
            if not self.first_found:
                self.first_found = True
                self.browser.hide()
                self.set_pin_state(True)
                self.timer.setInterval(8000)

        self.browser.run_js(EXTRACT_JS, on_code)


def main():
    app = QApplication(sys.argv)

    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    storage = os.path.join(appdata, APP_NAME, "qt_profile")
    os.makedirs(storage, exist_ok=True)

    profile = QWebEngineProfile(APP_NAME, app)
    profile.setPersistentCookiesPolicy(QWebEngineProfile.ForcePersistentCookies)
    profile.setPersistentStoragePath(storage)
    profile.setCachePath(os.path.join(storage, "cache"))

    browser = BrowserWindow(profile)
    overlay = OverlayWidget(browser)

    browser.show()
    overlay.show()
    overlay.move(30, 30)

    sys.exit(app.exec())


if __name__ == "__main__":
    main()

