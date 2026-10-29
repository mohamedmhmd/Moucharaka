from django import forms


class DateInput(forms.DateInput):
    input_type = "date"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m-%d")


class MonthInput(forms.DateInput):
    input_type = "month"

    def __init__(self, attrs=None):
        super().__init__(attrs, format="%Y-%m")


class MoughataaSelect(forms.Select):
    """Each option carries its wilaya id so static/js/app.js can filter the
    list when the wilaya changes."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        option = super().create_option(name, value, label, selected, index, subindex, attrs)
        instance = getattr(value, "instance", None)
        if instance is not None:
            option["attrs"]["data-wilaya"] = instance.wilaya_id
        return option


class MoneyInput(forms.NumberInput):
    def __init__(self, attrs=None):
        base = {"step": "1", "min": "0", "inputmode": "numeric", "class": "money"}
        base.update(attrs or {})
        super().__init__(base)
