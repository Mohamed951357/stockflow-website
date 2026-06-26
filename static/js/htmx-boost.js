/*
 * StockFlow legacy HTMX boost kill switch.
 *
 * The app uses independent full-page templates with page-specific inline styles
 * and scripts. Global body swaps caused a short broken layout flash on mobile,
 * so boosted navigation is intentionally disabled.
 */
(function () {
    "use strict";

    function disableBoost() {
        if (!document.body) return;

        document.body.removeAttribute("hx-boost");
        document.body.removeAttribute("data-hx-boost");
        document.body.removeAttribute("hx-target");
        document.body.removeAttribute("data-hx-target");
        document.body.removeAttribute("hx-swap");
        document.body.removeAttribute("data-hx-swap");
    }

    if (document.readyState === "loading") {
        document.addEventListener("DOMContentLoaded", disableBoost, { once: true });
    } else {
        disableBoost();
    }
})();
