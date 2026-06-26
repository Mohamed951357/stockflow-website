import json
import os
import re
import threading
import webview


ADMIN_URL = "https://bonuspharma1.pythonanywhere.com/admin"
APP_NAME = "InviteCodeFloat"


HTML_OVERLAY_INJECT = r"""
(function () {
  const OVERLAY_ID = "inviteOverlay";
  const PIN_ID = "invitePinBtn";
  const VALUE_ID = "inviteValue";
  const CLOSE_ID = "inviteCloseBtn";
  const CHANGE_ID = "inviteChangeBtn";

  function ensureOverlay() {
    if (document.getElementById(OVERLAY_ID)) return;

    const overlay = document.createElement("div");
    overlay.id = OVERLAY_ID;
    overlay.style.position = "fixed";
    overlay.style.top = "10px";
    overlay.style.left = "10px";
    overlay.style.zIndex = "2147483647";
    overlay.style.background = "rgba(10, 20, 35, 0.88)";
    overlay.style.color = "white";
    overlay.style.border = "1px solid rgba(255,255,255,0.18)";
    overlay.style.borderRadius = "14px";
    overlay.style.padding = "12px 12px";
    overlay.style.width = "330px";
    overlay.style.height = "105px";
    overlay.style.display = "flex";
    overlay.style.flexDirection = "column";
    overlay.style.alignItems = "flex-start";
    overlay.style.justifyContent = "space-between";
    overlay.style.userSelect = "none";

    const header = document.createElement("div");
    header.style.display = "flex";
    header.style.alignItems = "center";
    header.style.justifyContent = "space-between";
    header.style.width = "100%";

    const label = document.createElement("div");
    label.textContent = "كود الدعوة";
    label.style.fontSize = "13px";
    label.style.opacity = "0.9";

    const closeBtn = document.createElement("button");
    closeBtn.id = CLOSE_ID;
    closeBtn.textContent = "X";
    closeBtn.style.cursor = "pointer";
    closeBtn.style.border = "1px solid rgba(255,255,255,0.18)";
    closeBtn.style.background = "rgba(255,255,255,0.08)";
    closeBtn.style.color = "white";
    closeBtn.style.width = "28px";
    closeBtn.style.height = "28px";
    closeBtn.style.borderRadius = "999px";
    closeBtn.style.fontSize = "13px";
    closeBtn.style.pointerEvents = "auto";

    const pinBtn = document.createElement("button");
    pinBtn.id = PIN_ID;
    pinBtn.textContent = "PIN";
    pinBtn.style.cursor = "pointer";
    pinBtn.style.border = "1px solid rgba(255,255,255,0.18)";
    pinBtn.style.background = "rgba(255,255,255,0.10)";
    pinBtn.style.color = "white";
    pinBtn.style.padding = "6px 10px";
    pinBtn.style.borderRadius = "999px";
    pinBtn.style.fontSize = "12px";
    pinBtn.style.pointerEvents = "auto";

    const changeBtn = document.createElement("button");
    changeBtn.id = CHANGE_ID;
    changeBtn.textContent = "تغيير";
    changeBtn.style.cursor = "pointer";
    changeBtn.style.border = "1px solid rgba(66, 165, 245, 0.45)";
    changeBtn.style.background = "rgba(66, 165, 245, 0.22)";
    changeBtn.style.color = "white";
    changeBtn.style.padding = "6px 12px";
    changeBtn.style.borderRadius = "999px";
    changeBtn.style.fontSize = "12px";
    changeBtn.style.pointerEvents = "auto";

    closeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.close_overlay) {
          window.pywebview.api.close_overlay();
        }
      } catch (err) {}
    });

    pinBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      // toggle pinned state
      window.__invitePinned = !window.__invitePinned;
      try {
        if (window.pywebview && window.pywebview.api && window.pywebview.api.set_pin) {
          window.pywebview.api.set_pin(window.__invitePinned);
        }
      } catch (err) {}
      pinBtn.textContent = window.__invitePinned ? "PIN" : "UNPIN";
    });

    changeBtn.addEventListener("click", function (e) {
      e.stopPropagation();
      try {
        if (typeof window.__doChangeInviteCode === "function") {
          // Force next tick to accept the updated code.
          lastCode = "";
          window.__doChangeInviteCode();
          const v = document.getElementById(VALUE_ID);
          if (v) v.textContent = "....";
        }
      } catch (err) {}
    });

    const value = document.createElement("div");
    value.id = VALUE_ID;
    value.textContent = "----";
    value.style.fontSize = "28px";
    value.style.fontWeight = "700";
    value.style.letterSpacing = "0.5px";
    value.style.pointerEvents = "auto";

    overlay.appendChild(header);
    header.appendChild(label);
    header.appendChild(closeBtn);

    overlay.appendChild(value);

    const actions = document.createElement("div");
    actions.style.display = "flex";
    actions.style.gap = "10px";
    actions.style.alignItems = "center";
    actions.style.justifyContent = "flex-end";
    actions.style.width = "100%";

    actions.appendChild(pinBtn);
    actions.appendChild(changeBtn);
    overlay.appendChild(actions);

    document.body.appendChild(overlay);
  }

  function toLatinDigits(s) {
    // Convert Arabic-Indic digits to Latin digits if needed
    const map = {
      "٠": "0", "١": "1", "٢": "2", "٣": "3", "٤": "4",
      "٥": "5", "٦": "6", "٧": "7", "٨": "8", "٩": "9"
    };
    return String(s).replace(/[٠-٩]/g, function (d) { return map[d] || d; });
  }

  function findInviteCode() {
    const textNeedle = /كود\s*الدعوة/i;

    const candidates = [];
    // Narrow scan to reduce DOM work
    const all = document.querySelectorAll("div,span,label");
    for (let i = 0; i < all.length; i++) {
      const el = all[i];
      if (!el || !el.textContent) continue;
      const t = el.textContent.trim();
      if (!t) continue;
      if (!textNeedle.test(t)) continue;
      // label element found; locate nearest container
      const container = el.closest("div") || el.parentElement;
      if (!container) continue;
      const digitsEls = container.querySelectorAll("div,span,p");
      let best = "";
      for (let j = 0; j < digitsEls.length; j++) {
        const dEl = digitsEls[j];
        if (!dEl || !dEl.textContent) continue;
        const raw = toLatinDigits(dEl.textContent).trim();
        if (!raw) continue;
        // Extract a plausible invite code even if surrounded by extra chars/spaces
        const m = raw.match(/(\d{4,12})/);
        if (!m) continue;
        const val = m[1];
        // Pick the longest (usually the invite code is longer)
        if (val.length > best.length) best = val;
      }
      if (best) candidates.push(best);
    }

    if (candidates.length > 0) {
      // Return max length among candidates
      candidates.sort(function(a,b){ return b.length - a.length; });
      return candidates[0];
    }
    return "";
  }

  function findChangeButton() {
    function norm(s) {
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

    function matchesAny(text, needles) {
      for (let i = 0; i < needles.length; i++) {
        if (text && needles[i] && text.indexOf(needles[i]) !== -1) return true;
      }
      return false;
    }

    // Prefer buttons inside the invite-code card
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
        const txt = norm(b.textContent);
        const title = norm(b.getAttribute("title"));
        const aria = norm(b.getAttribute("aria-label"));
        const hay = (txt + " " + title + " " + aria);
        if (matchesAny(hay, copyNeedles)) continue;
        if (matchesAny(hay, changeNeedles)) return b;
      }
    }

    // Fallback: scan the page
    const allButtons = document.querySelectorAll("button, a");
    for (let k = 0; k < allButtons.length; k++) {
      const b = allButtons[k];
      const txt = norm(b.textContent);
      const title = norm(b.getAttribute("title"));
      const aria = norm(b.getAttribute("aria-label"));
      const hay = (txt + " " + title + " " + aria);
      if (matchesAny(hay, copyNeedles)) continue;
      if (matchesAny(hay, changeNeedles)) return b;
    }

    return null;
  }

  window.__doChangeInviteCode = function () {
    const btn = findChangeButton();
    if (btn && typeof btn.click === "function") {
      btn.click();
      return true;
    }
    return false;
  };

  function setInviteOverlayCode(code) {
    const valueEl = document.getElementById("inviteValue");
    if (!valueEl) return;
    if (!code) return;
    valueEl.textContent = code;
  }

  window.__invitePinned = true;
  ensureOverlay();
  // Show a hint if not logged in yet
  setInviteOverlayCode("....");

  let lastCode = "";
  let firstFound = false;
  let intervalMs = 2000;
  let intervalId = null;
  function tick() {
    try {
      ensureOverlay();
      const code = findInviteCode();
      if (code && code !== lastCode) {
        lastCode = code;
        setInviteOverlayCode(code);
        // Tell python: we got a code now (login success)
        try {
          if (window.pywebview && window.pywebview.api && window.pywebview.api.on_code) {
            window.pywebview.api.on_code(code);
          }
        } catch (err) {}

        if (!firstFound) {
          firstFound = true;
          intervalMs = 10000; // slow down after login/code is stable
          if (intervalId) clearInterval(intervalId);
          intervalId = setInterval(tick, intervalMs);
        }
      }
    } catch (e) {}
  }

  // Poll like the website updates
  intervalId = setInterval(tick, intervalMs);
  // Run fast on first load
  tick();
})();
"""


class Api:
    def __init__(self) -> None:
        self.window = None
        self.shrunk = False
        self.lock = threading.Lock()

    def set_window(self, win) -> None:
        self.window = win

    def set_pin(self, pinned: bool) -> bool:
        with self.lock:
            if self.window is None:
                return False
            try:
                self.window.on_top = bool(pinned)
                return True
            except Exception:
                return False

    def on_code(self, code: str) -> None:
        # When code is detected we shrink to "floating" size.
        with self.lock:
            if self.shrunk:
                return
            self.shrunk = True
            if self.window is None:
                return
            try:
                self.window.set_window_size(360, 140)
            except Exception:
                pass

    def close_overlay(self) -> None:
        with self.lock:
            try:
                if self.window is not None:
                    self.window.destroy()
            except Exception:
                pass
        os._exit(0)


def main() -> None:
    # Use stable per-user folder so cookies/session survive across EXE runs.
    appdata = os.environ.get("APPDATA") or os.path.expanduser("~")
    storage_path = os.path.join(appdata, APP_NAME, "webview_storage")
    os.makedirs(storage_path, exist_ok=True)

    api = Api()

    # Start larger so login fields are usable if the user isn't logged in yet.
    win = webview.create_window(
        APP_NAME,
        ADMIN_URL,
        js_api=api,
        width=1000,
        height=720,
        resizable=True,
        frameless=False,
        transparent=False,
        easy_drag=False,
        on_top=True,
        shadow=False,
    )
    api.set_window(win)

    # Inject overlay logic once the page is up.
    # We do it a bit later to reduce timing issues.
    def inject_overlay() -> None:
        # Retry injection a few times to survive slow loads/navigation.
        for _ in range(5):
            try:
                win.evaluate_js(HTML_OVERLAY_INJECT)
            except Exception:
                pass
            # short sleep in background thread; webview.start calls this func
            import time
            time.sleep(1.0)

    webview.start(
        func=inject_overlay,
        gui=None,
        debug=False,
        private_mode=False,  # so cookies survive between runs
        storage_path=storage_path,
        http_server=False,
    )


if __name__ == "__main__":
    main()

