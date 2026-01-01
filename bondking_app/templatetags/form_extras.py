from django import template

register = template.Library()


@register.filter(name="add_class")
def add_class(field, css):
    """
    Usage: {{ field|add_class:"form-control" }}
    """
    existing = field.field.widget.attrs.get("class", "")
    classes = (existing + " " + css).strip()
    return field.as_widget(attrs={"class": classes})

@register.filter
def humanize_step(value):
    if not value:
        return ""
    return value.replace("_", " ").title()
