"""Marca, término de «proyecto» y módulos de la empresa del request."""
from django.urls import reverse

from .models import Modulo
from .tenancy import es_admin_de, empresas_de

PRODUCTO = 'SkyGroup'


def marca_empresa(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        return {
            'empresa': None, 'producto': PRODUCTO, 'marca': PRODUCTO,
            'logo_claro_url': None, 'logo_oscuro_url': None, 'favicon_url': None,
            'logo_proveedor_url': None, 'nombre_proveedor': '',
            'tema_css_url': None, 'termino_proyecto': 'Proyecto', 'termino_proyectos': 'Proyectos',
            'modulos_activos': [],
        }
    v = empresa.version_tema()
    logo_claro = f'{empresa.logo_claro.url}?v={v}' if empresa.logo_claro else None
    logo_oscuro = f'{empresa.logo_oscuro.url}?v={v}' if empresa.logo_oscuro else logo_claro
    return {
        'empresa': empresa,
        'producto': PRODUCTO,
        'marca': empresa.marca,
        'logo_claro_url': logo_claro,
        'logo_oscuro_url': logo_oscuro,
        'favicon_url': f'{empresa.favicon.url}?v={v}' if empresa.favicon else None,
        'logo_proveedor_url': f'{empresa.logo_proveedor.url}?v={v}' if empresa.logo_proveedor else None,
        'nombre_proveedor': empresa.nombre_proveedor,
        'tema_css_url': f"{reverse('empresas:tema_css')}?v={v}" if empresa.tiene_colores else None,
        'termino_proyecto': empresa.termino_proyecto_singular,
        'termino_proyectos': empresa.termino_proyecto_plural,
        'termino_certificado': empresa.nombre_certificado,
        'modulos_activos': [m for m in Modulo.values if empresa.tiene_modulo(m)],
    }


def papel_plataforma(request):
    """Papel de plataforma del usuario para la cabecera: 'super', 'admin' (de la empresa activa) o ''."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {'papel_plataforma': '', 'mi_cargo': None}
    empresa = getattr(request, 'empresa', None)
    mi_cargo = None   # cargo (RolEmpresa) del usuario en la empresa activa, si es miembro
    if empresa is not None:
        m = user.membresias.filter(empresa=empresa, activa=True).select_related('rol').first()
        mi_cargo = m.rol if m and not user.is_superuser else None   # el superusuario se identifica como tal, no por su cargo
    if user.is_superuser:
        papel = 'super'
    elif empresa is not None and es_admin_de(user, empresa):
        papel = 'admin'
    else:
        papel = ''
    return {'papel_plataforma': papel, 'mi_cargo': mi_cargo}


def selector_empresas(request):
    """Empresas a las que puede cambiar el usuario (solo si son más de una)."""
    user = getattr(request, 'user', None)
    if not user or not user.is_authenticated:
        return {}
    actual = getattr(request, 'empresa', None)
    empresas = empresas_de(user)
    if len(empresas) < 2:
        return {'nav_empresas': None}
    return {'nav_empresas': [{'empresa': e, 'activa': actual is not None and e.pk == actual.pk} for e in empresas]}
