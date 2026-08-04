(function() {
    const PLAY_STORE_URL = 'https://play.google.com/store/apps/details?id=com.mnagy.stockflowapp&pcampaignid=web_share';

    function isAndroid() {
        const ua = navigator.userAgent.toLowerCase();
        const isAndroidUA = /android/i.test(ua);
        const isAndroidPlatform = navigator.platform && /android/i.test(navigator.platform.toLowerCase());
        const urlParams = new URLSearchParams(window.location.search);
        const isTestMode = urlParams.get('test_android') === '1';

        return isAndroidUA || isAndroidPlatform || isTestMode;
    }

    function ensureFontAwesome() {
        if (document.querySelector('link[href*="font-awesome"]') || document.querySelector('link[href*="all.min.css"]')) {
            return;
        }

        const fa = document.createElement('link');
        fa.rel = 'stylesheet';
        fa.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css';
        document.head.appendChild(fa);
    }

    function closeWarning(overlay) {
        overlay.classList.remove('show');
        setTimeout(() => overlay.remove(), 300);
    }

    function createWarningModal() {
        if (document.getElementById('androidWarningOverlay')) {
            return;
        }

        const overlay = document.createElement('div');
        overlay.className = 'android-warning-overlay';
        overlay.id = 'androidWarningOverlay';
        overlay.innerHTML = `
            <div class="android-warning-card" role="dialog" aria-modal="true" aria-labelledby="androidWarningTitle">
                <button type="button" class="android-warning-close" id="androidWarningClose" aria-label="إغلاق">×</button>
                <div class="android-icon-wrapper">
                    <i class="fab fa-android" aria-hidden="true"></i>
                </div>
                <h2 class="android-warning-title" id="androidWarningTitle">تنبيه لمستخدمي الأندرويد</h2>
                <p class="android-warning-text">
                    قريبًا هيكون استخدام <span class="stockflow-brand">ستوك فلو</span> على الأندرويد من خلال التطبيق فقط.
                    حمّل التطبيق من جوجل بلاي لأفضل تجربة.
                </p>
                <a class="android-warning-btn" id="androidWarningBtn" href="${PLAY_STORE_URL}" target="_blank" rel="noopener noreferrer">
                    تحميل التطبيق من جوجل بلاي
                </a>
            </div>
        `;

        document.body.appendChild(overlay);

        const closeBtn = document.getElementById('androidWarningClose');
        const playStoreBtn = document.getElementById('androidWarningBtn');

        closeBtn.addEventListener('click', function() {
            closeWarning(overlay);
        });

        playStoreBtn.addEventListener('click', function() {
            closeWarning(overlay);
        });

        setTimeout(() => {
            overlay.classList.add('show');
        }, 300);
    }

    function init() {
        if (!isAndroid()) {
            return;
        }

        ensureFontAwesome();

        if (document.body) {
            createWarningModal();
        } else {
            document.addEventListener('DOMContentLoaded', createWarningModal, { once: true });
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init, { once: true });
    } else {
        init();
    }
})();
