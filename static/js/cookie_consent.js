/**
 * Stock Flow — Cookie Consent & 30-Day Retention Notice
 * ═════════════════════════════════════════════════════
 */
(function () {
    'use strict';

    var COOKIE_NAME = 'sf_cookie_consent';
    var RETENTION_DAYS = 30;
    var RETENTION_SECONDS = RETENTION_DAYS * 24 * 60 * 60; // 2,592,000 seconds

    // Ensure CSS is loaded dynamically if missing
    function ensureCSSLoaded() {
        if (!document.querySelector('link[href*="cookie_consent.css"]')) {
            var link = document.createElement('link');
            link.rel = 'stylesheet';
            link.href = '/static/css/cookie_consent.css?v=20260805';
            document.head.appendChild(link);
        }
    }

    function getCookie(name) {
        var match = document.cookie.match(new RegExp('(?:^|;\\s*)' + name + '=([^;]+)'));
        if (match) return match[1];
        return null;
    }

    function setCookie(name, value, seconds) {
        var date = new Date();
        date.setTime(date.getTime() + (seconds * 1000));
        var expires = "; expires=" + date.toUTCString();
        var secure = location.protocol === 'https:' ? '; Secure' : '';
        document.cookie = name + "=" + (value || "") + expires + "; path=/; SameSite=Lax" + secure;
    }

    function isConsentGiven() {
        // Check URL query parameter to force show for testing: ?reset_cookie_consent=1
        if (window.location.search.indexOf('reset_cookie_consent=1') !== -1) {
            return false;
        }

        // Check Cookie
        if (getCookie(COOKIE_NAME) === 'accepted') {
            return true;
        }

        // Fallback check LocalStorage
        try {
            var stored = localStorage.getItem(COOKIE_NAME);
            if (stored) {
                var data = JSON.parse(stored);
                if (data && data.accepted && data.timestamp) {
                    var now = Date.now();
                    var ageInDays = (now - data.timestamp) / (1000 * 60 * 60 * 24);
                    if (ageInDays < RETENTION_DAYS) {
                        return true;
                    }
                }
            }
        } catch (e) {}

        return false;
    }

    function saveConsent() {
        setCookie(COOKIE_NAME, 'accepted', RETENTION_SECONDS);
        try {
            localStorage.setItem(COOKIE_NAME, JSON.stringify({
                accepted: true,
                timestamp: Date.now()
            }));
        } catch (e) {}
    }

    function renderBanner() {
        ensureCSSLoaded();

        if (isConsentGiven()) return;

        // Prevent duplicate rendering
        if (document.getElementById('sfCookieBanner')) return;

        var wrapper = document.createElement('div');
        wrapper.className = 'sf-cookie-banner-wrapper';
        wrapper.id = 'sfCookieBanner';

        var checkSvg = '<svg width="18" height="18" viewBox="0 0 24 24" fill="none" stroke="currentColor" stroke-width="3" stroke-linecap="round" stroke-linejoin="round"><polyline points="20 6 9 17 4 12"></polyline></svg>';

        wrapper.innerHTML = [
            '<div class="sf-cookie-card">',
            '  <div class="sf-cookie-header">',
            '    <div class="sf-cookie-icon-box">🍪</div>',
            '    <h4 class="sf-cookie-title">إشعار ملفات تعريف الارتباط (الكوكيز)</h4>',
            '  </div>',
            '  <p class="sf-cookie-body">',
            '    نحن نستخدم الكوكيز لضمان استمرار تسجيل دخولك بأمان وحفظ تفضيلاتك لمدة <span class="sf-cookie-highlight">30 يوماً</span>. باستمرارك في استخدام المنصة، فإنك توافق على سياسة الاحتفاظ بالكوكيز.',
            '  </p>',
            '  <div class="sf-cookie-actions">',
            '    <button id="sfAcceptCookiesBtn" class="sf-cookie-btn-accept">',
            '      ' + checkSvg + ' <span>موافق واستمرار</span>',
            '    </button>',
            '    <a href="/privacy-policy" class="sf-cookie-btn-policy">سياسة الخصوصية</a>',
            '  </div>',
            '</div>'
        ].join('');

        document.body.appendChild(wrapper);

        // Trigger smooth entrance animation
        setTimeout(function () {
            wrapper.classList.add('sf-show');
        }, 300);

        var acceptBtn = document.getElementById('sfAcceptCookiesBtn');
        if (acceptBtn) {
            acceptBtn.addEventListener('click', function () {
                saveConsent();
                wrapper.classList.remove('sf-show');
                setTimeout(function () {
                    if (wrapper.parentNode) {
                        wrapper.parentNode.removeChild(wrapper);
                    }
                }, 400);
            });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', renderBanner);
    } else {
        renderBanner();
    }
})();
