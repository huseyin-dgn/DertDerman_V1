from django import template

register = template.Library()


@register.simple_tag(takes_context=True)
def page_url(context, number, parameter="page"):
    query = context["request"].GET.copy()
    query[parameter or "page"] = str(number)
    return "?" + query.urlencode()


@register.simple_tag
def page_numbers(page):
    return page.paginator.get_elided_page_range(page.number, on_each_side=1, on_ends=1)
