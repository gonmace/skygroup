from django.contrib import messages
from django.http import Http404
from django.db.models import Count, OuterRef, Subquery
from django.shortcuts import get_object_or_404, redirect, render
from django.template.loader import render_to_string
from django.utils import timezone
from django.utils.safestring import mark_safe
from django.views.decorators.http import require_POST

from cuentas.capacidades import tiene_capacidad
from empresas.acceso import acceso_modulo
from proyectos.forms import TipoProyectoForm
from proyectos.models import TipoProyecto

from . import tipos
from .alcance import registros_visibles


@acceso_modulo('reg')
def inicio(request):
    """Resumen del módulo: cuántos registros hay en cada estado, dentro del alcance de la persona. Solo de los
    tipos de registro activos en la empresa."""
    user, empresa = request.user, request.empresa
    activos = {t.clave: t for t in tipos.habilitados(empresa)}

    def resumen(modelo, capacidad, url_name, nombre, con_estado_obra=False, tipo=None):
        if not tiene_capacidad(user, capacidad, empresa):
            return None
        base = registros_visibles(user, empresa, modelo.objects.all())
        if tipo:
            base = base.filter(proyecto__tipo=tipo)
        qs = base.with_estado()
        por_estado = {r['orden_estado']: r['n'] for r in qs.values('orden_estado').annotate(n=Count('pk'))}
        sitios = base.exclude(proyecto__isnull=True).values('proyecto_id').distinct().count()
        tarjeta = {
            'nombre': nombre, 'url': url_name, 'url_query': f'?tipo={tipo.pk}' if tipo else '',
            'con_estados': not con_estado_obra,   # en construcción importa el estado de la obra, no vacío/en proceso/concluido
            'sitios': sitios, 'reportes': sum(por_estado.values()), 'avance_medio': None,
            'en_proceso': por_estado.get(1, 0), 'concluidos': por_estado.get(2, 0), 'vacios': por_estado.get(3, 0),
            'por_obra': [],
        }
        if con_estado_obra:   # sitios por estado de obra, según su reporte más reciente
            from reg_construccion.models import ESTADOS_OBRA
            ultimo_avance = Subquery(base.filter(proyecto_id=OuterRef('proyecto_id')).order_by('-fecha', '-id')
                                     .values('avance_pct')[:1])
            conteo, avances = {}, []
            for e, av in (base.exclude(proyecto__isnull=True).order_by().values('proyecto_id', 'proyecto__estado')
                          .annotate(av=ultimo_avance).values_list('proyecto__estado', 'av')):
                conteo[e] = conteo.get(e, 0) + 1
                if e == 'CONSTRUCCION':   # el avance medio es el de las obras en curso
                    avances.append(av or 0)
            if avances:
                tarjeta['avance_medio'] = round(sum(avances) / len(avances))
            tarjeta['por_obra'] = [(codigo, f'{nombre_e} {conteo[codigo]}') for codigo, nombre_e in ESTADOS_OBRA
                                   if conteo.get(codigo)]
        return tarjeta

    tarjetas = []
    if 'txtss' in activos:
        from reg_txtss.models import RegTxtss
        por_tipo = list(empresa.tipos_proyecto.all())
        for t in por_tipo:
            tarjetas.append(resumen(RegTxtss, 'reg.txtss.ver', 'reg_txtss:lista', f'TX/TSS {t.nombre}', tipo=t))
        if not por_tipo:
            tarjetas.append(resumen(RegTxtss, 'reg.txtss.ver', 'reg_txtss:lista', 'TX/TSS'))
    if 'construccion' in activos:
        from reg_construccion.models import RegConstruccion
        tarjetas.append(resumen(RegConstruccion, 'reg.construccion.ver', 'reg_construccion:lista',
                                activos['construccion'].nombre, con_estado_obra=True))
    if 'construccion-base' in activos:
        t = activos['construccion-base']
        tarjetas.append(resumen(t.modelo, t.capacidad_ver, 'reg_construccion_base:lista', t.nombre))

    # Panel propio de cada tipo activo que lo defina (el mapa de proyectos solo se pinta una vez por página).
    paneles, acciones, hay_mapa = [], [], False
    for t in activos.values():
        if not t.panel or not tiene_capacidad(user, t.capacidad_ver, empresa):
            continue
        ctx = t.panel(user, empresa)
        if not ctx:
            continue
        if ctx.get('puntos'):
            if hay_mapa:
                ctx['puntos'] = []
            hay_mapa = True
        acciones += ctx.get('acciones', [])
        paneles.append({'tipo': t, 'html': mark_safe(render_to_string(t.plantilla_panel, ctx, request=request))})
    return render(request, 'reg_base/inicio.html', {
        'tarjetas': [t for t in tarjetas if t],
        'paneles': paneles, 'acciones': acciones, 'hay_mapa': hay_mapa,
        'puede_configurar': tiene_capacidad(user, 'reg.config.manage', empresa),
        'hoy': timezone.localdate(),
        'puede_activar': tiene_capacidad(user, 'reg.activar', empresa),
    })


@acceso_modulo('reg', 'reg.config.manage')
def config(request):
    """Configuración de Registros: los tipos de proyecto (opcionales; sin tipos, todos son del tipo por defecto)."""
    empresa = request.empresa
    form = TipoProyectoForm(request.POST or None, empresa=empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Tipo creado.')
        return redirect('reg_base:config')
    tipos = [(t, t.proyectos.filter(is_deleted=False).count()) for t in empresa.tipos_proyecto.all()]
    return render(request, 'reg_base/config.html', {'form': form, 'tipos': tipos})


@acceso_modulo('reg', 'reg.config.manage')
@require_POST
def tipo_eliminar(request, pk):
    tipo = get_object_or_404(TipoProyecto, pk=pk, empresa=request.empresa)
    if tipo.proyectos.exists():
        messages.error(request, f'«{tipo.nombre}» tiene {request.empresa.termino_proyecto_plural.lower()} asociados.')
    else:
        tipo.delete()
        messages.success(request, 'Tipo eliminado.')
    return redirect('reg_base:config')


@acceso_modulo('reg', 'reg.config.manage')
def tipos_registro(request):
    """Catálogo de TODOS los tipos de registro de la plataforma, con el interruptor que los activa en la empresa."""
    empresa = request.empresa
    activos = {t.clave for t in tipos.habilitados(empresa)}
    filas = [{'tipo': t, 'activo': t.clave in activos,
              'registros': t.modelo.objects.filter(empresa=empresa, is_deleted=False).count()} for t in tipos.todos()]
    return render(request, 'reg_base/tipos.html', {'filas': filas})


@acceso_modulo('reg', 'reg.config.manage')
@require_POST
def tipo_alternar(request, clave):
    t = tipos.tipo(clave)
    if tipos.esta_habilitado(request.empresa, clave):
        tipos.deshabilitar(request.empresa, clave)
        messages.success(request, f'«{t.nombre}» desactivado: se oculta, pero sus registros se conservan.')
    else:
        tipos.habilitar(request.empresa, clave)
        messages.success(request, f'«{t.nombre}» activado.')
    return redirect('reg_base:tipos')


@acceso_modulo('reg', 'reg.config.manage')
@require_POST
def tipo_restaurar(request, clave):
    t = tipos.tipo(clave)
    if t.restaurar is None or not tipos.esta_habilitado(request.empresa, clave):
        raise Http404
    t.restaurar(request.empresa)
    messages.success(request, f'Plantilla estándar de «{t.nombre}» restaurada.')
    return redirect('reg_base:tipos')


# ── Revisiones (tipos con `con_revisiones`) ─────────────────────────────────────────────────────────

def _registro_con_revisiones(request, clave, pk):
    from django.core.exceptions import PermissionDenied

    from . import acciones
    t = tipos.tipo_de_request(request, clave)
    if not t.con_revisiones or not tiene_capacidad(request.user, t.capacidad_ver, request.empresa):
        raise Http404
    return t, acciones.obtener_registro(request, t.modelo, pk)


@acceso_modulo('reg')
@require_POST
def revision_nueva(request, clave, pk):
    """Crea una revisión copiando la indicada; exige comentario. Se puede revisar un registro ya concluido."""
    from django.core.exceptions import ValidationError

    from . import revisiones
    t, origen = _registro_con_revisiones(request, clave, pk)
    revisiones.exigir_crear(request.user, origen)
    try:
        nuevo = revisiones.crear_revision(origen, request.user, request.POST.get('comentario'))
    except ValidationError as exc:
        messages.error(request, exc.messages[0])
        return redirect(_url_detalle(t, origen))
    messages.success(request, f'{nuevo.rev_etiqueta} creada a partir de {origen.rev_etiqueta} y marcada como vigente.')
    return redirect(_url_detalle(t, nuevo))


@acceso_modulo('reg')
@require_POST
def revision_vigente(request, clave, pk):
    from . import revisiones
    t, registro = _registro_con_revisiones(request, clave, pk)
    revisiones.exigir_elegir(request.user, registro)
    revisiones.elegir_vigente(registro)
    messages.success(request, f'{registro.rev_etiqueta} es ahora la revisión vigente.')
    return redirect(_url_detalle(t, registro))


def _url_detalle(tipo, registro):
    from django.urls import reverse
    return reverse(tipo.url_detalle, kwargs={'pk': registro.pk})
