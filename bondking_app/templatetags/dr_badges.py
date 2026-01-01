from django import template

register = template.Library()

@register.filter
def payment_badge(status):
    if not status:
        return "bg-secondary"

    return {
        # Neutral / not applicable
        "NA": "bg-secondary",

        # Accounting preparation
        "FOR_COUNTER_CREATION": "bg-warning text-dark",
        "FOR_COUNTERING": "bg-warning text-dark",

        # Counter prepared
        "COUNTERED": "bg-info text-dark",

        # Collection phase
        "FOR_COLLECTION": "bg-primary",

        # Deposit phase
        "FOR_DEPOSIT": "bg-primary",

        # Finalized
        "DEPOSITED": "bg-success",
    }.get(status, "bg-secondary")



@register.filter
def delivery_badge(status):
    return {
        "NEW_DR": "bg-primary",
        "FOR_DELIVERY": "bg-info text-dark",
        "DELIVERED": "bg-success",
        "FOR_COUNTER_CREATION": "bg-warning text-dark",
        "FOR_COUNTERING": "bg-warning text-dark",
        "COUNTERED": "bg-secondary",
        "FOR_COLLECTION": "bg-info text-dark",
        "FOR_DEPOSIT": "bg-info text-dark",
        "DEPOSITED": "bg-success",
    }.get(status, "bg-secondary")
