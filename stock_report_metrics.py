"""Shared, conservative calculations for stock-report quantities.

Stock levels represent whole packages. This module keeps the web report and
the native-app API on exactly the same calculation and rounding rules.
"""

import math


_ARABIC_DIGITS = str.maketrans('٠١٢٣٤٥٦٧٨٩٫', '0123456789.')


def whole_stock_units(value, default=0):
    """Return a non-negative whole-package quantity, rounded half up."""
    if value is None:
        return default

    try:
        normalized = str(value).strip().translate(_ARABIC_DIGITS)
        normalized = normalized.replace(',', '').replace('٬', '').replace('،', '')
        quantity = float(normalized)
        if not math.isfinite(quantity):
            return default
        return max(0, int(math.floor(quantity + 0.5)))
    except (TypeError, ValueError):
        return default


def calculate_stock_metrics(quantities, report_days, target_coverage_days=14):
    """Calculate whole-package movement and a bounded restock suggestion.

    The suggestion replenishes up to 14 days of observed consumption and is
    capped at the consumption in the selected report range.
    """
    whole_quantities = [whole_stock_units(quantity) for quantity in quantities]
    report_days = max(1, int(report_days or 1))

    total_increase = 0
    total_decrease = 0
    for previous, current in zip(whole_quantities, whole_quantities[1:]):
        change = current - previous
        if change > 0:
            total_increase += change
        elif change < 0:
            total_decrease += abs(change)

    current_stock = whole_quantities[-1] if whole_quantities else 0
    daily_consumption = total_decrease / report_days
    target_coverage_days = max(1, int(target_coverage_days or 1))
    target_stock = daily_consumption * target_coverage_days
    calculated_restock = max(0, int(math.ceil(target_stock - current_stock)))

    # If no packages were consumed, no estimate can be trusted. The cap also
    # ensures the suggestion never exceeds the displayed consumption.
    recommended_restock = min(calculated_restock, total_decrease)

    return {
        'quantities': whole_quantities,
        'current_stock': current_stock,
        'total_increase': total_increase,
        'total_decrease': total_decrease,
        'daily_consumption': daily_consumption,
        'target_stock': target_stock,
        'recommended_restock': recommended_restock,
        'target_coverage_days': target_coverage_days,
    }
