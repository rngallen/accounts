from datetime import timedelta

from django.urls import reverse_lazy
from django.utils import timezone


def delay_reverse_lazy(viewname, query_params=""):
    def _delay_reverse_lazy():
        return reverse_lazy(viewname) + ("?" + query_params if query_params else "")
    return _delay_reverse_lazy


def get_index_of_object_in_queryset(queryset, obj, key):
    try:
        for i, o in enumerate(queryset):
            if getattr(o, key) == getattr(obj, key):
                return i
    except:
        pass


def input_dropdown_widget_attrs_config(app_name, fields):
    configs = {}
    for field in fields:
        configs[field] = {
            "data-new": "#new-" + field,
            "data-load-url": delay_reverse_lazy(app_name + ":load_options", "field=" + field),
            "data-validation-url": delay_reverse_lazy(app_name + ":validate_choice", "field=" + field)
        }
    return configs