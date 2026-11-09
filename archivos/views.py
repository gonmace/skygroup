from django.contrib.auth.decorators import login_required
from django.core.files.storage import storages
from django.http import FileResponse, Http404, HttpResponseRedirect

from empresas.tenancy import es_miembro

from .registro import esta_protegido


@login_required
def privado(request, ruta):
    """Entrega un archivo del storage privado. Convención: `<empresa_id>/<modulo>/...`."""
    partes = ruta.split('/')
    if not partes[0].isdigit() or any(p in ('', '.', '..') or '\\' in p for p in partes):
        raise Http404
    primero = partes[0]
    if len(partes) > 1 and esta_protegido(partes[1]):
        raise Http404  # lo sirve la vista de su módulo, con su propia autorización
    if not request.user.is_superuser:
        from empresas.models import Empresa
        empresa = Empresa.objects.filter(pk=int(primero), activa=True).first()
        if empresa is None or not es_miembro(request.user, empresa):
            raise Http404  # no revelar que existe
    storage = storages['privado']
    if not storage.exists(ruta):
        raise Http404
    if storage.local.exists(ruta):
        return FileResponse(storage.local.open(ruta, 'rb'))
    return HttpResponseRedirect(storage.remote.url(ruta))
