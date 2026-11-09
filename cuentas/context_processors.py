from .models import NextcloudConfig, NextcloudVinculo


def nextcloud_cuenta(request):
    """Para el menú del usuario: ¿ofrecer vincular/desvincular Nextcloud? Solo con sesión propia (no al «ver como»)."""
    user = getattr(request, 'user', None)
    empresa = getattr(request, 'empresa', None)
    if not user or not user.is_authenticated or empresa is None or getattr(request, 'impersonador', None):
        return {}
    config = NextcloudConfig.de(empresa)
    if not config.disponible:
        return {}
    return {'nc_disponible': True, 'nc_vinculado': NextcloudVinculo.objects.filter(empresa=empresa, user=user).exists()}
