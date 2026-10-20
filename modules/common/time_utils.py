from datetime import datetime


def build_iso_datetime(year, month, day, hour=None, minute=0):
    """
    Construye una fecha ISO 8601 en horario local de Madrid.

    - Para datos horarios del Ayto.:
      H01 corresponde al intervalo 00:00-01:00 → hour = 1 → 00:00
    - Para datos diarios, hour=None → 00:00

    :param year: int
    :param month: int
    :param day: int
    :param hour: int | None
    :param minute: int
    :return: str ISO datetime
    """

    if hour is None:
        h = 0
    else:
        # Protección básica: nunca horas negativas
        h = max(hour - 1, 0)
        
    # h = 0 if hour is None else hour
    return datetime(year, month, day, h, minute).isoformat()

def build_daily_iso_datetime(year, month, day):
    """
    Fecha ISO para datos diarios (00:00 del día)
    """
    return datetime(year, month, day, 0, 0).isoformat()

def parse_date(fecha_texto, formato_entrada="%d/%m/%Y %H:%M", formato_salida="%Y-%m-%dT%H:%M:%S"):
    dt = datetime.strptime(fecha_texto, formato_entrada)
    return dt.strftime(formato_salida)
