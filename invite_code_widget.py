import json
import os
import threading
import webview


ADMIN_URL = "https://bonuspharma1.pythonanywhere.com/admin"
APP_NAME = "InviteCodeWidget"


OVERLAY_HTML = r"""
<!doctype html>
<html>
  <head>
    <meta charset="utf-8" />
    <style>
      body{
        margin:0;
        background: transparent;
        font-family: "Segoe UI", Tahoma, Arial, sans-serif;
        color:#fff;
        overflow: hidden;
      }
      #wrap{
        width: 100%;
        height: 100%;
        border-radius: 16px;
        padding: 12px 12px 10px 12px;
        background: rgba(10, 20, 35, 0.90);
        border: 1px solid rgba(255,255,255,0.18);
        box-sizing: border-box;
        overflow: hidden;
      }
      #top{
        display:flex;
        align-items:center;
        justify-content:space-between;
        gap:10px;
        margin-bottom: 8px;
      }
      #title{
        font-size: 13px;
        opacity: 0.9;
        letter-spacing: 0.2px;
      }
      #btnClose{
        width: 28px;
        height: 28px;
        border-radius: 10px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.08);
        color: #fff;
        cursor: pointer;
        font-weight: 700;
      }
      #code{
        font-size: 28px;
        font-weight: 900;
        letter-spacing: 0.6px;
        line-height: 1.0;
        text-align: left;
        margin-bottom: 10px;
        user-select: text;
      }
      #actions{
        display:flex;
        gap: 8px;
        justify-content: space-between;
        align-items:center;
        flex-wrap: nowrap;
      }
      .btn{
        border-radius: 12px;
        border: 1px solid rgba(255,255,255,0.18);
        background: rgba(255,255,255,0.10);
        color: #fff;
        cursor: pointer;
        padding: 8px 12px;
        font-weight: 700;
        font-size: 13px;
        user-select: none;
      }
      #btnChange{
        background: rgba(66, 165, 245, 0.22);
        border-color: rgba(66, 165, 245, 0.45);
      }
      #btnShow{
        background: rgba(255, 255, 255, 0.10);
      }
      #hint{
        font-size: 11px;
        opacity: 0.7;
        margin-top: 6px;
      }
    </style>
  </head>
  <body>
    <div id="wrap">
      <div id="top">
        <div id="title">كود الدعوة</div>
        <button id="btnClose" title="Close">X</button>
      </div>
      <div id="code">----</div>
      <div id="actions">
        <button id="btnPin" class="btn">PIN</button>
        <button id="btnChange" class="btn">تغيير</button>
        <button id="btnShow" class="btn">إظهار</button>
        <button id="btnReload" class="btn">تحديث</button>
      </div>
      <div id="hint">تغيير الرقم يعمل من نفس منطق الموقع</div>
    </div>

    <script>
      const api = window.pywebview && window.pywebview.api ? window.pywebview.api : null;

      function safeCall(fn){
        try { if (fn) fn(); } catch (e) {}
      }

      window.__setCode = function(code){
        const el = document.getElementById("code");
        if (!el) return;
        el.textContent = code ? String(code) : "----";
      }

      window.__pinned = true;
      const btnPin = document.getElementById("btnPin");
      function syncPinText(){
        btnPin.textContent = window.__pinned ? "PIN" : "UNPIN";
      }

      btnPin.addEventListener("click", function(){
        window.__pinned = !window.__pinned;
        syncPinText();
        if (api && api.set_pin) safeCall(() => api.set_pin(window.__pinned));
      });

      document.getElementById("btnChange").addEventListener("click", function(){
        if (api && api.change_code) safeCall(() => api.change_code());
      });

      document.getElementById("btnClose").addEventListener("click", function(){
        if (api && api.close_all) safeCall(() => api.close_all());
      });

      document.getElementById("btnShow").addEventListener("click", function(){
        if (api && api.show_browser) safeCall(() => api.show_browser());
      });

      document.getElementById("btnReload").addEventListener("click", function(){
        if (api && api.reload_browser) safeCall(() => api.reload_browser());
      });

      syncPinText();
      window.__setCode("....");
    </script>
  </body>
</html>
"""


SCRAPER_INJECT_JS = r"""
(function () {
  if (window.__inviteWidgetBootstrapped) return;
  window.__inviteWidgetBootstrapped = true;

  const api = window.pywebview && window.pywebview.api ? window.pywebview.api : null;

  function toLatinDigits(s) {
    const map = {
      "٠":"0","١":"1","٢":"2","٣":"3","٤":"4",
      "٥":"5","٦":"6","٧":"7","٨":"8","٩":"9"
    };
    return String(s).replace(/[٠-٩]/g, function (d) { return map[d] || d; });
  }

  function findInviteCode() {
    const textNeedle = /كود\s*الدعوة/i;
    const candidates = [];

    const all = document.querySelectorAll("div,span,label");
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (!el || !el.textContent) continue;
      const t = el.textContent.trim();
      if (!t || !textNeedle.test(t)) continue;

      const container = el.closest("div") || el.parentElement;
      if (!container) continue;

      const digitsEls = container.querySelectorAll("div,span,p");
      let best = "";

      for (let j = 0; j < digitsEls.length; j++) {
        const dEl = digitsEls[j];
        if (!dEl || !dEl.textContent) continue;
        const raw = toLatinDigits(dEl.textContent).trim();
        const m = raw.match(/(\d{4,12})/);
        if (!m) continue;
        const val = m[1];
        if (val.length > best.length) best = val;
      }

      if (best) candidates.push(best);
    }

    if (candidates.length > 0) {
      candidates.sort(function(a,b){ return b.length - a.length; });
      return candidates[0] || "";
    }
    return "";
  }

  function findChangeButton() {
    function norm(s){
      return String(s || "").trim();
    }
    const changeNeedles = [
      "تغيير",
      "تجديد",
      "تحديث",
      "اعادة",
      "إعادة",
      "Refresh",
      "Change",
      "Generate"
    ];
    const copyNeedles = ["نسخ", "Copy"];

    function matchesAny(text, needles){
      for (let i=0;i<needles.length;i++){
        if (text && needles[i] && text.indexOf(needles[i]) !== -1) return true;
      }
      return false;
    }

    // First: try inside the invite-code card/container
    const labelEls = document.querySelectorAll("div,span,label");
    for (let i = 0; i < labelEls.length; i++) {
      const el = labelEls[i];
      if (!el || !el.textContent) continue;
      if (!/كود\s*الدعوة/i.test(el.textContent.trim())) continue;

      const container = el.closest("div") || el.parentElement;
      if (!container) continue;

      const buttons = container.querySelectorAll("button, a");
      for (let j = 0; j < buttons.length; j++) {
        const b = buttons[j];
        if (!b) continue;
        const txt = norm(b.textContent);
        const title = norm(b.getAttribute("title"));
        const aria = norm(b.getAttribute("aria-label"));
        const hay = (txt + " " + title + " " + aria);
        if (matchesAny(hay, copyNeedles)) continue;
        if (matchesAny(hay, changeNeedles)) return b;
      }
    }

    // Second: global fallback
    const buttons2 = document.querySelectorAll("button, a");
    for (let k = 0; k < buttons2.length; k++) {
      const b = buttons2[k];
      if (!b) continue;
      const txt = norm(b.textContent);
      const title = norm(b.getAttribute("title"));
      const aria = norm(b.getAttribute("aria-label"));
      const hay = (txt + " " + title + " " + aria);
      if (matchesAny(hay, copyNeedles)) continue;
      if (matchesAny(hay, changeNeedles)) return b;
    }

    return null;
  }

  window.__doChangeCode = function () {
    const btn = findChangeButton();
    if (btn && typeof btn.click === "function") {
      btn.click();
      return true;
    }
    return false;
  };

  let lastCode = "";
  let firstFound = false;
  let intervalMs = 2000;
  let intervalId = null;

  function tick() {
    try {
      const code = findInviteCode();
      if (code && code !== lastCode) {
        lastCode = code;
        if (api && api.on_code) api.on_code(code);

        if (!firstFound) {
          firstFound = true;
          intervalMs = 8000;
          if (intervalId) clearInterval(intervalId);
          intervalId = setInterval(tick, intervalMs);
        }
      }
    } catch (e) {}
  }

  intervalId = setInterval(tick, intervalMs);
  tick();
})();
"""


class AppApi:
    def __init__(self) -> None:
        self.overlay_win = None
        self.scraper_win = None
        self.lock = threading.Lock()
        self.first_code_hidden = False

    def set_overlay_window(self, win) -> None:
        self.overlay_win = win

    def set_scraper_window(self, win) -> None:
        self.scraper_win = win

    def set_pin(self, pinned: bool) -> bool:
        with self.lock:
            if not self.overlay_win:
                return False
            try:
                self.overlay_win.on_top = bool(pinned)
                return True
            except Exception:
                return False

    def on_code(self, code: str) -> None:
        code = str(code).strip()
        if not code:
            return
        with self.lock:
            try:
                if self.overlay_win:
                    safe_code = json.dumps(code, ensure_ascii=False)
                    self.overlay_win.evaluate_js(f"window.__setCode({safe_code});")
            except Exception:
                pass

            if not self.first_code_hidden:
                self.first_code_hidden = True
                try:
                    if self.scraper_win:
                        self.scraper_win.hide()
                except Exception:
                    pass
                # Once code is available, put widget back on top.
                try:
                    if self.overlay_win:
                        self.overlay_win.on_top = True
                except Exception:
                    pass

    def change_code(self) -> None:
        with self.lock:
            if not self.scraper_win:
                return
            try:
                self.scraper_win.evaluate_js("window.__doChangeCode && window.__doChangeCode();")
            except Exception:
                pass

    def show_browser(self) -> None:
        with self.lock:
            try:
                if self.scraper_win:
                    self.scraper_win.load_url(ADMIN_URL)
                    self.scraper_win.show()
            except Exception:
                pass

    def reload_browser(self) -> None:
        with self.lock:
            try:
                if self.scraper_win:
                    self.scraper_win.load_url(ADMIN_URL)
                    self.scraper_win.show()
            except Exception:
                pass

    def close_all(self) -> None:
        with self.lock:
            try:
                if self.overlay_win:
                    self.overlay_win.destroy()
            except Exception:
                pass
            try:
                if self.scraper_win:
                    self.scraper_win.destroy()
            except Exception:
                pass
        # Ensure the app exits even if pywebview keeps the process alive.
        os._exit(0)


def main() -> None:
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    storage_path = os.path.join(appdata, APP_NAME, "webview_storage")
    os.makedirs(storage_path, exist_ok=True)

    api = AppApi()

    # 1) Scraper window (browser)
    scraper_win = webview.create_window(
        APP_NAME + "_scraper",
        ADMIN_URL,
        js_api=api,
        width=1100,
        height=760,
        resizable=True,
        frameless=False,
        transparent=False,
        easy_drag=False,
        on_top=False,
        shadow=True,
    )
    api.set_scraper_window(scraper_win)

    # 2) Overlay widget (always on top)
    overlay_win = webview.create_window(
        APP_NAME + "_overlay",
        url=None,
        html=OVERLAY_HTML,
        js_api=api,
        width=360,
        height=190,
        resizable=False,
        frameless=False,
        transparent=False,
        easy_drag=True,
        # Keep it NOT on top during login so browser can be clicked.
        on_top=False,
        shadow=True,
    )
    api.set_overlay_window(overlay_win)

    def inject():
        # Retry injection a few times to survive slow loads/navigation
        import time
        try:
            scraper_win.load_url(ADMIN_URL)
        except Exception:
            pass
        payload = (
            "(() => { "
            "if (document.readyState === 'complete' || document.readyState === 'interactive') { "
            "  " + SCRAPER_INJECT_JS.replace("\n", " ") + " "
            "} else { "
            "  document.addEventListener('DOMContentLoaded', function(){ "
            "    " + SCRAPER_INJECT_JS.replace("\n", " ") + " "
            "  });"
            "} })();"
        )
        for _ in range(6):
            try:
                scraper_win.evaluate_js(payload)
            except Exception:
                pass
            time.sleep(1.0)

    webview.start(
        func=inject,
        gui=None,
        debug=False,
        private_mode=False,  # persist cookies/session
        storage_path=storage_path,
        http_server=False,
    )


if __name__ == "__main__":
    main()

