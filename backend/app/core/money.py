def paise_to_display(paise: int) -> str:
    """Format integer paise as a rupee display string, e.g. 27500 -> '₹275.00'."""
    rupees = paise / 100
    return f"₹{rupees:,.2f}"
