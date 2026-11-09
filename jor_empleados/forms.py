from django import forms


from empresas.models import REPORTE_CONTROL_PERSONAL, Empresa

from .models import ConfigJornadas, Perfil, quitar_cargo

_INPUT = 'input input-bordered w-full'


class PerfilForm(forms.ModelForm):
    def clean_cargo(self):
        return quitar_cargo(self.cleaned_data['cargo'], self.instance.membresia.rol.nombre)

    class Meta:
        model = Perfil
        fields = ['cargo', 'hora_entrada', 'activo', 'exige_reporte', 'puede_excepcion',
                  'haber_basico', 'ciudad_catering', 'numero_item']
        widgets = {
            'cargo': forms.TextInput(attrs={'class': _INPUT}),
            'hora_entrada': forms.TimeInput(attrs={'class': _INPUT, 'type': 'time'}, format='%H:%M'),
            'haber_basico': forms.NumberInput(attrs={'class': _INPUT, 'step': '0.01'}),
            'ciudad_catering': forms.Select(attrs={'class': 'select select-bordered w-full'}),
            'numero_item': forms.NumberInput(attrs={'class': _INPUT}),
            'activo': forms.CheckboxInput(attrs={'class': 'checkbox'}),
            'puede_excepcion': forms.CheckboxInput(attrs={'class': 'checkbox'}),
            'exige_reporte': forms.CheckboxInput(attrs={'class': 'checkbox'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        for nombre in ('haber_basico', 'ciudad_catering'):
            self.fields[nombre].required = False

    def clean_haber_basico(self):
        return self.cleaned_data.get('haber_basico') or 0

    def clean_ciudad_catering(self):
        return self.cleaned_data.get('ciudad_catering') or 'NONE'


MAX_PLANTILLA = 5 * 1024 * 1024


class ConfigJornadasForm(forms.ModelForm):
    # Vive en la empresa (el menú y las descargas lo leen de ahí), pero se edita aquí, con el resto de Jornadas.
    termino_certificado = forms.CharField(
        label='Nombre del reporte de personal', max_length=60, required=False,
        widget=forms.TextInput(attrs={'class': _INPUT, 'placeholder': REPORTE_CONTROL_PERSONAL}),
        help_text='Cómo llama esta empresa al reporte que consolida el control de personal, ej. «Certificado de pago» '
                  f'o «Informe de personal». Vacío = «{REPORTE_CONTROL_PERSONAL}».')
    field_order = ['termino_certificado']

    class Meta:
        model = ConfigJornadas
        fields = ['descuento_refrigerio_min', 'plantilla_certificado', 'tipo_cambio_certificado', 'moneda_certificado']
        widgets = {
            'descuento_refrigerio_min': forms.NumberInput(attrs={'class': _INPUT}),
            'plantilla_certificado': forms.ClearableFileInput(attrs={'class': 'file-input file-input-bordered w-full', 'accept': '.xlsx'}),
            'tipo_cambio_certificado': forms.NumberInput(attrs={'class': _INPUT, 'step': 'any'}),
            'moneda_certificado': forms.TextInput(attrs={'class': _INPUT}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['termino_certificado'].initial = self.instance.empresa.termino_certificado
        for nombre in ('tipo_cambio_certificado', 'moneda_certificado'):
            self.fields[nombre].required = False
        self.fields['plantilla_certificado'].help_text = (
            'Libro .xlsx con variables {{ … }}. Sin plantilla se usa la base. Una plantilla sin variables con las hojas '
            '«PL» y «1…12» (formato clásico) también funciona.')
        self.fields['tipo_cambio_certificado'].help_text = 'Solo para plantillas clásicas.'
        self.fields['moneda_certificado'].help_text = 'Solo para plantillas clásicas.'

    def save(self, commit=True):
        config = super().save(commit)
        if commit:
            Empresa.objects.filter(pk=config.empresa_id).update(
                termino_certificado=(self.cleaned_data.get('termino_certificado') or '').strip())
        return config

    def clean_tipo_cambio_certificado(self):
        return self.cleaned_data.get('tipo_cambio_certificado') or self.instance.tipo_cambio_certificado

    def clean_moneda_certificado(self):
        return self.cleaned_data.get('moneda_certificado') or self.instance.moneda_certificado

    def clean_plantilla_certificado(self):
        f = self.cleaned_data.get('plantilla_certificado')
        if f and hasattr(f, 'read'):
            import openpyxl

            from jor_reportes import plantilla_motor
            if f.size > MAX_PLANTILLA:
                raise forms.ValidationError('La plantilla pesa demasiado (máximo 5 MB).')
            try:
                wb = openpyxl.load_workbook(f)
            except Exception:
                raise forms.ValidationError('No es un libro .xlsx válido.')
            if plantilla_motor.tiene_variables(wb):
                errores = plantilla_motor.validar(wb)
                if errores:
                    resto = len(errores) - 10
                    raise forms.ValidationError(errores[:10] + ([f'… y {resto} problema(s) más.'] if resto > 0 else []))
            elif not {'PL', '1'} <= set(wb.sheetnames):
                raise forms.ValidationError(
                    'La plantilla no tiene variables {{ }} ni la estructura clásica (hojas «PL» y «1»). '
                    'Descarga la plantilla base y adáptala.')
            f.seek(0)
        return f
