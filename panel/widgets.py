"""Widgets de la marca de la empresa: logos con miniatura y colores con muestra + selector."""
from django import forms


class ImagenWidget(forms.ClearableFileInput):
    """Archivo de imagen con su miniatura actual. `oscuro=True` la pinta sobre fondo oscuro (logo del tema oscuro)."""
    template_name = 'panel/widgets/imagen.html'

    def __init__(self, *args, oscuro=False, pequena=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.oscuro, self.pequena = oscuro, pequena

    def get_context(self, name, value, attrs):
        ctx = super().get_context(name, value, attrs)
        ctx['widget'].update({'oscuro': self.oscuro, 'pequena': self.pequena})
        return ctx


class ColorWidget(forms.TextInput):
    """Texto #RRGGBB junto a un selector de color nativo. static/js/campo-color.js los mantiene sincronizados."""
    template_name = 'panel/widgets/color.html'

    def __init__(self, attrs=None):
        super().__init__({'placeholder': '#RRGGBB', 'maxlength': '7', 'autocomplete': 'off', **(attrs or {})})
