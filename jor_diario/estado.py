"""Estado de la jornada del día de una persona, compartido por «Mi jornada» y el indicador de la barra superior."""
from .models import Jornada

EN_CURSO, CERRADA, SIN_INICIAR = 'en_curso', 'cerrada', 'sin_iniciar'


def estado_del_dia(jornadas_de_hoy):
    """(estado, jornada) con las jornadas de HOY (más reciente primero): en curso si hay una abierta; cerrada si
    ya fichó y terminó; sin iniciar si no hay ninguna."""
    jornadas = list(jornadas_de_hoy)
    abierta = next((j for j in jornadas if j.estado == Jornada.Estado.EN_CURSO), None)
    if abierta:
        return EN_CURSO, abierta
    if jornadas:
        return CERRADA, jornadas[0]
    return SIN_INICIAR, None
