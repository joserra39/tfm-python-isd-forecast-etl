import os
import csv
import json
import logging
import tempfile
import shutil
from pathlib import Path
from typing import Dict, List, Optional

import requests

logger = logging.getLogger(__name__)


class DataExtractionError(Exception):
    """Error controlado durante la extracción de datos."""
    pass


def _get_env(name: str, default: Optional[str] = None) -> Optional[str]:
    value = os.getenv(name, default)
    if value is None:
        return None
    value = value.strip()
    return value if value != "" else None


def _build_madrid_filters() -> Dict[str, str]:
    """
    Construye el bloque 'filters' para la API del Ayuntamiento de Madrid.
    Solo añade ANO, MES y DIA si vienen informados desde Jenkins/entorno.
    """
    filters = {}

    ano = _get_env("MADRID_API_ANO")
    mes = _get_env("MADRID_API_MES")
    dia = _get_env("MADRID_API_DIA")

    if ano:
        filters["ANO"] = ano
    if mes:
        filters["MES"] = mes.zfill(2)
    if dia:
        filters["DIA"] = dia.zfill(2)

    return filters


def _build_madrid_payload(offset: int = 0) -> Dict:
    resource_id = _get_env("MADRID_API_RESOURCE_ID", "201200-1-calidad-aire-horario-csv")
    limit = int(_get_env("MADRID_API_LIMIT", "100"))

    payload = {
        "resource_id": resource_id,
        "limit": limit,
        "offset": offset
    }

    filters = _build_madrid_filters()
    if filters:
        payload["filters"] = filters

    return payload


def fetch_madrid_api_data() -> List[Dict]:
    api_url = _get_env(
        "MADRID_API_URL",
        "https://datos.madrid.es/api/3/action/datastore_search"
    )
    timeout = int(_get_env("MADRID_API_TIMEOUT", "60"))
    limit = int(_get_env("MADRID_API_LIMIT", "100"))
    if limit <= 0:
        raise DataExtractionError("MADRID_API_LIMIT debe ser un entero mayor que 0")

    all_records: List[Dict] = []
    current_offset = 0
    page_number = 1

    while True:
        payload = _build_madrid_payload(offset=current_offset)

        logger.info("Extrayendo página %d desde API Madrid", page_number)
        logger.info("URL API: %s", api_url)
        logger.info("Payload enviado: %s", json.dumps(payload, ensure_ascii=False))

        try:
            response = requests.post(
                api_url,
                headers={"content-type": "application/json"},
                json=payload,
                timeout=timeout
            )
            response.raise_for_status()
        except requests.RequestException as exc:
            raise DataExtractionError(f"Error llamando a la API de Madrid: {exc}") from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise DataExtractionError("La respuesta de la API no es un JSON válido") from exc

        if not data.get("success", False):
            raise DataExtractionError(
                f"La API devolvió success=false: {json.dumps(data, ensure_ascii=False)}"
            )

        result = data.get("result", {})
        records = result.get("records", [])

        if not isinstance(records, list):
            raise DataExtractionError("El campo result.records no tiene formato lista")

        logger.info(
            "Página %d: recuperados %d registros (offset=%d, limit=%d)",
            page_number, len(records), current_offset, limit
        )

        if not records:
            logger.info("No se han recibido más registros. Fin de paginación.")
            break

        all_records.extend(records)
        current_offset += limit
        page_number += 1

    logger.info("Total de registros recuperados desde API: %d", len(all_records))
    return all_records


def write_records_to_temp_csv(
    records: List[Dict],
    dataset: str,
    output_base_dir: str
) -> List[str]:
    """
    Convierte los registros obtenidos desde la API a un CSV temporal para
    reutilizar el transformer actual, cuya firma espera una ruta de fichero CSV.
    """
    if not records:
        logger.warning("No hay registros para serializar a CSV")
        return []

    output_dir = Path(output_base_dir) / "outputs" / "tmp"
    if output_dir.exists() and output_dir.is_dir():
        shutil.rmtree(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    temp_file = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        newline="",
        suffix=".csv",
        prefix=f"{dataset}_api_",
        dir=str(output_dir),
        delete=False
    )

    fieldnames = sorted({key for record in records for key in record.keys()})

    try:
        writer = csv.DictWriter(
            temp_file,
            fieldnames=fieldnames,
            delimiter=";",
            quoting=csv.QUOTE_MINIMAL
        )
        writer.writeheader()
        for record in records:
            writer.writerow(record)
        temp_file.flush()
    finally:
        temp_file.close()

    logger.info("CSV temporal generado desde API: %s", temp_file.name)
    return [temp_file.name]


def get_input_files(directory_path: str, dataset: str) -> List[str]:
    """
    Resuelve el origen de los datos:
    - CSV: devuelve los .csv del directorio indicado
    - API: llama a la API, genera un CSV temporal y devuelve su ruta

    Variable de entorno esperada:
    - DATA_SOURCE=CSV | API
    """
    data_source = _get_env("DATA_SOURCE", "CSV").upper()

    logger.info("Origen de datos seleccionado: %s", data_source)

    if data_source == "CSV":
        csv_files = [
            os.path.join(directory_path, filename)
            for filename in os.listdir(directory_path)
            if filename.endswith(".csv")
        ]
        csv_files.sort()

        logger.info("Ficheros CSV detectados: %d", len(csv_files))
        return csv_files

    if data_source == "API":
        records = fetch_madrid_api_data()
        return write_records_to_temp_csv(records, dataset, directory_path)

    raise DataExtractionError(
        f"Origen de datos no soportado: {data_source}. Valores válidos: CSV, API"
    )