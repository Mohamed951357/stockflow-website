(function () {
    'use strict';

    var deferredInstallPrompt = null;
    var promptId = 'stockflowPwaInstallPrompt';
    var dismissedKey = 'stockflow:pwa-install-dismissed-at';
    var dismissedTtl = 3 * 24 * 60 * 60 * 1000;
    var promptDelay = 700;

    function storageGet(key) {
        try {
            return window.localStorage.getItem(key);
        } catch (err) {
            return null;
        }
    }

    function storageSet(key, value) {
        try {
            window.localStorage.setItem(key, value);
        } catch (err) {}
    }

    function isStandalone() {
        return window.navigator.standalone === true ||
            window.matchMedia('(display-mode: standalone)').matches;
    }

    function isDesktop() {
        var ua = window.navigator.userAgent || '';
        return !/Android|webOS|iPhone|iPad|iPod|BlackBerry|IEMobile|Opera Mini/i.test(ua);
    }

    function wasRecentlyDismissed() {
        var dismissedAt = Number(storageGet(dismissedKey) || 0);
        return dismissedAt > 0 && Date.now() - dismissedAt < dismissedTtl;
    }

    function canRegisterServiceWorker() {
        if (!('serviceWorker' in navigator)) {
            return false;
        }

        return window.isSecureContext ||
            window.location.protocol === 'https:' ||
            /^(localhost|127\.0\.0\.1|\[::1\])$/.test(window.location.hostname);
    }

    function registerServiceWorker() {
        if (!canRegisterServiceWorker()) {
            return;
        }

        window.addEventListener('load', function () {
            navigator.serviceWorker.register('/service-worker.js').catch(function (error) {
                if (window.console && console.warn) {
                    console.warn('StockFlow service worker registration failed:', error);
                }
            });
        });
    }

    function ensurePromptElement() {
        var existing = document.getElementById(promptId);
        if (existing) {
            return existing;
        }

        if (!document.body) {
            return null;
        }

        var prompt = document.createElement('aside');
        prompt.id = promptId;
        prompt.className = 'stockflow-pwa-install';
        prompt.setAttribute('role', 'dialog');
        prompt.setAttribute('aria-live', 'polite');
        prompt.setAttribute('aria-label', 'تثبيت StockFlow على الكمبيوتر');
        prompt.innerHTML = [
            '<div class="stockflow-pwa-install__panel">',
            '  <div class="stockflow-pwa-install__icon" aria-hidden="true"><i class="fas fa-download"></i></div>',
            '  <div class="stockflow-pwa-install__content">',
            '    <p class="stockflow-pwa-install__title">ثبّت StockFlow على الكمبيوتر</p>',
            '    <p class="stockflow-pwa-install__text">افتحه من سطح المكتب أو قائمة Start بسرعة ومن غير ما تدور على الرابط.</p>',
            '  </div>',
            '  <div class="stockflow-pwa-install__actions">',
            '    <button type="button" class="stockflow-pwa-install__button" data-pwa-install>',
            '      <i class="fas fa-check-circle" aria-hidden="true"></i><span>تثبيت الآن</span>',
            '    </button>',
            '    <button type="button" class="stockflow-pwa-install__dismiss" data-pwa-dismiss>لاحقاً</button>',
            '  </div>',
            '</div>'
        ].join('');

        document.body.appendChild(prompt);

        var installButton = prompt.querySelector('[data-pwa-install]');
        var dismissButton = prompt.querySelector('[data-pwa-dismiss]');

        if (installButton) {
            installButton.addEventListener('click', startInstall);
        }

        if (dismissButton) {
            dismissButton.addEventListener('click', function () {
                hidePrompt(true);
            });
        }

        return prompt;
    }

    function showPrompt() {
        if (!deferredInstallPrompt || isStandalone() || !isDesktop() || wasRecentlyDismissed()) {
            return;
        }

        var prompt = ensurePromptElement();
        if (!prompt) {
            return;
        }

        window.requestAnimationFrame(function () {
            prompt.classList.add('is-visible');
        });
    }

    function hidePrompt(markDismissed) {
        var prompt = document.getElementById(promptId);
        if (prompt) {
            prompt.classList.remove('is-visible');
        }

        if (markDismissed) {
            storageSet(dismissedKey, String(Date.now()));
        }
    }

    function restoreInstallButton(button) {
        if (!button) {
            return;
        }

        button.disabled = false;
        button.innerHTML = '<i class="fas fa-check-circle" aria-hidden="true"></i><span>تثبيت الآن</span>';
    }

    function startInstall() {
        var prompt = deferredInstallPrompt;
        var installButton = document.querySelector('#' + promptId + ' [data-pwa-install]');

        if (!prompt) {
            hidePrompt(false);
            return;
        }

        if (installButton) {
            installButton.disabled = true;
            installButton.innerHTML = '<i class="fas fa-spinner fa-spin" aria-hidden="true"></i><span>جاري الفتح...</span>';
        }

        prompt.prompt();
        prompt.userChoice
            .then(function (choice) {
                if (choice && choice.outcome === 'accepted') {
                    hidePrompt(false);
                } else {
                    hidePrompt(true);
                }
            })
            .catch(function () {
                restoreInstallButton(installButton);
            })
            .finally(function () {
                deferredInstallPrompt = null;
                restoreInstallButton(installButton);
            });
    }

    registerServiceWorker();

    window.addEventListener('beforeinstallprompt', function (event) {
        if (!isDesktop() || isStandalone()) {
            return;
        }

        event.preventDefault();
        deferredInstallPrompt = event;

        window.setTimeout(function () {
            if (document.readyState === 'loading') {
                document.addEventListener('DOMContentLoaded', showPrompt, { once: true });
            } else {
                showPrompt();
            }
        }, promptDelay);
    });

    window.addEventListener('appinstalled', function () {
        hidePrompt(false);
        deferredInstallPrompt = null;
    });

    window.StockFlowPWAInstall = {
        show: showPrompt,
        install: startInstall,
        ready: function () {
            return Boolean(deferredInstallPrompt);
        }
    };
})();
