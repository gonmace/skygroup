"""Alcance de datos (qué registros ve cada persona) y permisos de escritura sobre un registro.

- `reg.alcance.todo`        → todos los de la empresa (Coordinador, Observador/Visita).
- `reg.alcance.contratista` → los de las personas de SU contratista (Coordinador acotado = administrador de contratista).
- ninguno                   → solo los propios (Ejecutor = ITO / Buscador).
Siempre acotado a la empresa; el superusuario ve todo."""
from cuentas.capacidades import membresia_activa, tiene_capacidad
from cuentas.roles import RolBase


def registros_visibles(user, empresa, qs):
    qs = qs.filter(empresa=empresa, is_deleted=False)
    if user.is_superuser or tiene_capacidad(user, 'reg.alcance.todo', empresa):
        return qs
    if tiene_capacidad(user, 'reg.alcance.contratista', empresa):
        m = membresia_activa(user, empresa)
        if m is not None and m.contratista_id:
            return qs.filter(
                user__membresias__empresa=empresa, user__membresias__activa=True,
                user__membresias__contratista_id=m.contratista_id,
            ).distinct()
    return qs.filter(user=user)


def puede_ver(user, registro):
    return registros_visibles(user, registro.empresa, type(registro).objects.filter(pk=registro.pk)).exists()


def puede_escribir(user, registro):
    """Cargar datos exige permiso, estar en el alcance y que el registro no esté concluido."""
    return (not registro.concluido and tiene_capacidad(user, 'reg.cargar_datos', registro.empresa)
            and puede_ver(user, registro))


def responsables_posibles(user, empresa):
    """Personas que pueden figurar como responsables (ITO/Buscador = rol base Ejecutor). Quien tiene
    alcance de contratista solo puede elegir a gente de su contratista."""
    from django.contrib.auth import get_user_model
    # Un solo filter(): todas las condiciones deben cumplirse en LA MISMA membresía (si no, una persona
    # de varias empresas podría cruzar filas de empresas distintas).
    criterios = {
        'is_active': True, 'membresias__empresa': empresa, 'membresias__activa': True,
        'membresias__rol__rol_base': RolBase.MIEMBRO,
    }
    if not user.is_superuser and not tiene_capacidad(user, 'reg.alcance.todo', empresa) \
            and tiene_capacidad(user, 'reg.alcance.contratista', empresa):
        m = membresia_activa(user, empresa)
        if m is not None and m.contratista_id:
            criterios['membresias__contratista_id'] = m.contratista_id
    return get_user_model().objects.filter(**criterios).distinct().order_by('first_name', 'email')
