
/* static/android_alert.js */
(function() {
    console.log("StockFlow: Android Alert Script Loaded");

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

    function hasSeenWarning() {
        const dismissed = sessionStorage.getItem('stockflow_android_notice_dismissed') === 'true';
        console.log("StockFlow Debug: Warning dismissed?", dismissed);
        return dismissed;
    }

    function setWarningSeen() {
        sessionStorage.setItem('stockflow_android_notice_dismissed', 'true');
        console.log("StockFlow: Warning marked as seen for this session");
    }

    function createWarningModal() {
        if (document.getElementById('androidWarningOverlay')) return;

        console.log("StockFlow: Creating Warning Modal...");

        const overlay = document.createElement('div');
        overlay.className = 'android-warning-overlay';
        overlay.id = 'androidWarningOverlay';

        overlay.innerHTML = `
            <div class="android-warning-card">
                <div class="android-icon-wrapper">
                    <i class="fab fa-android"></i>
                </div>
                <h2 class="android-warning-title">تنبيه لمستخدمي الأندرويد 📱</h2>
                <p class="android-warning-text">
                    نود إعلامكم بأن الموقع سيتوقف عن العمل قريباً على أجهزة أندرويد . النظام سيكون متاحاً حصرياً من خلال تطبيق 
                    <span class="stockflow-brand">ستوك فلو</span> (Stock Flow) 
                    المخصص لأجهزة الأندرويد لضمان تجربة أسرع وأكثر استقراراً.
                </p>
                <button class="android-warning-btn" id="androidWarningBtn">موافق، استمرار</button>
            </div>
        `;

        document.body.appendChild(overlay);

        const btn = document.getElementById('androidWarningBtn');
        btn.addEventListener('click', function() {
            overlay.classList.remove('show');
            setTimeout(() => {
                overlay.remove();
                setWarningSeen();
            }, 500);
        });

        setTimeout(() => {
            overlay.classList.add('show');
            console.log("StockFlow: Modal Displayed");
        }, 1000);
    }

    function init() {
        console.log("StockFlow: Initializing Android Check...");
        if (isAndroid()) {
            if (!hasSeenWarning()) {
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
                console.log("StockFlow: Alert already dismissed for this session.");
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
