from .models import Notificacion


def campana(request):
    """Cantidad de avisos sin leer del usuario en la empresa activa (para la campana)."""
    user = getattr(request, 'user', None)
    empresa = getattr(request, 'empresa', None)
    if not user or not user.is_authenticated or empresa is None:
        return {}
    return {
        'notif_no_leidas': Notificacion.objects.filter(destinatario=user, empresa=empresa, leida=False).count(),
    }
