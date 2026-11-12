from datetime import date

from django import forms

from panel.forms import EstiloMixin
from proyectos.models import Proyecto
from reg_base.alcance import responsables_posibles

from .models import ALTERNATIVAS, RegTxtss


class ListaProyectosWidget(forms.CheckboxSelectMultiple):
    """Casillas con buscador: un `select multiple` con cientos de proyectos es inmanejable (y DaisyUI lo deforma)."""
    template_name = 'reg_txtss/widgets/lista_proyectos.html'
    option_template_name = 'reg_txtss/widgets/lista_proyectos_opcion.html'


class ActivarTxtssForm(EstiloMixin, forms.Form):
    proyectos = forms.ModelMultipleChoiceField(label='Proyectos', queryset=Proyecto.objects.none())
    fecha = forms.DateField(label='Fecha', initial=date.today, widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    alternativa = forms.ChoiceField(label='Alternativa', choices=ALTERNATIVAS, initial='A')
    user = forms.ModelChoiceField(label='Responsable', queryset=None, required=False)

    def __init__(self, *args, empresa, usuario, puede_elegir_responsable, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa, self.usuario = empresa, usuario
        # El widget va primero: al asignar el queryset, Django le copia las opciones (si no, el select sale vacío).
        self.fields['proyectos'].widget = ListaProyectosWidget()
        self.fields['proyectos'].queryset = Proyecto.objects.de_empresa(empresa).activos().select_related('tipo')
        self.fields['proyectos'].help_text = 'Marca uno o varios.'
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        if puede_elegir_responsable:
            self.fields['user'].queryset = responsables_posibles(usuario, empresa)
            self.fields['user'].required = True
        else:
            del self.fields['user']   # el responsable es quien activa
        from panel.forms import _estilizar
        _estilizar(self)


class ResponsableForm(EstiloMixin, forms.Form):
    user = forms.ModelChoiceField(label='Responsable', queryset=None, required=False)
    alternativa = forms.ChoiceField(label='Alternativa', choices=[('', '—')] + ALTERNATIVAS, required=False)

    def __init__(self, *args, empresa, usuario, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = responsables_posibles(usuario, empresa)
        from panel.forms import _estilizar
        _estilizar(self)
