from datetime import date

from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q

from panel.forms import EstiloMixin, _estilizar
from proyectos.models import Proyecto
from reg_base.alcance import responsables_posibles

from .models import DESCRIPCION_DEFAULT, ESTADOS_OBRA, RegConstruccion


def proyectos_de_obra(empresa):
    """Proyectos donde puede haber obra: todos los activos de la empresa."""
    return Proyecto.objects.de_empresa(empresa).activos().select_related('tipo')


class ActivarConstruccionForm(EstiloMixin, forms.Form):
    proyecto = forms.ModelChoiceField(label='Proyecto', queryset=Proyecto.objects.none())
    fecha = forms.DateField(label='Fecha de la visita', initial=date.today,
                            widget=forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d'))
    contratista = forms.ModelChoiceField(label='Contratista', queryset=None, required=False)
    user = forms.ModelChoiceField(label='Responsable', queryset=None, required=False)

    def __init__(self, *args, empresa, usuario, puede_elegir_responsable, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields['proyecto'].label = empresa.termino_proyecto_singular or 'Proyecto'
        self.fields['proyecto'].queryset = proyectos_de_obra(empresa)
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        self.fields['contratista'].queryset = empresa.contratistas.filter(is_deleted=False, activo=True)
        self.fields['contratista'].label_from_instance = lambda c: c.nombre
        if puede_elegir_responsable:
            self.fields['user'].queryset = responsables_posibles(usuario, empresa)
            self.fields['user'].required = True
        else:
            del self.fields['user']
        _estilizar(self)


class DatosObraForm(EstiloMixin, forms.ModelForm):
    # El estado de la obra es el del proyecto: se edita aquí pero se guarda en Proyecto.estado.
    estado_obra = forms.ChoiceField(label='Estado de la obra', choices=ESTADOS_OBRA)

    class Meta:
        model = RegConstruccion
        fields = ('fecha', 'descripcion', 'revision', 'contratista', 'user')
        widgets = {'fecha': forms.DateInput(attrs={'type': 'date'}, format='%Y-%m-%d')}

    def __init__(self, *args, usuario=None, puede_cambiar_responsable=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['fecha'].input_formats = ['%Y-%m-%d']
        if self.instance.proyecto_id:
            self.initial['estado_obra'] = self.instance.proyecto.estado
        if puede_cambiar_responsable:   # reasignar la visita a otro ITO/Buscador (reg.cambiar_responsable)
            posibles = responsables_posibles(usuario, self.instance.empresa)
            # quien ya es el responsable sigue siendo una opción válida aunque ya no figure entre los posibles
            self.fields['user'].queryset = get_user_model().objects.filter(
                Q(pk__in=posibles.values('pk')) | Q(pk=self.instance.user_id)).order_by('first_name', 'email')
            self.fields['user'].label = 'ITO responsable'
            self.fields['user'].required = True
        else:
            del self.fields['user']
        self.fields['contratista'].queryset = self.instance.empresa.contratistas.filter(is_deleted=False)
        self.fields['contratista'].label_from_instance = lambda c: c.nombre
        self.fields['contratista'].required = False
        self.fields['descripcion'].required = False
        _estilizar(self)

    def save(self, commit=True):
        registro = super().save(commit=commit)
        proyecto, estado = registro.proyecto, self.cleaned_data['estado_obra']
        if commit and proyecto and proyecto.estado != estado:
            proyecto.estado = estado
            proyecto.save(update_fields=['estado', 'actualizado'])
        return registro
