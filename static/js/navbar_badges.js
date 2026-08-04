(function () {
    'use strict';

    function setBadge(selector, count) {
        document.querySelectorAll(selector).forEach(function (badge) {
            if (count > 0) {
                badge.textContent = count;
                badge.classList.remove('d-none');
                badge.style.display = 'inline-flex';
            } else {
                badge.classList.add('d-none');
                badge.style.display = 'none';
            }
        });
    }

    function updateNavbarBadges(data, communityNotificationsCount) {
        var notificationsCount = Number(data.unread_notifications_count) || 0;
        var privateMessagesCount = Number(data.unread_private_messages_count) || 0;
        var totalNotificationsCount = notificationsCount + (Number(communityNotificationsCount) || 0);

        setBadge('.navbar .nav-link[href*="/notifications"] .notification-badge', totalNotificationsCount);
        setBadge('.navbar .nav-link[href*="/company/messages"] .notification-badge', privateMessagesCount);
    }

    function refreshNavbarBadges() {
        fetch('/api/unread_counts', { credentials: 'same-origin' })
            .then(function (response) {
                if (!response.ok) throw new Error('Could not load unread counts');
                return response.json();
            })
            .then(function (data) {
                return fetch('/community_bonus/get_notification_count', { credentials: 'same-origin' })
                    .then(function (response) { return response.json(); })
                    .then(function (communityData) {
                        updateNavbarBadges(data, communityData && communityData.count);
                    })
                    .catch(function () {
                        updateNavbarBadges(data, 0);
                    });
            })
            .catch(function () {});
    }

    refreshNavbarBadges();
    window.setInterval(refreshNavbarBadges, 15000);
})();
