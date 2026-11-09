import re

from django import forms

from .models import CategoriaActividad

_INPUT = 'input input-bordered w-full'
COLOR = re.compile(r'^#[0-9a-fA-F]{6}$')


class CategoriaForm(forms.ModelForm):
    class Meta:
        model = CategoriaActividad
        fields = ['etiqueta', 'codigo', 'color', 'orden', 'activa']
        widgets = {
            'etiqueta': forms.TextInput(attrs={'class': _INPUT}),
            'codigo': forms.TextInput(attrs={'class': _INPUT}),
            'color': forms.TextInput(attrs={'class': _INPUT, 'type': 'color'}),
            'orden': forms.NumberInput(attrs={'class': _INPUT}),
            'activa': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        if self.instance.pk:                      # el código es la llave de las estadísticas: no cambia
            self.fields['codigo'].disabled = True

    def clean_color(self):
        c = self.cleaned_data['color']
        if not COLOR.match(c):
            raise forms.ValidationError('Usa un color hexadecimal (#rrggbb).')
        return c.lower()

    def clean_codigo(self):
        c = self.cleaned_data['codigo']
        if not self.instance.pk and CategoriaActividad.objects.filter(empresa=self.empresa, codigo=c).exists():
            raise forms.ValidationError('Ya existe una categoría con ese código.')
        return c

    def clean_activa(self):
        activa = self.cleaned_data['activa']
        if self.instance.pk and self.instance.protegida and self.instance.codigo == 'otros' and not activa:
            raise forms.ValidationError('«Otros» no se puede desactivar: es donde cae lo que no coincide con nada.')
        return activa

    def save(self, commit=True):
        self.instance.empresa = self.empresa
        return super().save(commit)
