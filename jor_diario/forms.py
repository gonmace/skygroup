from django import forms

from .models import Ausencia, NotaCalendario

_INPUT = 'input input-bordered w-full'


class ReporteForm(forms.Form):
    realizado = forms.CharField(label='Actividades realizadas', required=False, widget=forms.Textarea(
        attrs={'class': 'textarea textarea-bordered w-full', 'rows': 5}))
    planificado = forms.CharField(label='Actividades planificadas', required=False, widget=forms.Textarea(
        attrs={'class': 'textarea textarea-bordered w-full', 'rows': 4}))


class AusenciaForm(forms.ModelForm):
    perfil = forms.ModelChoiceField(label='Persona', queryset=None, required=False, empty_label=None,
                                    widget=forms.Select(attrs={'class': 'select select-bordered w-full'}))

    class Meta:
        model = Ausencia
        fields = ['perfil', 'tipo', 'desde', 'hasta', 'nota']
        widgets = {
            'tipo': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'desde': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}, format='%Y-%m-%d'),
            'hasta': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}, format='%Y-%m-%d'),
            'nota': forms.TextInput(attrs={'class': _INPUT}),
        }

    def __init__(self, *args, perfiles=None, **kwargs):
        super().__init__(*args, **kwargs)
        if perfiles is None:        # quien solo solicita las propias no elige persona
            del self.fields['perfil']
        else:
            self.fields['perfil'].queryset = perfiles

    def clean(self):
        datos = super().clean()
        if datos.get('desde') and datos.get('hasta') and datos['hasta'] < datos['desde']:
            self.add_error('hasta', 'La fecha final no puede ser anterior a la inicial.')
        return datos


class NotaForm(forms.ModelForm):
    class Meta:
        model = NotaCalendario
        fields = ['fecha', 'tipo', 'texto']
        widgets = {
            'fecha': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}, format='%Y-%m-%d'),
            'tipo': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'texto': forms.TextInput(attrs={'class': _INPUT}),
        }
