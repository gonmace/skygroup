"""Lectura del período elegido en los filtros: mes, rango, todo o último día."""
import calendar
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta

from django.utils import timezone

MESES = ['enero', 'febrero', 'marzo', 'abril', 'mayo', 'junio', 'julio', 'agosto', 'septiembre', 'octubre',
         'noviembre', 'diciembre']
DIAS = ['lunes', 'martes', 'miércoles', 'jueves', 'viernes', 'sábado', 'domingo']


@dataclass
class Periodo:
    modo: str
    desde: date | None
    hasta: date | None
    etiqueta: str

    @property
    def inicio_dt(self):
        return timezone.make_aware(datetime.combine(self.desde, time.min)) if self.desde else None

    @property
    def fin_dt(self):
        return timezone.make_aware(datetime.combine(self.hasta, time.max)) if self.hasta else None

    def dias(self):
        d = self.desde
        while d <= self.hasta:
            yield d
            d += timedelta(days=1)


def leer(get, permitir_todo=False, hoy=None):
    """`mode`: month (año/mes), range (from/to), y —solo estadísticas— all / last. Valores inválidos caen al mes
    actual. El fin nunca pasa de hoy."""
    hoy = hoy or timezone.localdate()
    modo = get.get('mode', 'month')
    if permitir_todo and modo in ('all', 'last'):
        return Periodo(modo, None, None, 'Todo el historial' if modo == 'all' else 'Último día con datos')
    if modo == 'range':
        try:
            desde, hasta = date.fromisoformat(get.get('from', '')), date.fromisoformat(get.get('to', ''))
            hasta = max(hasta, desde)
            return Periodo('range', desde, min(hasta, max(hoy, desde)), f'{desde:%d/%m/%Y} — {hasta:%d/%m/%Y}')
        except ValueError:
            pass
    try:
        anio, mes = int(get.get('year', hoy.year)), int(get.get('month', hoy.month))
        if not (1 <= mes <= 12 and 2000 <= anio <= 2100):
            raise ValueError
    except (TypeError, ValueError):
        anio, mes = hoy.year, hoy.month
    desde = date(anio, mes, 1)
    hasta = min(date(anio, mes, calendar.monthrange(anio, mes)[1]), max(hoy, desde))
    return Periodo('month', desde, hasta, f'{MESES[mes - 1].capitalize()} {anio}')
