import json

from django import forms

from panel.forms import EstiloMixin, _estilizar
from reg_base import tipos

from .models import Paso, PasoWidget, Plantilla
from .widgets import todos


class PasoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Paso
        fields = ('titulo', 'nombre', 'descripcion')
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        if self.instance.pk:
            # El nombre es el identificador estable (URL y etapa de las fotos): no se cambia.
            self.fields['nombre'].disabled = True

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre']
        if not self.instance.pk and Paso.objects.filter(empresa=self.empresa, nombre=nombre).exists():
            raise forms.ValidationError('Ya existe un paso con ese nombre.')
        return nombre


class PasoWidgetForm(EstiloMixin, forms.Form):
    widget_slug = forms.ChoiceField(label='Tipo de widget')
    orden = forms.IntegerField(label='Orden', min_value=0, initial=0)
    config = forms.CharField(label='Configuración (JSON)', required=False, widget=forms.Textarea(attrs={'rows': 6, 'class': 'font-mono'}))

    def __init__(self, *args, paso, instance=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.paso, self.instance = paso, instance
        self.fields['widget_slug'].choices = [(w.slug, w.nombre) for w in todos()]
        if instance is not None:
            self.fields['widget_slug'].initial = instance.widget_slug
            self.fields['widget_slug'].disabled = True
        _estilizar(self)

    def clean_config(self):
        crudo = self.cleaned_data.get('config', '').strip()
        if not crudo:
            return {}
        try:
            config = json.loads(crudo)
        except ValueError as exc:
            raise forms.ValidationError(f'JSON inválido: {exc}')
        if not isinstance(config, dict):
            raise forms.ValidationError('La configuración debe ser un objeto JSON ({ ... }).')
        return config

    def clean(self):
        data = super().clean()
        slug = data.get('widget_slug') or (self.instance.widget_slug if self.instance else None)
        if slug and 'config' in data:
            if self.instance is None and PasoWidget.objects.filter(paso=self.paso, widget_slug=slug).exists():
                raise forms.ValidationError('Este paso ya tiene un widget de ese tipo.')
            from django.core.exceptions import ValidationError
            try:
                PasoWidget(paso=self.paso, widget_slug=slug, orden=data.get('orden') or 0, config=data['config']).clean()
            except ValidationError as exc:
                for mensaje in exc.messages:
                    self.add_error('config', mensaje)
        return data


class PlantillaForm(EstiloMixin, forms.ModelForm):
    tipo_registro = forms.ChoiceField(label='Tipo de registro')

    class Meta:
        model = Plantilla
        fields = ('nombre', 'tipo_registro', 'tipo_proyecto', 'descripcion', 'activa')
        widgets = {'descripcion': forms.Textarea(attrs={'rows': 2})}

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        # Solo los tipos activos en la empresa, más el de la plantilla que se edita (aunque se haya desactivado después).
        activos = {t.clave for t in tipos.habilitados(empresa)} | ({self.instance.tipo_registro} if self.instance.pk else set())
        self.fields['tipo_registro'].choices = [(t.clave, t.nombre) for t in tipos.todos() if t.clave in activos]
        self.fields['tipo_proyecto'].queryset = empresa.tipos_proyecto.all()
        self.fields['tipo_proyecto'].required = False
        _estilizar(self)

    def validate_constraints(self, *args, **kwargs):
        super().validate_constraints(*args, **kwargs)

    def clean(self):
        data = super().clean()
        if data.get('activa') and 'tipo_registro' in data:
            otras = Plantilla.objects.filter(empresa=self.empresa, tipo_registro=data['tipo_registro'], activa=True,
                                             tipo_proyecto=data.get('tipo_proyecto'))
            if self.instance.pk:
                otras = otras.exclude(pk=self.instance.pk)
            if otras.exists():
                raise forms.ValidationError('Ya hay una plantilla activa para ese tipo de registro y de proyecto: desactívala primero.')
        return data
