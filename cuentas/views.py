from django.contrib import messages
from django.contrib.auth import get_user_model
from django.contrib.auth import views as auth_views
from django.contrib.auth import login
from django.contrib.auth.decorators import login_required
from django.core.cache import cache
from django.http import Http404
from django.db import transaction
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse_lazy
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

import secrets

from . import correos, impersonacion, nextcloud, registro as reg

from .forms import LoginForm, RegistroConfirmarForm, RegistroForm
from empresas.models import Empresa

from .models import Membresia, NextcloudConfig, NextcloudVinculo

User = get_user_model()


class LoginView(auth_views.LoginView):
    template_name = 'cuentas/login.html'
    authentication_form = LoginForm
    redirect_authenticated_user = True

    def get_context_data(self, **kwargs):
        ctx = super().get_context_data(**kwargs)
        empresa = getattr(self.request, 'empresa', None)
        ctx['registro_abierto'] = empresa is not None and reg.hay_dominios(empresa)
        config = NextcloudConfig.de(empresa)
        ctx['nextcloud'] = config if config is not None and config.disponible else None
        return ctx


class LogoutView(auth_views.LogoutView):
    """Solo POST (Django 5+)."""


class PasswordResetView(auth_views.PasswordResetView):
    template_name = 'cuentas/password_reset.html'
    email_template_name = 'cuentas/email/password_reset.txt'
    subject_template_name = 'cuentas/email/password_reset_asunto.txt'
    success_url = reverse_lazy('cuentas:password_reset_hecho')


class PasswordResetDoneView(auth_views.PasswordResetDoneView):
    template_name = 'cuentas/password_reset_hecho.html'


class PasswordResetConfirmView(auth_views.PasswordResetConfirmView):
    template_name = 'cuentas/password_reset_confirmar.html'
    success_url = reverse_lazy('cuentas:password_reset_completo')


class PasswordResetCompleteView(auth_views.PasswordResetCompleteView):
    template_name = 'cuentas/password_reset_completo.html'


def _destino(request):
    nxt = request.POST.get('next', '')
    ok = url_has_allowed_host_and_scheme(nxt, allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok and nxt else '/'


@login_required
@require_POST
def impersonar(request, pk):
    """Solo un superusuario real (no uno ya impersonando) puede iniciar."""
    if request.impersonador or not request.user.is_superuser:
        raise Http404
    objetivo = get_object_or_404(get_user_model(), pk=pk, is_active=True, is_superuser=False)
    request.session[impersonacion.SESSION_KEY] = objetivo.pk
    impersonacion.audit.warning('IMPERSONAR inicio: %s (id=%s) -> %s (id=%s)',
                                request.user.email, request.user.pk, objetivo.email, objetivo.pk)
    messages.info(request, f'Ahora ves la aplicación como {objetivo.get_full_name() or objetivo.email}.')
    return redirect('/')


@login_required
@require_POST
def impersonar_detener(request):
    real = request.impersonador
    if real is None:
        raise Http404
    impersonacion.audit.warning('IMPERSONAR fin: %s (id=%s) <- %s (id=%s)',
                                real.email, real.pk, request.user.email, request.user.pk)
    request.session.pop(impersonacion.SESSION_KEY, None)
    return redirect(_destino(request))


# ── Alta automática por dominio ───────────────────────────────────────────────

REGISTRO_INTENTOS = 5  # solicitudes por IP y hora


def _empresa_o_404(request):
    empresa = getattr(request, 'empresa', None)
    if empresa is None or not reg.hay_dominios(empresa):
        raise Http404
    return empresa


def _ip(request):
    return request.META.get('REMOTE_ADDR', '')


def registro(request):
    """Pide el correo. La respuesta es SIEMPRE la misma, exista o no la cuenta y esté o no permitido el dominio:
    no se puede usar para averiguar qué correos tienen acceso."""
    empresa = _empresa_o_404(request)
    form = RegistroForm(request.POST or None)
    if request.method == 'POST' and form.is_valid():
        clave = f'registro:{empresa.pk}:{_ip(request)}'
        cache.add(clave, 0, 3600)
        try:
            intentos = cache.incr(clave)
        except ValueError:
            intentos = 1
        if intentos > REGISTRO_INTENTOS:
            messages.error(request, 'Demasiados intentos. Vuelve a probar en una hora.')
            return render(request, 'cuentas/registro.html', {'form': form}, status=429)
        d = form.cleaned_data
        email = d['email'].strip().lower()
        if (reg.dominio_permitido(empresa, email)
                and not Membresia.objects.filter(user__email__iexact=email, empresa=empresa).exists()):
            token = reg.token_registro(email, empresa, d['first_name'], d['last_name'])
            correos.preparar_confirmacion_registro(request, email, empresa, token)()
        return render(request, 'cuentas/registro_enviado.html')
    return render(request, 'cuentas/registro.html', {'form': form})


def registro_confirmar(request, token):
    empresa = _empresa_o_404(request)
    datos = reg.leer_token(token, empresa)
    if datos is None:
        return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
    email = datos['e']
    if reg.dominio_permitido(empresa, email) is None:  # pudo bloquearse o quitarse el dominio tras enviar el enlace
        return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
    User = get_user_model()
    existente = User.objects.filter(email__iexact=email).first()
    if existente is not None:
        # Abrir el enlace demuestra que controla el correo, pero NO inicia sesión: entra con su contraseña.
        resultado = reg.registrar(empresa, email)
        if resultado is None:
            return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
        messages.success(request, 'Listo: ya tienes acceso. Inicia sesión con tu cuenta.')
        return redirect('cuentas:login')
    form = RegistroConfirmarForm(None, request.POST or None,
                                 initial={'first_name': datos.get('n', ''), 'last_name': datos.get('a', '')})
    if request.method == 'POST' and form.is_valid():
        with transaction.atomic():
            resultado = reg.registrar(empresa, email, form.cleaned_data['first_name'],
                                      form.cleaned_data['last_name'], form.cleaned_data['new_password1'])
        if resultado is None:
            return render(request, 'cuentas/registro_confirmar.html', {'invalido': True}, status=400)
        user = resultado[0]
        login(request, user, backend='cuentas.backends.EmailBackend')
        return redirect('home')
    return render(request, 'cuentas/registro_confirmar.html', {'form': form, 'email': email})


# ── Inicio de sesión con Nextcloud ────────────────────────────────────────────

NC_SESION = 'nextcloud_oauth'
NC_PRUEBA = 'nextcloud_prueba'      # resultado de «Probar inicio de sesión» (lo muestra Panel → Nextcloud, una vez)


def _destino_seguro(request, nxt):
    ok = url_has_allowed_host_and_scheme(nxt or '', allowed_hosts={request.get_host()}, require_https=request.is_secure())
    return nxt if ok and nxt else ''


def nextcloud_iniciar(request):
    """Genera el `state`, recuerda empresa y destino en la sesión y manda al usuario a autorizar en Nextcloud."""
    empresa = getattr(request, 'empresa', None)
    config = NextcloudConfig.de(empresa)
    if config is None or not config.disponible:
        raise Http404
    state = secrets.token_urlsafe(32)
    request.session[NC_SESION] = {
        'state': state,
        'next': _destino_seguro(request, request.GET.get('next')),
        'slug': empresa.slug,
    }
    return redirect(nextcloud.url_autorizar(config, request, state))


@require_POST
@login_required
def nextcloud_probar_inicio(request):
    """Prueba de la configuración: recorre el inicio de sesión de Nextcloud de verdad (valida Client ID, secret y URI de
    redirección) pero NO inicia sesión, NO vincula y NO crea nada: solo muestra lo que Nextcloud devolvió y qué pasaría.
    Solo el superusuario, con la configuración ya guardada."""
    empresa = getattr(request, 'empresa', None)
    if empresa is None or not request.user.is_superuser or getattr(request, 'impersonador', None):
        raise Http404
    config = NextcloudConfig.de(empresa)
    if not config.completo:
        messages.error(request, 'Guarda el servidor, el Client ID y el Client secret antes de probar el inicio de sesión.')
        return redirect('panel:nextcloud')
    state = secrets.token_urlsafe(32)
    request.session[NC_SESION] = {'state': state, 'next': '', 'slug': empresa.slug, 'prueba': request.user.pk}
    return redirect(nextcloud.url_autorizar(config, request, state))


def _callback_prueba(request, datos):
    """Fin de «Probar inicio de sesión»: guarda un resumen en la sesión y vuelve a la pantalla de configuración."""
    slug = datos.get('slug', '')
    empresa = Empresa.objects.filter(slug=slug).first() if slug else None
    config = NextcloudConfig.de(empresa)
    if (config is None or not config.completo or not request.user.is_authenticated or not request.user.is_superuser
            or request.user.pk != datos.get('prueba')):
        raise Http404

    def terminar(resultado):
        request.session[NC_PRUEBA] = resultado
        return redirect(f'/{slug}/config/nextcloud/')

    if request.GET.get('error'):
        return terminar({'ok': False, 'titulo': 'Nextcloud no autorizó el acceso',
                         'detalle': (request.GET.get('error_description') or request.GET.get('error'))[:200]})
    code, state = request.GET.get('code', ''), request.GET.get('state', '')
    if not code or not datos.get('state') or not secrets.compare_digest(state, datos['state']):
        return terminar({'ok': False, 'titulo': 'La solicitud no es válida o expiró', 'detalle': 'Vuelve a pulsar «Probar inicio de sesión».'})
    try:
        token, uid = nextcloud.canjear_codigo(config, request, code)
    except nextcloud.NextcloudError:
        return terminar({'ok': False, 'titulo': 'Nextcloud rechazó el intercambio del código',
                         'detalle': 'Revisa que el Client ID, el Client secret y la URI de redirección coincidan exactamente '
                                    'con el cliente OAuth registrado en Nextcloud.'})
    datos_nc = nextcloud.perfil(config, uid, token)
    return terminar({
        'ok': True, 'uid': uid, 'nombre': datos_nc['nombre'], 'email': datos_nc['email'], 'grupos': list(datos_nc['grupos']),
        'perfil_leido': bool(datos_nc['nombre'] or datos_nc['email'] or datos_nc['grupos']),
        'simulacion': nextcloud.simular_ingreso(config, uid, datos_nc),
    })


@require_POST
@login_required
def nextcloud_vincular(request):
    """Vincula la cuenta de Nextcloud con la sesión iniciada: la única forma en que una persona enlaza su uid."""
    empresa = getattr(request, 'empresa', None)
    config = NextcloudConfig.de(empresa)
    if (config is None or not config.disponible or getattr(request, 'impersonador', None)
            or request.user.is_staff or request.user.is_superuser):
        raise Http404
    state = secrets.token_urlsafe(32)
    request.session[NC_SESION] = {'state': state, 'next': '', 'slug': empresa.slug, 'vincular': request.user.pk}
    return redirect(nextcloud.url_autorizar(config, request, state))


@require_POST
@login_required
def nextcloud_desvincular(request):
    if getattr(request, 'impersonador', None):
        raise Http404
    empresa = getattr(request, 'empresa', None)
    NextcloudVinculo.objects.filter(user=request.user, empresa=empresa).delete()
    messages.success(request, 'Se desvinculó tu cuenta de Nextcloud.')
    return redirect(f'/{empresa.slug}/' if empresa else '/')


def nextcloud_callback(request):
    datos = request.session.pop(NC_SESION, None) or {}
    if datos.get('prueba'):
        return _callback_prueba(request, datos)
    slug = datos.get('slug', '')
    inicio = f'/{slug}/' if slug else '/'
    vincular_id = datos.get('vincular')
    login_url = f'/{slug}/acceso/login/' if slug else reverse_lazy('cuentas:login')

    def fallo(mensaje):
        messages.error(request, mensaje)
        return redirect(inicio if vincular_id else login_url)

    empresa = Empresa.objects.filter(slug=slug).first() if slug else None
    config = NextcloudConfig.de(empresa)
    if config is None or not config.disponible:
        raise Http404
    if request.GET.get('error'):
        return fallo('Nextcloud no autorizó el acceso. Vuelve a intentarlo.')
    code, state = request.GET.get('code', ''), request.GET.get('state', '')
    if not code or not datos.get('state') or not secrets.compare_digest(state, datos['state']):
        return fallo('La solicitud de acceso no es válida o expiró. Vuelve a intentarlo.')
    try:
        token, uid = nextcloud.canjear_codigo(config, request, code)
    except nextcloud.NextcloudError:
        return fallo('No se pudo conectar con Nextcloud. Vuelve a intentarlo en unos minutos.')
    if vincular_id:      # vincular desde una sesión ya iniciada
        if (not request.user.is_authenticated or request.user.pk != vincular_id
                or getattr(request, 'impersonador', None)):
            return fallo('Tu sesión cambió mientras vinculabas Nextcloud. Vuelve a intentarlo.')
        if NextcloudVinculo.objects.filter(empresa=empresa, uid=uid).exclude(user=request.user).exists():
            return fallo('Esa cuenta de Nextcloud ya está vinculada a otro usuario de la plataforma.')
        NextcloudVinculo.objects.update_or_create(empresa=empresa, user=request.user, defaults={'uid': uid})
        messages.success(request, 'Tu cuenta de Nextcloud quedó vinculada. Ya puedes entrar con ella.')
        return redirect(inicio)
    user = nextcloud.buscar_usuario(empresa, uid) or nextcloud.enlazar_existente(empresa, uid)
    if user is None and config.crear_cuentas:
        user, motivo = nextcloud.alta_automatica(config, uid, nextcloud.perfil(config, uid, token))
        if user is None:
            return fallo(motivo)
    if user is None:
        return fallo('Tu cuenta de Nextcloud aún no está vinculada a un usuario de la plataforma. Entra con tu correo '
                     'y contraseña y pulsa «Vincular Nextcloud» en el menú de tu usuario.')
    if not Membresia.objects.filter(user=user, empresa=empresa, activa=True).exists():
        return fallo('Tu cuenta no tiene acceso activo a esta empresa. Pide a un administrador que te lo dé.')
    login(request, user, backend='cuentas.backends.EmailBackend')
    return redirect(datos.get('next') or inicio)
