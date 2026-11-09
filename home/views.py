from django.contrib.auth.views import redirect_to_login
from django.core.cache import cache
from django.db import connection
from django.http import JsonResponse
from django.shortcuts import render
from django.views.decorators.cache import never_cache


def index(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None:
        from panel.menu import MODULOS
        return render(request, 'home/index.html', {  # portada pública (sin empresa): los 3 módulos
            'lanzador_publico': [
                {'codigo': c, **m, 'resalte': m.get('resalte', ''),
                 'nombre_base': m['nombre'].removesuffix(m.get('resalte', '')).rstrip()}
                for c, m in MODULOS.items()],
        })
    if not request.user.is_authenticated:
        return redirect_to_login(request.get_full_path())
    from django.db.models import Count, Q

    from cuentas.capacidades import tiene_capacidad
    from cuentas.models import Membresia, RolEmpresa
    from empresas.models import Contratista, Modulo
    from proyectos.models import Proyecto
    user = request.user
    contratistas = proyectos = roles = n_usuarios = None
    if tiene_capacidad(user, 'cuentas.usuarios.manage', empresa):
        n_usuarios = Membresia.objects.filter(empresa=empresa, activa=True, user__is_active=True).count()
    if tiene_capacidad(user, 'empresas.contratistas.manage', empresa):
        contratistas = (Contratista.objects.filter(empresa=empresa, is_deleted=False)
                        .annotate(personas=Count('membresias', filter=Q(membresias__activa=True), distinct=True)))
    if tiene_capacidad(user, 'proyectos.view', empresa):
        base = Proyecto.objects.de_empresa(empresa).activos()
        por_estado = {r['estado']: r['n'] for r in base.values('estado').annotate(n=Count('pk'))}
        proyectos = {
            'total': sum(por_estado.values()),
            'por_estado': [(label, por_estado.get(valor, 0)) for valor, label in Proyecto.Estado.choices],
            'por_tipo': list(base.filter(tipo__isnull=False).values_list('tipo__nombre').annotate(n=Count('pk')).order_by('-n')),
            'sin_tipo': base.filter(tipo__isnull=True).count(),
        }
    if tiene_capacidad(user, 'cuentas.roles.manage', empresa):
        roles = (RolEmpresa.objects.filter(empresa=empresa, activo=True)
                 .annotate(personas=Count('membresias', filter=Q(membresias__activa=True), distinct=True)))
    return render(request, 'home/empresa.html', {
        'n_usuarios': n_usuarios,
        'modulos': [{'codigo': m.value, 'nombre': m.label} for m in Modulo if empresa.tiene_modulo(m.value)],
        'contratistas': contratistas, 'proyectos': proyectos, 'roles': roles,
        'puede_marca': tiene_capacidad(user, 'empresas.marca.manage', empresa),
    })


@never_cache
def healthz(request):
    """Healthcheck para Docker/deploy: verifica DB y cache."""
    try:
        with connection.cursor() as cursor:
            cursor.execute('SELECT 1')
        cache.set('healthz', 1, 10)
        if cache.get('healthz') != 1:
            raise RuntimeError('cache no responde')
    except Exception:
        return JsonResponse({'status': 'error'}, status=503)
    return JsonResponse({'status': 'ok'})
