from django import forms
from django.forms import inlineformset_factory

from panel.forms import EstiloMixin

from .models import Proyecto, ProyectoUbicacion, TipoProyecto


class ProyectoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Proyecto
        fields = ('nombre', 'codigo', 'codigo_operador', 'tipo', 'estado',
                  'region', 'comuna', 'ciudad', 'descripcion')
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 3})}

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        self.fields['tipo'].queryset = empresa.tipos_proyecto.all()
        self.fields['tipo'].required = False
        self.fields['codigo'].label = 'Código'

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip()
        if not codigo:
            return codigo
        repetidos = Proyecto.objects.filter(empresa=self.empresa, is_deleted=False, codigo__iexact=codigo)
        if self.instance.pk:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError('Ya existe un registro con ese código.')
        return codigo


class UbicacionForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = ProyectoUbicacion
        fields = ('etiqueta', 'lat', 'lon')


UbicacionFormSet = inlineformset_factory(
    Proyecto, ProyectoUbicacion, form=UbicacionForm, extra=1, can_delete=True,
)


class TipoProyectoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = TipoProyecto
        fields = ('nombre', 'descripcion')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        repetidos = self.empresa.tipos_proyecto.filter(nombre__iexact=nombre)
        if self.instance.pk:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError('Ya existe un tipo con ese nombre.')
        return nombre
