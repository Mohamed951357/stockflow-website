
/* static/android_alert.js */
(function() {
    console.log("StockFlow: Android Alert Script Loaded");

    // رابط التطبيق على جوجل بلاي - عدّله بالرابط الفعلي
    const PLAY_STORE_URL = "https://play.google.com/store/apps/details?id=com.stockflow.app";

    function isAndroid() {
        const ua = navigator.userAgent.toLowerCase();
        const isAndroidUA = /android/i.test(ua);
        const isAndroidPlatform = (navigator.platform && /android/i.test(navigator.platform.toLowerCase()));
        
        // التحقق من وضع الاختبار عبر الرابط ?test_android=1
        const urlParams = new URLSearchParams(window.location.search);
        const isTestMode = urlParams.get('test_android') === '1';

        console.log("StockFlow Debug:", {
            userAgent: ua,
            isAndroidUA: isAndroidUA,
            isAndroidPlatform: isAndroidPlatform,
            isTestMode: isTestMode
        });

        return isAndroidUA || isAndroidPlatform || isTestMode;
    }

    function createWarningModal() {
        // إزالة أي modal موجود مسبقاً قبل إنشاء واحد جديد
        const existing = document.getElementById('androidWarningOverlay');
        if (existing) existing.remove();

        console.log("StockFlow: Creating Warning Modal...");

        const overlay = document.createElement('div');
        overlay.className = 'android-warning-overlay';
        overlay.id = 'androidWarningOverlay';

        overlay.innerHTML = `
            <div class="android-warning-card">
                <button class="android-close-btn" id="androidCloseBtn" aria-label="إغلاق">&#10005;</button>
                <div class="android-icon-wrapper">
                    <i class="fab fa-android"></i>
                </div>
                <h2 class="android-warning-title">تنبيه لمستخدمي الأندرويد 📱</h2>
                <p class="android-warning-text">
                    الموقع سيتوقف قريباً على الأندرويد.<br>
                    حمّل تطبيق <span class="stockflow-brand">ستوك فلو</span> للاستمرار بتجربة أفضل.
                </p>
                <a class="android-warning-btn" id="androidPlayStoreBtn" href="${PLAY_STORE_URL}" target="_blank" rel="noopener noreferrer">
                    <i class="fab fa-google-play"></i> تحميل من جوجل بلاي
                </a>
            </div>
        `;

        document.body.appendChild(overlay);

        // زرار الإغلاق (X) - يخفي الرسالة فقط مؤقتاً
        const closeBtn = document.getElementById('androidCloseBtn');
        closeBtn.addEventListener('click', function() {
            overlay.classList.remove('show');
            setTimeout(() => overlay.remove(), 500);
        });

        setTimeout(() => {
            overlay.classList.add('show');
            console.log("StockFlow: Modal Displayed");
        }, 1000);
    }

    function init() {
        console.log("StockFlow: Initializing Android Check...");
        if (isAndroid()) {
            if (!document.querySelector('link[href*="font-awesome"]') && !document.querySelector('link[href*="all.min.css"]')) {
                console.log("StockFlow: Injecting FontAwesome...");
                const fa = document.createElement('link');
                fa.rel = 'stylesheet';
                fa.href = 'https://cdnjs.cloudflare.com/ajax/libs/font-awesome/6.4.2/css/all.min.css';
                document.head.appendChild(fa);
            }

            if (document.body) {
                createWarningModal();
            } else {
                document.addEventListener('DOMContentLoaded', createWarningModal);
            }
        } else {
            console.log("StockFlow: Not an Android device (and not in test mode).");
        }
    }

    if (document.readyState === 'loading') {
        document.addEventListener('DOMContentLoaded', init);
    } else {
        init();
    }
})();
