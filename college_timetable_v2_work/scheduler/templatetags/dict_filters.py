from django import template

register = template.Library()

@register.filter
def dict_key(d, key):
    try:
        return d[key]
    except (KeyError, TypeError):
        return None

# Alias so templates can use either name
@register.filter
def get_item(d, key):
    try:
        return d[key]
    except (KeyError, TypeError):
        return None

@register.filter
def dict_get(d, key):
    """Return d[key], used as {{ mydict|dict_get:key }}"""
    try:
        return d[key]
    except (KeyError, TypeError):
        return {}
