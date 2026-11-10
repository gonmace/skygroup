import re

from django import forms
from django.db import models

from cuentas.models import CorreoBloqueado, CorreoConfig, DominioPermitido, NextcloudConfig, RolEmpresa
from cuentas.roles import RolBase
from empresas.models import Contratista, Empresa, Modulo, Sede

from .widgets import ColorWidget, ImagenWidget

INPUT = 'input input-bordered w-full'
SELECT = 'select select-bordered w-full'
FILE = 'file-input file-input-bordered w-full'


def _estilizar(form):
    for campo in form.fields.values():
        w = campo.widget
        if isinstance(w, (forms.CheckboxInput,)):
            w.attrs.setdefault('class', 'checkbox')
        elif isinstance(w, forms.CheckboxSelectMultiple):
            pass
        elif isinstance(w, (forms.Select, forms.SelectMultiple)):
            w.attrs.setdefault('class', SELECT)
        elif isinstance(w, forms.ClearableFileInput):
            w.attrs.setdefault('class', FILE)
        elif isinstance(w, forms.Textarea):
            w.attrs.setdefault('class', 'textarea textarea-bordered w-full')
        else:
            w.attrs.setdefault('class', INPUT)


class EstiloMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        _estilizar(self)


COLORES = ('color_primario', 'color_primario_oscuro', 'color_acento', 'color_acento_oscuro')
WIDGETS_MARCA = {
    'logo_claro': ImagenWidget(), 'logo_oscuro': ImagenWidget(oscuro=True), 'favicon': ImagenWidget(pequena=True),
    **{c: ColorWidget() for c in COLORES},
}
CAMPOS_MARCA = (
    'nombre_marca', 'logo_claro', 'logo_oscuro', 'favicon', *COLORES,
    'termino_proyecto_singular', 'termino_proyecto_plural',
)


class MarcaForm(EstiloMixin, forms.ModelForm):
    """Lo que edita el Coordinador de la empresa."""

    class Meta:
        model = Empresa
        fields = CAMPOS_MARCA
        widgets = WIDGETS_MARCA


class EmpresaForm(EstiloMixin, forms.ModelForm):
    """Alta/edición global (superusuario): identidad, módulos y todo lo de marca."""

    modulos = forms.MultipleChoiceField(
        label='Módulos habilitados', choices=Modulo.choices, widget=forms.CheckboxSelectMultiple, required=False,
    )

    class Meta:
        model = Empresa
        fields = ('nombre', 'slug', 'activa', 'razon_social', 'rut', 'contacto_email', 'contacto_telefono',
                  'modulos', *CAMPOS_MARCA, 'nombre_proveedor', 'logo_proveedor')
        # El proveedor del servicio (p. ej. Redline) lo define solo el superusuario: no está en CAMPOS_MARCA.
        widgets = {**WIDGETS_MARCA, 'logo_proveedor': ImagenWidget()}

    tipos_proyecto = forms.CharField(
        label='Tipos de proyecto (opcional)', required=False,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Poste, Torre'}),
        help_text='Separados por coma o uno por línea (p. ej. en telecomunicaciones: Poste, Torre). '
                  'Puedes dejarlo vacío y definirlos más adelante en Proyectos → Tipos.',
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:            # en una empresa existente se gestionan en su pantalla de tipos
            del self.fields['tipos_proyecto']

    def clean_modulos(self):
        return list(self.cleaned_data['modulos'])

    def clean_tipos_proyecto(self):
        vistos, tipos = set(), []
        for n in re.split(r'[,\n;]', self.cleaned_data['tipos_proyecto']):
            n = ' '.join(n.split())
            if n and n.lower() not in vistos:
                if len(n) > 60:
                    raise forms.ValidationError(f'«{n[:20]}…» supera los 60 caracteres.')
                vistos.add(n.lower())
                tipos.append(n)
        return tipos

    def save_tipos(self, empresa):
        """Crea los tipos indicados al dar de alta la empresa (en el orden escrito)."""
        from proyectos.models import TipoProyecto
        for orden, nombre in enumerate(self.cleaned_data.get('tipos_proyecto', []), 1):
            TipoProyecto.objects.get_or_create(empresa=empresa, nombre=nombre, defaults={'orden': orden})


class AdministradorForm(EstiloMixin, forms.Form):
    """Administrador de sistema: quién es y qué empresas administra (no es un cargo de la RACI)."""
    email = forms.EmailField(label='Correo')
    first_name = forms.CharField(label='Nombre', max_length=150, required=False)
    last_name = forms.CharField(label='Apellido', max_length=150, required=False)
    empresas = forms.ModelMultipleChoiceField(
        label='Empresas que administra', queryset=Empresa.objects.none(), required=False,
        widget=forms.CheckboxSelectMultiple,
        help_text='Gestiona miembros, cargos, marca, contratistas y proyectos de esas empresas, aunque no sea miembro.')
    superusuario = forms.BooleanField(
        label='Superusuario', required=False,
        help_text='Administra toda la plataforma: todas las empresas, Plataforma y los administradores.')
    enviar_correo = forms.BooleanField(label='Enviar correo', required=False, initial=True,
                                       help_text='Cuenta nueva: invitación para elegir contraseña.')

    def __init__(self, *args, usuario=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.usuario = usuario
        self.fields['empresas'].queryset = Empresa.objects.order_by('nombre')
        if usuario is not None:
            self.fields['email'].disabled = True
            del self.fields['enviar_correo']

    def clean(self):
        d = super().clean()
        if not d.get('superusuario') and not d.get('empresas'):
            raise forms.ValidationError('Elige al menos una empresa, o márcalo como superusuario.')
        return d


class MiembroForm(EstiloMixin, forms.Form):
    email = forms.EmailField(label='Correo')
    first_name = forms.CharField(label='Nombre', max_length=150, required=False)
    last_name = forms.CharField(label='Apellido', max_length=150, required=False)
    rol = forms.ModelChoiceField(label='Cargo', queryset=RolEmpresa.objects.none())
    contratista = forms.ModelChoiceField(
        label='Contratista', queryset=Contratista.objects.none(), required=False,
        help_text='Vacío = personal de la propia empresa.',
    )
    sede = forms.ModelChoiceField(label='Sede', queryset=Sede.objects.none(), required=False,
                                  help_text='Opcional.')
    enviar_correo = forms.BooleanField(
        label='Enviar correo', required=False, initial=True,
        help_text='Cuenta nueva: invitación para elegir contraseña. Cuenta existente: aviso de que fue agregada.',
    )

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.fields['rol'].queryset = empresa.roles.filter(activo=True)
        self.fields['contratista'].queryset = empresa.contratistas.filter(is_deleted=False, activo=True)
        self.fields['sede'].queryset = empresa.sedes.filter(activo=True)
        _estilizar(self)


class CambiarMiembroForm(EstiloMixin, forms.Form):
    # Datos de la persona (son de la cuenta: valen para todas las empresas a las que pertenece).
    first_name = forms.CharField(label='Nombre', max_length=150, required=False)
    last_name = forms.CharField(label='Apellido', max_length=150, required=False)
    telefono = forms.CharField(label='Teléfono', max_length=30, required=False)
    rol = forms.ModelChoiceField(label='Cargo', queryset=RolEmpresa.objects.none())
    contratista = forms.ModelChoiceField(label='Contratista', queryset=Contratista.objects.none(), required=False)
    sede = forms.ModelChoiceField(label='Sede', queryset=Sede.objects.none(), required=False)
    activa = forms.BooleanField(label='Activa', required=False)

    def __init__(self, *args, empresa, puede_admin=False, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['rol'].queryset = empresa.roles.filter(activo=True)
        if puede_admin:
            # Solo el superusuario: dejar el cargo vacío convierte a la persona en administrador de sistema.
            self.fields['rol'].required = False
            self.fields['rol'].empty_label = 'Vacío = administrador de sistema'
        # Incluye los inactivos para que quien ya pertenece a uno no lo pierda al editar otro campo.
        self.fields['contratista'].queryset = empresa.contratistas.filter(is_deleted=False)
        self.fields['sede'].queryset = empresa.sedes.all()   # incluye inactivas: no se pierde la que ya tiene
        _estilizar(self)


class RolEmpresaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = RolEmpresa
        fields = ('nombre', 'rol_base', 'descripcion', 'activo')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        self.fields['rol_base'].help_text = 'Define los permisos por defecto del cargo. No se puede cambiar si el cargo tiene miembros.'
        if self.instance.pk:
            # El rol base fija la semántica: no se cambia con miembros asignados.
            self.fields['rol_base'].disabled = True
        _estilizar(self)

    def save(self, commit=True):
        # El orden no se pide en el formulario: un rol nuevo va al final de la lista de la empresa.
        if not self.instance.pk:
            ultimo = self.empresa.roles.aggregate(m=models.Max('orden'))['m']
            self.instance.orden = 0 if ultimo is None else ultimo + 1
        return super().save(commit)

    def validate_unique(self):
        # La unicidad (empresa, lower(nombre)) la valida clean_nombre: Django no la ve en Meta.
        super().validate_unique()

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        qs = self.empresa.roles.filter(nombre__iexact=nombre)
        if self.instance.pk:
            qs = qs.exclude(pk=self.instance.pk)
        if qs.exists():
            raise forms.ValidationError('Ya existe un cargo con ese nombre.')
        return nombre


class ContratistaForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Contratista
        fields = ('nombre', 'codigo', 'activo')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa

    def clean_codigo(self):
        codigo = self.cleaned_data['codigo'].strip().upper()
        repetidos = Contratista.objects.filter(empresa=self.empresa, is_deleted=False, codigo__iexact=codigo)
        if self.instance.pk:
            repetidos = repetidos.exclude(pk=self.instance.pk)
        if repetidos.exists():
            raise forms.ValidationError('Ya existe un contratista con ese código.')
        return codigo


class SedeForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = Sede
        fields = ('nombre', 'lat', 'lon', 'radio_m', 'precision_max_m', 'activo')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        for nombre in ('radio_m', 'precision_max_m'):
            self.fields[nombre].required = False

    def clean_radio_m(self):
        return self.cleaned_data.get('radio_m') or Sede._meta.get_field('radio_m').default

    def clean_precision_max_m(self):
        return self.cleaned_data.get('precision_max_m') or Sede._meta.get_field('precision_max_m').default

    def clean(self):
        datos = super().clean()
        lat, lon = datos.get('lat'), datos.get('lon')
        if (lat is None) != (lon is None):
            self.add_error('lon' if lon is None else 'lat', 'Indica latitud y longitud, o deja ambas vacías.')
        elif lat is not None and not (-90 <= lat <= 90 and -180 <= lon <= 180):
            self.add_error('lat', 'Coordenadas fuera de rango.')
        return datos

    def clean_nombre(self):
        nombre = self.cleaned_data['nombre'].strip()
        repetidas = self.empresa.sedes.filter(nombre__iexact=nombre)
        if self.instance.pk:
            repetidas = repetidas.exclude(pk=self.instance.pk)
        if repetidas.exists():
            raise forms.ValidationError('Ya existe una sede con ese nombre.')
        return nombre


class DominioPermitidoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = DominioPermitido
        fields = ('dominio', 'rol')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.empresa = empresa
        self.instance.empresa = empresa
        # Solo cargos que el alta automática puede asignar: nunca Coordinador.
        self.fields['rol'].queryset = empresa.roles.filter(activo=True).exclude(rol_base=RolBase.COORDINADOR)
        _estilizar(self)

    def clean(self):
        datos = super().clean()
        if datos.get('dominio'):
            datos['dominio'] = datos['dominio'].strip().lower().lstrip('@')
            self.instance.dominio = datos['dominio']
            if DominioPermitido.objects.filter(empresa=self.empresa, dominio__iexact=datos['dominio']).exists():
                self.add_error('dominio', 'Ese dominio ya está en la lista.')
        return datos


class CorreoBloqueadoForm(EstiloMixin, forms.ModelForm):
    class Meta:
        model = CorreoBloqueado
        fields = ('email', 'motivo')

    def __init__(self, *args, empresa, **kwargs):
        super().__init__(*args, **kwargs)
        self.instance.empresa = empresa
        self.empresa = empresa

    def clean_email(self):
        email = self.cleaned_data['email'].strip().lower()
        if CorreoBloqueado.objects.filter(empresa=self.empresa, email__iexact=email).exists():
            raise forms.ValidationError('Ese correo ya está bloqueado.')
        return email


class NextcloudForm(EstiloMixin, forms.ModelForm):
    """Inicio de sesión con Nextcloud. El secret no se muestra: vacío conserva el guardado."""

    client_secret = forms.CharField(
        label='Client secret', required=False, widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Déjalo vacío para conservar el actual.')
    class Meta:
        model = NextcloudConfig
        fields = ('activo', 'servidor_url', 'client_id', 'client_secret', 'texto_boton', 'crear_cuentas', 'grupo_admin')

    def clean_client_secret(self):
        return self.cleaned_data['client_secret'] or self.instance.client_secret

    def clean_servidor_url(self):
        from cuentas.nextcloud import NextcloudError, validar_servidor
        url = self.cleaned_data['servidor_url'].rstrip('/')
        if url:
            try:
                validar_servidor(url)
            except NextcloudError as e:
                raise forms.ValidationError(str(e))
        return url

    def clean(self):
        d = super().clean()
        if d.get('activo') and not (d.get('servidor_url') and d.get('client_id') and d.get('client_secret')):
            raise forms.ValidationError('Para activarlo indica la URL, el Client ID y el Client secret.')
        return d


class CorreoForm(EstiloMixin, forms.ModelForm):
    """Servidor SMTP de la plataforma. La contraseña no se muestra: vacía conserva la guardada."""

    password = forms.CharField(
        label='Contraseña', required=False,
        widget=forms.PasswordInput(render_value=False, attrs={'autocomplete': 'new-password'}),
        help_text='Se guarda en la base de datos. Déjala vacía para conservar la actual.')

    class Meta:
        model = CorreoConfig
        fields = ('activo', 'host', 'puerto', 'seguridad', 'usuario', 'password', 'remitente', 'remitente_nombre')

    def clean_password(self):
        return self.cleaned_data['password'] or self.instance.password

    def clean_puerto(self):
        puerto = self.cleaned_data['puerto']
        if not 1 <= puerto <= 65535:
            raise forms.ValidationError('El puerto debe estar entre 1 y 65535.')
        return puerto

    def clean(self):
        d = super().clean()
        if d.get('activo') and not (d.get('host') and d.get('remitente')):
            raise forms.ValidationError('Para activarlo indica el servidor SMTP y el correo del remitente.')
        return d
