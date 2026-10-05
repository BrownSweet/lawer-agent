from decimal import ROUND_HALF_UP, Decimal, InvalidOperation


def lawsuit_fee(value: str):
    try:
        amount = Decimal(value)
    except InvalidOperation:
        raise ValueError("金额必须为有限非负数字") from None
    if not amount.is_finite() or amount < 0 or amount > Decimal("1000000000000"):
        raise ValueError("金额必须在 0 至 1 万亿元之间且为有限数字")
    brackets = [
        ("10000", "0", "50"),
        ("100000", ".025", "-200"),
        ("200000", ".02", "300"),
        ("500000", ".015", "1300"),
        ("1000000", ".01", "3800"),
        ("2000000", ".009", "4800"),
        ("5000000", ".008", "6800"),
        ("10000000", ".007", "11800"),
        ("20000000", ".006", "21800"),
        ("1000000000000", ".005", "41800"),
    ]
    for upper, rate, offset in brackets:
        if amount <= Decimal(upper):
            fee = (amount * Decimal(rate) + Decimal(offset)).quantize(Decimal(".01"), ROUND_HALF_UP)
            return {
                "amount": str(amount),
                "fee": str(fee),
                "scope": "普通民事财产案件受理费估算；不含律师费、保全费及其他费用。",
                "rule_source": "诉法法技能包财产案件分段公式",
                "verification": "规则未经本系统现行法核验；减半、减免及具体案类需另行确认。",
            }
