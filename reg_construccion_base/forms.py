from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from panel.forms import EstiloMixin, _estilizar
from proyectos.models import Proyecto
from reg_base.alcance import responsables_posibles

from .models import Hallazgo, RegConstruccionBase

FECHA = forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')


def _contratistas(campo, empresa):
    campo.queryset = empresa.contratistas.filter(is_deleted=False, activo=True)
    campo.label_from_instance = lambda c: c.nombre
    campo.required = False


class NuevaVisitaForm(EstiloMixin, forms.Form):
    proyecto = forms.ModelChoiceField(label='Proyecto', queryset=Proyecto.objects.none())
    fecha = forms.DateField(label='Fecha de la visita', initial=date.today, widget=FECHA)
    contratista = forms.ModelChoiceField(label='Contratista', queryset=None, required=False)
    user = forms.ModelChoiceField(label='Supervisor', queryset=None, required=False)

    def __init__(self, *args, empresa, usuario, puede_elegir_responsable, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['proyecto'].label = empresa.termino_proyecto_singular or 'Proyecto'
        self.fields['proyecto'].queryset = Proyecto.objects.de_empresa(empresa).activos().select_related('tipo')
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        _contratistas(self.fields['contratista'], empresa)
        if puede_elegir_responsable:
            self.fields['user'].queryset = responsables_posibles(usuario, empresa)
            self.fields['user'].required = True
        else:
            del self.fields['user']
        _estilizar(self)


class DatosVisitaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = RegConstruccionBase
        fields = ('fecha', 'contratista', 'user')
        widgets = {'fecha': FECHA}

    def __init__(self, *args, usuario=None, puede_cambiar_responsable=False, **kwargs):
        super().__init__(*args, **kwargs)
        empresa = self.instance.empresa
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        _contratistas(self.fields['contratista'], empresa)
        if puede_cambiar_responsable:
            posibles = responsables_posibles(usuario, empresa)
            self.fields['user'].queryset = get_user_model().objects.filter(
                Q(pk__in=posibles.values('pk')) | Q(pk=self.instance.user_id)).order_by('first_name', 'email')
            self.fields['user'].label = 'Supervisor'
            self.fields['user'].required = True
        else:
            del self.fields['user']
        _estilizar(self)


class HallazgoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Hallazgo
        fields = ('descripcion', 'tipo', 'severidad', 'responsable', 'plazo')
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 4}), 'plazo': FECHA}

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['plazo'].input_formats = ['%Y-%m-%d']
        _estilizar(self)
