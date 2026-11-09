from django import forms
from django.contrib.auth import get_user_model
from django.db.models import Q
from django.utils.text import Truncator

from cuentas.models import Membresia
from cuentas.roles import RolBase
from proyectos.models import Proyecto

from .models import Comentario, Etiqueta, Ticket

User = get_user_model()

_INPUT = 'input input-bordered w-full'
_TEXTAREA = 'textarea textarea-bordered w-full'
_SELECT = 'select select-bordered w-full min-w-0'
_CHECK = 'checkbox checkbox-sm checkbox-primary'


def _etiqueta_usuario(u):
    nombre = u.get_full_name().strip()
    texto = f'{nombre} · {u.email}' if nombre else u.email
    # Un usuario dado de baja que sigue asignado debe verse (y verse distinto): si no apareciera
    # en el form, guardar cualquier edición lo desasignaría en silencio.
    return texto if u.is_active else f'{texto} — dado de baja'


def _etiqueta_proyecto(p):
    # El <select> nativo no recorta de forma confiable un texto largo: se acorta la etiqueta.
    return Truncator(f'{p.codigo} · {p.nombre}').chars(70)


def _ids_de_rol(empresa, roles_base):
    return Membresia.objects.filter(
        empresa=empresa, activa=True, user__is_active=True, rol__rol_base__in=roles_base,
    ).values_list('user_id', flat=True)


class TicketForm(forms.ModelForm):
    ejecutores = forms.ModelMultipleChoiceField(
        label='Ejecutores', required=False, queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': _CHECK}),
        help_text='Uno o varios. Al asignar, el ticket pasa a «Por hacer».',
    )
    expertos = forms.ModelMultipleChoiceField(
        label='Expertos', required=False, queryset=User.objects.none(),
        widget=forms.CheckboxSelectMultiple(attrs={'class': _CHECK}), help_text='Opcional (consultores).',
    )

    class Meta:
        model = Ticket
        fields = ('titulo', 'solicitante', 'descripcion', 'proyecto', 'prioridad', 'vence', 'etiquetas',
                  'tiene_subproductos')
        widgets = {
            'titulo': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Título del ticket'}),
            'solicitante': forms.TextInput(attrs={'class': _INPUT, 'placeholder': 'Quién lo solicita'}),
            'descripcion': forms.Textarea(attrs={'class': _TEXTAREA, 'rows': 5}),
            'proyecto': forms.Select(attrs={'class': f'{_SELECT} block'}),
            'prioridad': forms.Select(attrs={'class': _SELECT}),
            'vence': forms.DateInput(attrs={'class': _INPUT, 'type': 'date'}, format='%Y-%m-%d'),
            'etiquetas': forms.CheckboxSelectMultiple(attrs={'class': _CHECK}),
            'tiene_subproductos': forms.CheckboxInput(attrs={'class': 'toggle toggle-primary'}),
        }

    def __init__(self, *args, puede_asignar=True, user=None, empresa=None, **kwargs):
        super().__init__(*args, **kwargs)
        if empresa is None and self.instance.pk:
            empresa = self.instance.empresa
        self.empresa = empresa
        self.fields['vence'].input_formats = ['%Y-%m-%d']
        # Alcance por empresa: proyectos, etiquetas y personas asignables son SOLO los de la empresa
        # (el POST tampoco acepta ids ajenos: el queryset es lo que valida el campo).
        self.fields['proyecto'].queryset = Proyecto.objects.de_empresa(empresa).activos()
        self.fields['proyecto'].label_from_instance = _etiqueta_proyecto
        self.fields['etiquetas'].queryset = Etiqueta.objects.filter(empresa=empresa)
        ids_ejec, ids_exp = [], []
        if self.instance.pk:
            ids_ejec = [a.user_id for a in self.instance.ejecutores]
            ids_exp = [a.user_id for a in self.instance.expertos]
        # Los ya asignados entran al queryset aunque estén dados de baja (ver _etiqueta_usuario).
        # Quien dirige también puede ser ejecutor, pero nunca uno mismo.
        candidatos = Q(pk__in=_ids_de_rol(empresa, [RolBase.MIEMBRO, RolBase.COORDINADOR]))
        if user is not None:
            candidatos &= ~Q(pk=user.pk)
        self.fields['ejecutores'].queryset = User.objects.filter(
            candidatos | Q(pk__in=ids_ejec)).distinct().order_by('first_name', 'email')
        self.fields['expertos'].queryset = User.objects.filter(
            Q(pk__in=_ids_de_rol(empresa, [RolBase.ESPECIALISTA])) | Q(pk__in=ids_exp),
        ).distinct().order_by('first_name', 'email')
        self.fields['ejecutores'].label_from_instance = _etiqueta_usuario
        self.fields['expertos'].label_from_instance = _etiqueta_usuario
        self.fields['ejecutores'].initial = ids_ejec
        self.fields['expertos'].initial = ids_exp
        if not puede_asignar:
            self.fields.pop('ejecutores')
            self.fields.pop('expertos')

    def clean_titulo(self):
        return self.cleaned_data['titulo'].strip()

    def clean_solicitante(self):
        valor = self.cleaned_data['solicitante'].strip()
        if not valor:
            raise forms.ValidationError('Indica quién lo solicita.')
        return valor


class ComentarioForm(forms.ModelForm):
    class Meta:
        model = Comentario
        fields = ('texto',)
        widgets = {
            'texto': forms.Textarea(attrs={
                # min-h-0: DaisyUI fuerza min-height:5rem en .textarea sin importar `rows`.
                'class': f'{_TEXTAREA} min-h-0', 'rows': 1, 'placeholder': 'Escribe un mensaje de seguimiento…',
                'id': 'chat-compose',  # id fijo: chat-submit.js lo enfoca tras enviar
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # No requerido: se permite mandar solo adjuntos sin texto (la vista exige texto o archivos).
        self.fields['texto'].required = False
