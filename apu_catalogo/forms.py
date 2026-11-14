from django import forms

from .models import PerfilCalculo

INPUT = 'input input-bordered input-sm w-full'
MODOS = [('HALF_UP', 'Hacia arriba desde la mitad (0,5 → 1)'), ('HALF_EVEN', 'Al par más cercano (0,5 → 0)')]


class PerfilDatosForm(forms.Form):
    """Datos generales de un perfil: nombre, país, moneda y redondeo. Las líneas las maneja `editor.py`."""
    nombre = forms.CharField(label='Nombre', max_length=100, widget=forms.TextInput(attrs={'class': INPUT}))
    pais = forms.CharField(label='País', max_length=2, required=False, help_text='Código ISO: BO, CL…',
                           widget=forms.TextInput(attrs={'class': INPUT}))
    moneda = forms.CharField(label='Moneda', max_length=3, help_text='Código ISO: BOB, CLP…',
                             widget=forms.TextInput(attrs={'class': INPUT}))
    dec_total = forms.IntegerField(label='Decimales del total', min_value=0, max_value=8,
                                   widget=forms.NumberInput(attrs={'class': INPUT}))
    dec_linea = forms.IntegerField(label='Decimales de cada línea', min_value=0, max_value=8, required=False,
                                   help_text='Vacío = las líneas no se redondean, solo el total.',
                                   widget=forms.NumberInput(attrs={'class': INPUT}))
    modo = forms.ChoiceField(label='Redondeo', choices=MODOS,
                             widget=forms.Select(attrs={'class': 'select select-bordered select-sm w-full'}))

    def __init__(self, empresa, perfil=None, *args, **kwargs):
        self.empresa, self.perfil = empresa, perfil
        super().__init__(*args, **kwargs)

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        otros = PerfilCalculo.objects.filter(empresa=self.empresa, nombre=nombre)
        if self.perfil is not None:
            otros = otros.exclude(pk=self.perfil.pk)
        if otros.exists():
            raise forms.ValidationError('Ya tienes un perfil con ese nombre.')
        return nombre

    def clean_pais(self):
        return self.cleaned_data['pais'].strip().upper()

    def clean_moneda(self):
        return self.cleaned_data['moneda'].strip().upper()

    def redondeo(self):
        d = self.cleaned_data
        return {'linea': d['dec_linea'], 'total': d['dec_total'], 'modo': d['modo']}
