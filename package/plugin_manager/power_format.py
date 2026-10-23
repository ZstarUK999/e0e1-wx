"""Display power compactly while keeping raw values for ordering."""
import math


def format_power(value):
    try:
        number=float(value)
    except (ValueError,TypeError):
        return '—'
    if not math.isfinite(number):return '—'
    if abs(number)>=100000000:
        return f'{number/100000000:.2f}'.rstrip('0').rstrip('.')+'亿'
    if abs(number)>=10000:
        return f'{number/10000:.2f}'.rstrip('0').rstrip('.')+'万'
    return f'{number:g}'
