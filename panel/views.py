from collections import Counter
import os
import subprocess
import sys
from functools import wraps

from django.conf import settings
from django.contrib import messages
from django.utils.crypto import get_random_string
from django.contrib.auth.views import redirect_to_login
from django.core.exceptions import PermissionDenied
from django.db import models, transaction
from django.db.models import ProtectedError
from django.db.models import Count, F, Q
from django.db.models.functions import Concat, Lower
from django.http import Http404, JsonResponse
from django.utils import timezone
from django.utils.http import url_has_allowed_host_and_scheme
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.views.decorators.http import require_POST

from archivos.models import TareaMigracionMedia
from archivos.services import estado_almacenamiento
from archivos.storage import s3_activo
from cuentas import capacidades
from cuentas.capacidades import requiere_capacidad
from cuentas import correos
from cuentas.models import (CorreoBloqueado, CorreoConfig, CredencialesPlataforma, DominioPermitido, Membresia, NextcloudConfig, RolEmpresa,
                            RolPermiso, User)
from cuentas.services import agregar_miembro, sembrar_roles
from empresas.models import Contratista, Empresa, Sede

from .forms import (AdministradorForm, CambiarMiembroForm, ContratistaForm, CredencialesForm, SedeForm, CorreoBloqueadoForm, DominioPermitidoForm, EmpresaForm,
                    MarcaForm, MiembroForm, NextcloudForm, RolEmpresaForm)


def superusuario_requerido(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if not request.user.is_authenticated:
            return redirect_to_login(request.get_full_path())
        if not request.user.is_superuser:
            raise PermissionDenied
        return vista(request, *args, **kwargs)
    return envoltura


def empresa_requerida(vista):
    @wraps(vista)
    def envoltura(request, *args, **kwargs):
        if getattr(request, 'empresa', None) is None:
            raise Http404
        return vista(request, *args, **kwargs)
    return envoltura


# ── Plataforma (superusuario) ─────────────────────────────────────────────────

@superusuario_requerido
def empresas(request):
    lista = Empresa.objects.all()
    return render(request, 'panel/empresas.html', {'lista': lista})


@superusuario_requerido
@transaction.atomic
def empresa_editar(request, pk=None):
    empresa = get_object_or_404(Empresa, pk=pk) if pk else None
    form = EmpresaForm(request.POST or None, request.FILES or None, instance=empresa)
    if request.method == 'POST' and form.is_valid():
        nueva = empresa is None
        empresa = form.save()
        if nueva:
            sembrar_roles(empresa)
            form.save_tipos(empresa)
        messages.success(request, f'Empresa «{empresa.nombre}» guardada.')
        return redirect('panel:empresas')
    return render(request, 'panel/empresa_form.html', {'form': form, 'obj': empresa})


@superusuario_requerido
def administradores(request):
    """Superusuarios y administradores de sistema con las empresas que administra cada uno."""
    lista = (User.objects.filter(is_deleted=False).filter(Q(is_superuser=True) | Q(empresas_administradas__isnull=False))
             .distinct().prefetch_related('empresas_administradas').order_by('-is_superuser', 'email'))
    return render(request, 'panel/administradores.html', {'lista': lista})


@superusuario_requerido
@transaction.atomic
def administrador_editar(request, pk=None):
    usuario = get_object_or_404(User, pk=pk, is_deleted=False) if pk else None
    inicial = {}
    if usuario:
        inicial = {'email': usuario.email, 'first_name': usuario.first_name, 'last_name': usuario.last_name,
                   'empresas': usuario.empresas_administradas.all(), 'superusuario': usuario.is_superuser}
    form = AdministradorForm(request.POST or None, usuario=usuario, initial=inicial)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        creado = False
        if usuario is None:
            usuario, creado = User.objects.get_or_create(
                email__iexact=d['email'],
                defaults={'email': d['email'], 'first_name': d['first_name'], 'last_name': d['last_name']})
            if creado:
                usuario.set_unusable_password()
                usuario.save(update_fields=['password'])
        elif usuario.pk == request.user.pk and not d['superusuario']:
            messages.error(request, 'No puedes quitarte el rol de superusuario a ti mismo.')
            return redirect('panel:administradores')
        usuario.is_superuser = usuario.is_staff = d['superusuario']
        usuario.first_name, usuario.last_name = d['first_name'], d['last_name']
        usuario.save(update_fields=['is_superuser', 'is_staff', 'first_name', 'last_name'])
        usuario.empresas_administradas.set(d['empresas'])
        if creado and d.get('enviar_correo') and d['empresas']:
            transaction.on_commit(correos.preparar_invitacion_admin(request, usuario, d['empresas'][0]))
        messages.success(request, f'Administrador {usuario.email} guardado.')
        return redirect('panel:administradores')
    return render(request, 'panel/administrador_form.html', {'form': form, 'obj': usuario})


@require_POST
@superusuario_requerido
def administrador_quitar(request, pk):
    """Quita la administración de sistema (empresas y superusuario). La cuenta y sus membresías no se tocan."""
    usuario = get_object_or_404(User, pk=pk, is_deleted=False)
    if usuario.pk == request.user.pk:
        messages.error(request, 'No puedes quitarte tu propio rol.')
    else:
        usuario.is_superuser = usuario.is_staff = False
        usuario.save(update_fields=['is_superuser', 'is_staff'])
        usuario.empresas_administradas.clear()
        messages.success(request, f'{usuario.email} ya no es administrador.')
    return redirect('panel:administradores')


@superusuario_requerido
def almacenamiento(request):
    return render(request, 'panel/almacenamiento.html', {
        'estado': estado_almacenamiento(),
        'historial': TareaMigracionMedia.objects.all()[:10],
        's3': s3_activo(),
    })


@superusuario_requerido
@require_POST
def almacenamiento_migrar(request):
    if not s3_activo():
        messages.error(request, 'Activa el modo S3 en Admin → Almacenamiento de media / CDN primero.')
        return redirect('panel:almacenamiento')
    if TareaMigracionMedia.objects.filter(estado='EN_CURSO').exists():
        messages.warning(request, 'Ya hay una migración en curso.')
        return redirect('panel:almacenamiento')
    args = [sys.executable, str(os.path.join(settings.BASE_DIR, 'manage.py')), 'media_a_cdn']
    if request.POST.get('dry_run'):
        args.append('--dry-run')
    if request.POST.get('borrar_local'):
        args.append('--borrar-local')
    antiguedad = request.POST.get('antiguedad', '').strip()
    if antiguedad.isdigit() and int(antiguedad) > 0:
        args += ['--antiguedad', antiguedad]
    # Proceso independiente: sobrevive a la request y al worker de gunicorn.
    subprocess.Popen(args, cwd=settings.BASE_DIR, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                     start_new_session=True)
    messages.success(request, 'Migración iniciada. Actualiza esta página para ver el progreso.')
    return redirect('panel:almacenamiento')


@superusuario_requerido
def correo(request):
    """Servidor SMTP de la plataforma (todas las empresas). Solo el superusuario."""
    from .forms import CorreoForm
    form = CorreoForm(request.POST or None, instance=CorreoConfig.de())
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuración de correo guardada.')
        return redirect('panel:correo')
    return render(request, 'panel/correo.html', {
        'form': form, 'destino_prueba': request.user.email,
        # Servidor de respaldo (.env): solo si el servidor define uno; si no, el correo va a la consola.
        'env_host': settings.EMAIL_HOST if 'smtp' in getattr(settings, 'EMAIL_BACKEND_BASE', '') else '',
    })


@require_POST
@superusuario_requerido
def correo_probar(request):
    """«Probar conexión» y «Enviar correo de prueba» con lo que hay en el formulario (aunque no esté guardado)."""
    from django.core.exceptions import ValidationError
    from django.core.validators import validate_email

    from cuentas import correo_backend as cb
    guardada = CorreoConfig.de()
    post = request.POST
    try:
        puerto = int(post.get('puerto') or 0)
    except ValueError:
        puerto = 0
    seguridad = post.get('seguridad') if post.get('seguridad') in dict(CorreoConfig.Seguridad.choices) else 'starttls'
    cfg = {'host': (post.get('host') or '').strip(), 'puerto': puerto, 'seguridad': seguridad,
           'usuario': (post.get('usuario') or '').strip(), 'password': post.get('password') or guardada.password,
           'remitente': (post.get('remitente') or '').strip(), 'remitente_nombre': (post.get('remitente_nombre') or '').strip()}
    if not cfg['host']:
        return JsonResponse({'ok': False, 'mensaje': 'Indica el servidor SMTP.'})
    if not 1 <= puerto <= 65535:
        return JsonResponse({'ok': False, 'mensaje': 'El puerto debe estar entre 1 y 65535.'})
    if post.get('accion') == 'envio':
        destino = (post.get('destino') or '').strip()
        try:
            validate_email(destino)
        except ValidationError:
            return JsonResponse({'ok': False, 'mensaje': 'Escribe un correo de destino válido.'})
        ok, mensaje = cb.enviar_prueba(cfg, destino)
    else:
        ok, mensaje = cb.probar_conexion(cfg)
    return JsonResponse({'ok': ok, 'mensaje': mensaje})


@superusuario_requerido
def credenciales(request):
    """Credenciales de servicios externos de la plataforma (todas las empresas). Solo el superusuario.
    Hoy: la clave de Google Maps (Static Maps API) con la que se generan las imágenes de los mapas."""
    from reg_actividades import mapas
    cred = CredencialesPlataforma.de()
    form = CredencialesForm(request.POST or None, instance=cred)
    if request.method == 'POST' and form.is_valid():
        if request.POST.get('accion') == 'probar':
            # Prueba la clave escrita (o, vacía, la guardada) sin guardarla.
            clave = form.cleaned_data['google_maps_api_key'] or mapas.clave_google()
            if not clave:
                messages.error(request, 'No hay ninguna clave que probar.')
            else:
                ok, mensaje = mapas.probar_clave(clave)
                (messages.success if ok else messages.error)(request, mensaje)
            return render(request, 'panel/credenciales.html', {'form': CredencialesForm(instance=cred), **_ctx_credenciales(cred)})
        form.save()
        messages.success(request, 'Credenciales guardadas.')
        return redirect('panel:credenciales')
    return render(request, 'panel/credenciales.html', {'form': form, **_ctx_credenciales(cred)})


def _ctx_credenciales(cred):
    from django.conf import settings
    clave = cred.google_maps_api_key
    return {
        'maps_guardada': bool(clave), 'maps_final': clave[-4:] if clave else '',
        'maps_env': bool(getattr(settings, 'GOOGLE_MAPS_API_KEY', '')) and not clave,
    }


# ── Configuración de la empresa ───────────────────────────────────────────────

@empresa_requerida
@requiere_capacidad('empresas.marca.manage')
def marca(request):
    form = MarcaForm(request.POST or None, request.FILES or None, instance=request.empresa)
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Marca actualizada.')
        return redirect('panel:marca')
    return render(request, 'panel/marca.html', {'form': form})


# Columnas ordenables de la tabla de usuarios: clave de la URL → (título, expresión de orden).
COLUMNAS_MIEMBROS = [
    ('usuario', 'Usuario', Lower(Concat('user__first_name', 'user__last_name', 'user__email'))),
    ('telefono', 'Teléfono', Lower('user__telefono')),
    ('rol', 'Cargo', Lower('rol__nombre')),
    ('puesto', 'Puesto', Lower('perfil_jor__cargo')),
    ('contratista', 'Contratista', Lower('contratista__nombre')),
    ('sede', 'Sede', Lower('sede__nombre')),
    ('activo', 'Activo', F('activa')),
]


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def miembros(request):
    lista = (Membresia.objects.filter(empresa=request.empresa, user__is_deleted=False)
             .select_related('user', 'rol', 'contratista', 'sede', 'perfil_jor'))
    orden = request.GET.get('orden', '')
    descendente = request.GET.get('dir') == 'desc'
    expresion = {k: e for k, _, e in COLUMNAS_MIEMBROS}.get(orden)
    if expresion is None:
        orden = ''
        lista = lista.order_by('-activa', 'user__email')
    else:
        lista = lista.order_by(expresion.desc(nulls_last=True) if descendente else expresion.asc(nulls_last=True),
                               'user__email')
    empresa = request.empresa
    con_puesto = empresa.tiene_modulo('jor')   # el puesto vive en el perfil de Jornadas
    columnas = []
    for clave, titulo, _ in COLUMNAS_MIEMBROS:
        if clave == 'puesto' and not con_puesto:
            continue
        siguiente = 'desc' if (orden == clave and not descendente) else 'asc'
        columnas.append({
            'titulo': titulo, 'url': f'?orden={clave}&dir={siguiente}',
            'activa': orden == clave, 'desc': orden == clave and descendente,
        })
    puestos = []
    if con_puesto:   # los ya usados, para sugerirlos y evitar variantes del mismo puesto
        puestos = sorted({m.perfil_jor.cargo for m in lista if getattr(m, 'perfil_jor', None) and m.perfil_jor.cargo})
    lista = list(lista)
    activos = [m for m in lista if m.activa]   # los desgloses por cargo y por sede cuentan solo a quienes están activos
    resumen = {
        'total': len(lista), 'activos': len(activos),
        'por_cargo': sorted(Counter(m.rol.nombre for m in activos).items()),
        'por_sede': sorted(Counter(m.sede.nombre if m.sede else 'Sin sede' for m in activos).items(),
                           key=lambda x: (x[0] == 'Sin sede', x[0])),
    }
    eliminados = None
    if request.user.is_superuser:  # papelera: solo la ve el superusuario
        eliminados = (Membresia.objects.filter(empresa=empresa, user__is_deleted=True)
                      .select_related('user', 'rol').order_by('-user__eliminado_en'))
    # Administradores que no son miembros: los superusuarios (de todas las empresas) y los administradores de esta empresa.
    administradores = (User.objects.filter(is_deleted=False).filter(Q(is_superuser=True) | Q(empresas_administradas=empresa))
                       .exclude(membresias__empresa=empresa).distinct().order_by('-is_superuser', 'email'))
    return render(request, 'panel/miembros.html', {
        'administradores': administradores,
        'resumen': resumen, 'con_puesto': con_puesto, 'puestos': puestos, 'eliminados': eliminados, 'lista': lista, 'columnas': columnas, 'roles': empresa.roles.filter(activo=True),
        'contratistas': empresa.contratistas.filter(is_deleted=False, activo=True),
        'sedes': empresa.sedes.filter(activo=True),
    })


def _destino(request, defecto):
    """Adónde volver tras guardar: el `next` del formulario si es una ruta interna segura."""
    destino = request.POST.get('next') or request.GET.get('next') or ''
    if destino and url_has_allowed_host_and_scheme(destino, allowed_hosts={request.get_host()},
                                                   require_https=request.is_secure()):
        return destino
    return defecto


def _volver_o_json(request, defecto):
    """Fin de una acción de la tabla de usuarios. Con AJAX (`X-Requested-With`) responde JSON con los mensajes y la
    página NO se recarga (así la tabla conserva el desplazamiento); sin AJAX, redirige como siempre."""
    if request.headers.get('X-Requested-With') == 'XMLHttpRequest':
        avisos = [{'texto': str(m), 'tipo': m.tags} for m in messages.get_messages(request)]
        return JsonResponse({'ok': not any(a['tipo'] == 'error' for a in avisos), 'mensajes': avisos})
    return redirect(_destino(request, defecto))


def _puede_desactivar(request, membresia):
    """Nadie puede desactivarse a sí mismo."""
    return membresia.user_id != request.user.pk


_CARACTERES_CLAVE = 'abcdefghijkmnpqrstuvwxyzABCDEFGHJKLMNPQRSTUVWXYZ23456789'    # sin caracteres ambiguos (0/O, 1/l/I)


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
@transaction.atomic
def miembro_nuevo(request):
    form = MiembroForm(request.POST or None, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        d = form.cleaned_data
        user, creado = User.objects.get_or_create(
            email__iexact=d['email'],
            defaults={'email': d['email'], 'first_name': d['first_name'], 'last_name': d['last_name']},
        )
        acceso = d['acceso']
        clave = get_random_string(12, _CARACTERES_CLAVE) if creado and acceso == 'clave' else ''
        if creado:
            user.set_password(clave) if clave else user.set_unusable_password()
            user.save(update_fields=['password'])
        if Membresia.objects.filter(user=user, empresa=request.empresa).exists():
            messages.warning(request, f'{user.email} ya pertenece a la empresa.')
            return redirect(_destino(request, 'panel:miembros'))
        membresia = agregar_miembro(user, request.empresa, d['rol'], d['contratista'], d['sede'])
        volver = _destino(request, 'panel:miembros')
        if clave:     # se muestra aquí, una sola vez y sin pasar por los mensajes (que pueden viajar en una cookie)
            respuesta = render(request, 'panel/miembro_credenciales.html', {'user_nuevo': user, 'clave': clave, 'volver': volver})
            respuesta['Cache-Control'] = 'no-store'
            return respuesta
        if acceso == 'correo':
            preparar = correos.preparar_invitacion if creado else correos.preparar_aviso_agregado
            transaction.on_commit(preparar(request, user, membresia))
            messages.success(request, f'{user.email} agregado · correo enviado.')
        elif creado:      # nextcloud
            messages.success(request, f'{user.email} agregado. Entrará con Nextcloud: su usuario allí debe ser este correo.')
        else:
            messages.success(request, f'{user.email} agregado.')
        return redirect(volver)
    return render(request, 'panel/miembro_form.html', {'form': form, 'obj': None, 'volver': _destino(request, reverse('panel:miembros'))})


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def miembro_editar(request, pk):
    membresia = get_object_or_404(Membresia.objects.select_related('user', 'rol'), pk=pk, empresa=request.empresa)
    form = CambiarMiembroForm(
        request.POST or None, empresa=request.empresa,
        puede_admin=request.user.is_superuser and membresia.user_id != request.user.pk,
        initial={'rol': membresia.rol, 'activa': membresia.activa, 'contratista': membresia.contratista, 'sede': membresia.sede,
                 'first_name': membresia.user.first_name, 'last_name': membresia.user.last_name,
                 'telefono': membresia.user.telefono},
    )
    if request.method == 'POST' and form.is_valid():
        if not _puede_desactivar(request, membresia) and not form.cleaned_data['activa']:
            messages.error(request, 'No puedes desactivarte a ti mismo.')
        elif not form.cleaned_data['rol']:
            # Cargo vacío (solo superusuario, ver el formulario): pasa a administrador de sistema y deja de ser miembro.
            persona = membresia.user
            try:
                with transaction.atomic():
                    persona.first_name = form.cleaned_data['first_name']
                    persona.last_name = form.cleaned_data['last_name']
                    persona.telefono = form.cleaned_data['telefono']
                    persona.save(update_fields=['first_name', 'last_name', 'telefono'])
                    persona.empresas_administradas.add(request.empresa)
                    membresia.delete()
                messages.success(request, f'{persona.email} ahora es administrador de {request.empresa}.')
                return redirect('panel:miembros')
            except ProtectedError:
                messages.error(request, 'No se pudo convertir en administrador: la membresía tiene registros asociados.')
        else:
            membresia.rol = form.cleaned_data['rol']
            membresia.contratista = form.cleaned_data['contratista']
            membresia.sede = form.cleaned_data['sede']
            membresia.activa = form.cleaned_data['activa']
            membresia.save()
            persona = membresia.user
            persona.first_name = form.cleaned_data['first_name']
            persona.last_name = form.cleaned_data['last_name']
            persona.telefono = form.cleaned_data['telefono']
            persona.save(update_fields=['first_name', 'last_name', 'telefono'])
            messages.success(request, 'Miembro actualizado.')
            return redirect('panel:miembros')
    return render(request, 'panel/miembro_form.html', {'form': form, 'obj': membresia, 'volver': reverse('panel:miembros')})


@require_POST
@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def miembro_rapido(request, pk):
    """Cambios de una sola cosa desde la tabla de usuarios: cargo, puesto, contratista, sede o activar/desactivar."""
    empresa = request.empresa
    membresia = get_object_or_404(Membresia.objects.select_related('user', 'rol'), pk=pk, empresa=empresa)
    if 'rol' in request.POST and not request.POST['rol'] and request.user.is_superuser:
        # Cargo vacío (solo superusuario): pasa a administrador de sistema de la empresa y deja de ser miembro.
        if membresia.user_id == request.user.pk:
            messages.error(request, 'No puedes cambiar tu propio cargo.')
        else:
            try:
                with transaction.atomic():
                    membresia.user.empresas_administradas.add(empresa)
                    membresia.delete()
                messages.success(request, f'{membresia.user.email} ahora es administrador de {empresa}.')
            except ProtectedError:
                messages.error(request, 'No se pudo convertir en administrador: la membresía tiene registros asociados.')
    elif 'rol' in request.POST:
        rol = empresa.roles.filter(activo=True, pk=request.POST['rol'] or 0).first()
        if rol is None:
            messages.error(request, 'Cargo no válido.')
        else:
            membresia.rol = rol
            membresia.save(update_fields=['rol'])
            messages.success(request, f'Cargo de {membresia.user.email} actualizado.')
    elif 'puesto' in request.POST:
        from jor_empleados.models import Perfil
        perfil = Perfil.de(membresia)
        from jor_empleados.models import quitar_cargo
        perfil.cargo = quitar_cargo(request.POST['puesto'], membresia.rol.nombre)[:150]
        perfil.save(update_fields=['cargo'])
        messages.success(request, f'Puesto de {membresia.user.email} actualizado.')
    elif 'contratista' in request.POST:
        valor = request.POST['contratista']
        contratista = empresa.contratistas.filter(is_deleted=False, pk=valor).first() if valor else None
        if valor and contratista is None:
            messages.error(request, 'Contratista no válido.')
        else:
            membresia.contratista = contratista
            membresia.save(update_fields=['contratista'])
            messages.success(request, f'Contratista de {membresia.user.email} actualizado.')
    elif 'sede' in request.POST:
        valor = request.POST['sede']
        sede = empresa.sedes.filter(pk=valor).first() if valor.isdigit() else None
        if valor and sede is None:
            messages.error(request, 'Sede no válida.')
        else:
            membresia.sede = sede
            membresia.save(update_fields=['sede'])
            messages.success(request, f'Sede de {membresia.user.email} actualizada.')
    elif 'alternar_activa' in request.POST:
        if membresia.activa and not _puede_desactivar(request, membresia):
            messages.error(request, 'No puedes desactivarte a ti mismo.')
        else:
            membresia.activa = not membresia.activa
            membresia.save(update_fields=['activa'])
            messages.success(request, f'{membresia.user.email} {"activado" if membresia.activa else "desactivado"}.')
    return _volver_o_json(request, 'panel:miembros')


@require_POST
@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def miembro_reinvitar(request, pk):
    """Reenvía la invitación a quien aún no eligió contraseña."""
    membresia = get_object_or_404(Membresia.objects.select_related('user', 'rol', 'empresa'), pk=pk, empresa=request.empresa)
    if membresia.user.has_usable_password():
        messages.warning(request, f'{membresia.user.email} ya tiene contraseña.')
    elif not membresia.user.is_active:
        messages.error(request, 'La cuenta está bloqueada.')
    else:
        correos.preparar_invitacion(request, membresia.user, membresia)()
        messages.success(request, f'Invitación reenviada a {membresia.user.email}.')
    return _volver_o_json(request, 'panel:miembros')


def _protegido(request, user):
    """Cuentas sobre las que no se puede bloquear ni eliminar: la propia y otros superusuarios."""
    return user.pk == request.user.pk or user.is_superuser or request.impersonador is not None


@require_POST
@empresa_requerida
@superusuario_requerido
def miembro_bloquear(request, pk):
    """Bloqueo global de la cuenta (todas las empresas): alterna `is_active`."""
    membresia = get_object_or_404(Membresia.objects.select_related('user'), pk=pk, empresa=request.empresa)
    user = membresia.user
    if _protegido(request, user):
        messages.error(request, 'No se puede bloquear esta cuenta.')
    else:
        user.is_active = not user.is_active
        user.save(update_fields=['is_active'])
        messages.success(request, f'Cuenta de {user.email} {"desbloqueada" if user.is_active else "bloqueada en todas las empresas"}.')
    return _volver_o_json(request, 'panel:miembros')


@empresa_requerida
@superusuario_requerido
def miembro_eliminar(request, pk):
    """Elimina la CUENTA (todas las empresas) con borrado lógico: queda bloqueada, sin membresías activas y fuera de
    las listas, pero conserva todo su historial (tickets, jornadas, mensajes…). Solo superusuario; se restaura desde
    la papelera de Miembros."""
    membresia = get_object_or_404(Membresia.objects.select_related('user'), pk=pk, empresa=request.empresa,
                                  user__is_deleted=False)
    user = membresia.user
    if _protegido(request, user):
        messages.error(request, 'No se puede eliminar esta cuenta.')
        return redirect('panel:miembros')
    if request.method == 'POST':
        with transaction.atomic():
            user.is_deleted, user.is_active, user.eliminado_en = True, False, timezone.now()
            user.save(update_fields=['is_deleted', 'is_active', 'eliminado_en'])
            user.membresias.update(activa=False)
        messages.success(request, f'Cuenta de {user.email} eliminada. Puedes restaurarla desde «Eliminados».')
        return redirect('panel:miembros')
    return render(request, 'panel/miembro_eliminar.html', {
        'obj': membresia, 'empresas': user.membresias.select_related('empresa'),
    })


@require_POST
@empresa_requerida
@superusuario_requerido
def miembro_restaurar(request, pk):
    """Restaura una cuenta eliminada: vuelve a estar activa, con sus membresías reactivadas."""
    membresia = get_object_or_404(Membresia.objects.select_related('user'), pk=pk, empresa=request.empresa,
                                  user__is_deleted=True)
    user = membresia.user
    with transaction.atomic():
        user.is_deleted, user.is_active, user.eliminado_en = False, True, None
        user.save(update_fields=['is_deleted', 'is_active', 'eliminado_en'])
        user.membresias.update(activa=True)
    messages.success(request, f'Cuenta de {user.email} restaurada.')
    return redirect('panel:miembros')


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def acceso(request):
    """Alta automática: dominios permitidos y correos bloqueados de la empresa."""
    empresa = request.empresa
    form_dominio = DominioPermitidoForm(empresa=empresa)
    form_correo = CorreoBloqueadoForm(empresa=empresa)
    if request.method == 'POST':
        if 'dominio' in request.POST:
            form_dominio = DominioPermitidoForm(request.POST, empresa=empresa)
            if form_dominio.is_valid():
                form_dominio.save()
                messages.success(request, f'Dominio @{form_dominio.instance.dominio} habilitado.')
                return redirect('panel:acceso')
        elif 'email' in request.POST:
            form_correo = CorreoBloqueadoForm(request.POST, empresa=empresa)
            if form_correo.is_valid():
                form_correo.save()
                messages.success(request, f'{form_correo.instance.email} bloqueado para el alta automática.')
                return redirect('panel:acceso')
    return render(request, 'panel/acceso.html', {
        'form_dominio': form_dominio, 'form_correo': form_correo,
        'dominios': empresa.dominios_permitidos.select_related('rol'),
        'bloqueados': empresa.correos_bloqueados.all(),
    })


@require_POST
@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def acceso_dominio_alternar(request, pk):
    dominio = get_object_or_404(DominioPermitido, pk=pk, empresa=request.empresa)
    dominio.activo = not dominio.activo
    dominio.save(update_fields=['activo'])
    return redirect('panel:acceso')


@require_POST
@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def acceso_dominio_eliminar(request, pk):
    get_object_or_404(DominioPermitido, pk=pk, empresa=request.empresa).delete()
    messages.success(request, 'Dominio quitado.')
    return redirect('panel:acceso')


@require_POST
@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def acceso_correo_eliminar(request, pk):
    get_object_or_404(CorreoBloqueado, pk=pk, empresa=request.empresa).delete()
    messages.success(request, 'Correo desbloqueado.')
    return redirect('panel:acceso')


@superusuario_requerido
@empresa_requerida
def nextcloud(request):
    """Inicio de sesión con el Nextcloud PROPIO de la empresa. Solo el superusuario: el servidor y el cliente OAuth
    deciden quién entra a la empresa, así que un administrador de la empresa no los puede cambiar."""
    from cuentas.nextcloud import redirect_uri
    form = NextcloudForm(request.POST or None, instance=NextcloudConfig.de(request.empresa))
    if request.method == 'POST' and form.is_valid():
        form.save()
        messages.success(request, 'Configuración de Nextcloud guardada.')
        return redirect('panel:nextcloud')
    from cuentas.views import NC_PRUEBA
    return render(request, 'panel/nextcloud.html', {
        'form': form, 'redirect_uri': redirect_uri(request),
        'prueba': request.session.pop(NC_PRUEBA, None),                    # resultado de «Probar inicio de sesión» (una vez)
        'config_completa': NextcloudConfig.de(request.empresa).completo,   # lo GUARDADO: el flujo OAuth usa lo guardado
    })


@require_POST
@superusuario_requerido
@empresa_requerida
def nextcloud_probar(request):
    """«Probar conexión»: comprueba el servidor (URL, Nextcloud accesible, app OAuth 2.0) con lo que hay en el formulario,
    sin guardar y sin enviar credenciales."""
    from cuentas import nextcloud as nc
    url = request.POST.get('servidor_url') or NextcloudConfig.de(request.empresa).servidor_url
    return JsonResponse({'resultados': nc.probar_servidor(url)})


@empresa_requerida
@requiere_capacidad('cuentas.roles.manage')
def roles(request):
    lista = request.empresa.roles.all().prefetch_related('membresias')
    return render(request, 'panel/roles.html', {'lista': lista})


@empresa_requerida
@requiere_capacidad('cuentas.roles.manage')
def rol_editar(request, pk=None):
    rol = get_object_or_404(RolEmpresa, pk=pk, empresa=request.empresa) if pk else None
    form = RolEmpresaForm(request.POST or None, instance=rol, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        rol = form.save()
        messages.success(request, f'Cargo «{rol.nombre}» guardado.')
        return redirect('panel:rol_matriz', pk=rol.pk)
    return render(request, 'panel/rol_form.html', {'form': form, 'obj': rol})


def _refs_protegidas(rol):
    """(modelo, campo) de cada FK PROTECT que apunta al cargo (membresías, dominios, excepciones por módulo…)."""
    return [(r.related_model, r.field.name) for r in RolEmpresa._meta.get_fields(include_hidden=True)
            if r.auto_created and r.one_to_many and r.field.remote_field.on_delete is models.PROTECT]


@empresa_requerida
@requiere_capacidad('cuentas.roles.manage')
def rol_eliminar(request, pk):
    """Elimina un cargo. Si está en uso, pide a qué otro cargo pasar a todas esas personas (y dominios) y lo mueve en bloque."""
    rol = get_object_or_404(RolEmpresa, pk=pk, empresa=request.empresa)
    refs = _refs_protegidas(rol)
    n_miembros = rol.membresias.count()
    en_uso = sum(m.objects.filter(**{c: rol}).count() for m, c in refs)
    destinos = request.empresa.roles.filter(activo=True).exclude(pk=rol.pk).order_by('orden', 'nombre')
    if request.method == 'POST':
        destino = None
        if en_uso:
            destino = destinos.filter(pk=request.POST.get('destino') or 0).first()
            if destino is None:
                messages.error(request, f'«{rol.nombre}» está en uso: elige a qué cargo pasar a sus miembros.')
                return redirect('panel:rol_eliminar', pk=rol.pk)
        nombre = rol.nombre
        with transaction.atomic():
            for modelo, campo in refs:
                modelo.objects.filter(**{campo: rol}).update(**{campo: destino})
            rol.delete()
        extra = f' {n_miembros} miembro{"s" if n_miembros != 1 else ""} pasaron a «{destino.nombre}».' if n_miembros else ''
        messages.success(request, f'Cargo «{nombre}» eliminado.{extra}')
        return redirect('panel:roles')
    return render(request, 'panel/rol_eliminar.html', {
        'obj': rol, 'n_miembros': n_miembros, 'en_uso': en_uso, 'destinos': destinos})


def _modulos_visibles_matriz(empresa):
    """Módulos cuyas capacidades muestra (y por tanto puede guardar) la matriz de la empresa."""
    return set(empresa.modulos or []) | {'cuentas', 'empresas', 'proyectos', 'mje_mensajes'}


@empresa_requerida
@requiere_capacidad('cuentas.roles.manage')
@transaction.atomic
def rol_matriz(request, pk):
    """Tablero de capacidades de un rol: solo se guardan las DIFERENCIAS con el default.

    Solo se tocan las capacidades de los módulos visibles: las de un módulo desactivado no llegan en el
    POST y conservan sus excepciones guardadas (si no, al reactivarlo el rol quedaría sin permisos)."""
    rol = get_object_or_404(RolEmpresa, pk=pk, empresa=request.empresa)
    todas = capacidades.todas()
    modulos_activos = _modulos_visibles_matriz(request.empresa)
    if request.method == 'POST':
        visibles = {clave: cap for clave, cap in todas.items() if cap.modulo in modulos_activos}
        marcadas = set(request.POST.getlist('cap')) & set(visibles)
        rol.permisos.filter(capacidad__in=visibles).delete()
        RolPermiso.objects.bulk_create([
            RolPermiso(rol_empresa=rol, capacidad=clave, habilitado=(clave in marcadas))
            for clave, cap in visibles.items()
            if (clave in marcadas) != (rol.rol_base in cap.roles_default)
        ])
        capacidades.invalidar_rol(rol.pk)
        messages.success(request, 'Permisos guardados.')
        return redirect('panel:roles')
    efectivas = capacidades._conjunto_rol(rol)
    grupos = [
        {'modulo': modulo, 'caps': [{'clave': c.clave, 'etiqueta': c.etiqueta, 'activa': c.clave in efectivas,
                                     'por_defecto': rol.rol_base in c.roles_default} for c in caps]}
        for modulo, caps in capacidades.agrupadas_por_modulo().items() if modulo in modulos_activos
    ]
    return render(request, 'panel/rol_matriz.html', {'rol': rol, 'grupos': grupos})


# ── Contratistas (organizaciones dentro de la empresa) ────────────────────────

@empresa_requerida
@requiere_capacidad('empresas.contratistas.manage')
def contratistas(request):
    lista = (Contratista.objects.filter(empresa=request.empresa, is_deleted=False)
             .annotate(num_miembros=Count('membresias', filter=Q(membresias__activa=True))))
    eliminados = None
    if request.user.is_superuser:  # papelera: solo la ve el superusuario
        eliminados = Contratista.objects.filter(empresa=request.empresa, is_deleted=True).order_by('-actualizado')
    return render(request, 'panel/contratistas.html', {'lista': lista, 'eliminados': eliminados})


@empresa_requerida
@requiere_capacidad('empresas.contratistas.manage')
def contratista_editar(request, pk=None):
    obj = get_object_or_404(Contratista, pk=pk, empresa=request.empresa, is_deleted=False) if pk else None
    form = ContratistaForm(request.POST or None, instance=obj, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Contratista «{obj.nombre}» guardado.')
        return redirect('panel:contratistas')
    return render(request, 'panel/contratista_form.html', {'form': form, 'obj': obj})


@empresa_requerida
@requiere_capacidad('empresas.contratistas.manage')
@require_POST
def contratista_eliminar(request, pk):
    obj = get_object_or_404(Contratista, pk=pk, empresa=request.empresa, is_deleted=False)
    if obj.membresias.filter(activa=True).exists():
        messages.error(request, f'«{obj.nombre}» tiene miembros activos; muévelos o desactívalos primero.')
    else:
        obj.is_deleted = True  # borrado lógico: libera el código y conserva el historial
        obj.activo = False
        obj.save(update_fields=['is_deleted', 'activo', 'actualizado'])
        messages.success(request, f'Contratista «{obj.nombre}» eliminado.')
    return redirect('panel:contratistas')


@empresa_requerida
@superusuario_requerido
def contratista_eliminar_definitivo(request, pk):
    """Borrado físico, solo superusuario y solo desde la papelera. Los registros ligados (visitas de
    Construcción) se conservan con el contratista vacío; la pantalla avisa cuántos son antes de confirmar.
    Con membresías ligadas (aunque inactivas) se rechaza: dejarlas sin contratista ampliaría su alcance."""
    obj = get_object_or_404(Contratista, pk=pk, empresa=request.empresa, is_deleted=True)
    n_registros = obj.reg_construcciones.count()
    n_membresias = obj.membresias.count()
    if request.method == 'POST':
        if n_membresias:
            messages.error(request, f'«{obj.nombre}» aún tiene {n_membresias} miembro(s) ligado(s); muévelos a otro contratista primero.')
            return redirect('panel:contratistas')
        nombre = obj.nombre
        with transaction.atomic():
            obj.delete()  # reg_construcciones.contratista → SET_NULL
        messages.success(request, f'Contratista «{nombre}» eliminado definitivamente.')
        return redirect('panel:contratistas')
    return render(request, 'panel/contratista_eliminar.html', {
        'obj': obj, 'n_registros': n_registros, 'n_membresias': n_membresias,
    })


@empresa_requerida
@requiere_capacidad('empresas.contratistas.manage')
@require_POST
def contratista_alternar(request, pk):
    """Activa o desactiva un contratista desde el interruptor de la tabla."""
    obj = get_object_or_404(Contratista, pk=pk, empresa=request.empresa, is_deleted=False)
    obj.activo = not obj.activo
    obj.save(update_fields=['activo', 'actualizado'])
    messages.success(request, f'Contratista «{obj.nombre}» {"activado" if obj.activo else "desactivado"}.')
    return redirect('panel:contratistas')


@empresa_requerida
@requiere_capacidad('empresas.contratistas.manage')
@require_POST
def contratista_restaurar(request, pk):
    if not request.user.is_superuser:
        raise Http404
    obj = get_object_or_404(Contratista, pk=pk, empresa=request.empresa, is_deleted=True)
    if Contratista.objects.filter(empresa=request.empresa, is_deleted=False, codigo__iexact=obj.codigo).exists():
        messages.error(request, f'No se puede restaurar «{obj.nombre}»: ya existe un contratista activo con el código {obj.codigo}.')
    else:
        obj.is_deleted = False
        obj.activo = True
        obj.save(update_fields=['is_deleted', 'activo', 'actualizado'])
        messages.success(request, f'Contratista «{obj.nombre}» restaurado.')
    return redirect('panel:contratistas')


# ── Sedes (opcionales; cada miembro puede tener una) ──────────────────────────

@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def sedes(request):
    lista = request.empresa.sedes.annotate(num_miembros=Count('membresias', filter=Q(membresias__activa=True)))
    return render(request, 'panel/sedes.html', {'lista': lista})


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
def sede_editar(request, pk=None):
    obj = get_object_or_404(Sede, pk=pk, empresa=request.empresa) if pk else None
    form = SedeForm(request.POST or None, instance=obj, empresa=request.empresa)
    if request.method == 'POST' and form.is_valid():
        obj = form.save()
        messages.success(request, f'Sede «{obj.nombre}» guardada.')
        return redirect('panel:sedes')
    return render(request, 'panel/sede_form.html', {'form': form, 'obj': obj})


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
@require_POST
def sede_eliminar(request, pk):
    obj = get_object_or_404(Sede, pk=pk, empresa=request.empresa)
    if obj.membresias.exists():
        messages.error(request, f'«{obj.nombre}» tiene miembros; muévelos a otra sede o desactívala.')
    else:
        obj.delete()
        messages.success(request, f'Sede «{obj.nombre}» eliminada.')
    return redirect('panel:sedes')


@empresa_requerida
@requiere_capacidad('cuentas.usuarios.manage')
@require_POST
def sede_alternar(request, pk):
    obj = get_object_or_404(Sede, pk=pk, empresa=request.empresa)
    obj.activo = not obj.activo
    obj.save(update_fields=['activo'])
    messages.success(request, f'Sede «{obj.nombre}» {"activada" if obj.activo else "desactivada"}.')
    return redirect('panel:sedes')
