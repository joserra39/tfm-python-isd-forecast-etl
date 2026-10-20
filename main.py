import sys
import os
import json
import time
import importlib
import logging
import tc_etl_lib as tc
from modules.common.auth_keycloak import KeycloakAuthManager
from modules.common.extractor import get_input_files, DataExtractionError
from pathlib import Path

# --------------------------------------------------
# Load .env only in local environments
# --------------------------------------------------
try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

# --------------------------------------------------
# Logging configuration
# --------------------------------------------------
logging.basicConfig(
    level=logging.DEBUG,
    format="%(asctime)s [%(levelname)s] %(message)s"
)
logger = logging.getLogger(__name__)

# --------------------------------------------------
# Helpers
# --------------------------------------------------
def chunked(data, size):
    for i in range(0, len(data), size):
        yield data[i:i + size]

def save_chunks(entities, output_base_dir, dataset, chunk_size=50):
    output_path = os.path.join(output_base_dir, "outputs")
    os.makedirs(output_path, exist_ok=True)

    for i, chunk in enumerate(chunked(entities, chunk_size)):
        timestamp = int(time.time() * 1000) + i
        file_name = f"{dataset}_{timestamp}.json"
        full_path = os.path.join(output_path, file_name)

        with open(full_path, "w", encoding="utf-8") as f:
            json.dump(chunk, f, indent=4, ensure_ascii=False)

        logger.info("Generado fichero de salida: %s", file_name)

def log_batch_payload(batch_number, chunk):
    try:
        batch_json = json.dumps(chunk, ensure_ascii=False, indent=2)
        logger.debug("Payload batch %d:\n%s", batch_number, batch_json)
    except Exception as e:
        logger.error("No se pudo serializar el batch %d para log: %s", batch_number, e)

def log_suspicious_characters(batch_number, chunk):
    forbidden_chars = set(['<', '>', '"', "'", '=', ';', '(', ')'])

    for entity_idx, entity in enumerate(chunk, start=1):
        for attr_name, attr_value in entity.items():
            serialized = json.dumps(attr_value, ensure_ascii=False)

            bad_chars = sorted(set(ch for ch in serialized if ch in forbidden_chars))
            if bad_chars:
                logger.warning(
                    "Batch %d, entidad %d, atributo '%s' contiene caracteres sospechosos %s. Valor: %s",
                    batch_number,
                    entity_idx,
                    attr_name,
                    bad_chars,
                    serialized
                )

def replace_target_schema(sql_file_path: Path, target_schema: str):
    content = sql_file_path.read_text(encoding="utf-8")
    content = content.replace(":target_schema.", f"{target_schema}.")
    sql_file_path.write_text(content, encoding="utf-8")
# --------------------------------------------------
# Main
# --------------------------------------------------
def main():
    directory_path = os.getenv("DATA_PATH")
    dataset = os.getenv("DATASET")
    service_path = os.getenv("FIWARE_SERVICEPATH")

    if not directory_path:
        logger.error("La variable de entorno DATA_PATH no está definida")
        sys.exit(1)
    
    if not dataset:
        logger.error("La variable de entorno DATASET no está definida")
        sys.exit(1)

    if not service_path:
        logger.error("La variable de entorno FIWARE_SERVICEPATH no está definida")
        sys.exit(1)

    if not os.path.isdir(directory_path):
        logger.error("El directorio %s no es válido", directory_path)
        sys.exit(1)

    if not service_path.startswith("/"):
        service_path = f"/{service_path}"

    logger.info("Ejecutando ETL para dataset '%s'", dataset)
    logger.info("FIWARE ServicePath: %s", service_path)
    logger.info("DATA_PATH: %s", directory_path)

    all_entities = []

    # --------------------------------------------------
    # Dynamic transformer loading
    # --------------------------------------------------
    try:
        module = importlib.import_module(f"modules.{dataset}.transformer")
        transform_func = getattr(module, "transform_csv_to_ngsi")
    except Exception as e:
        logger.error("No se pudo cargar el transformer de '%s': %s", dataset, e)
        sys.exit(1)

    # --------------------------------------------------
    # Data extraction (CSV o API)
    # --------------------------------------------------
    try:
        input_files = get_input_files(directory_path, dataset)
    except DataExtractionError as e:
        logger.error("Error en la extracción de datos: %s", e)
        sys.exit(1)
    except Exception as e:
        logger.error("Error inesperado obteniendo los datos de entrada: %s", e)
        sys.exit(1)

    if not input_files:
        logger.warning("No se encontraron datos de entrada para procesar")
        return

    # --------------------------------------------------
    # Transform processing
    # --------------------------------------------------
    for file_path in input_files:
        logger.info("Procesando entrada %s", file_path)
        try:
            entities = transform_func(directory_path, file_path)
            all_entities.extend(entities)
        except Exception as e:
            logger.error("Error procesando %s: %s", file_path, e)

    if not all_entities:
        logger.warning("No se generaron entidades NGSI")
        return

    logger.info("Total de entidades generadas: %d", len(all_entities))

    # --------------------------------------------------
    # Get configuration
    # --------------------------------------------------
    output_target = os.getenv("OUTPUT_TARGET", "ORION")
    orion_base_url = os.getenv("ORION_BASE_URL")
    batch_size = int(os.environ.get("ORION_BATCH_SIZE", "20"))
    batch_delay = int(os.environ.get("ORION_BATCH_DELAY", "10"))

    logger.info("Destino de salida seleccionado: %s", output_target)

    # --------------------------------------------------
    # Send entities to SQL File
    # --------------------------------------------------

    if output_target == "SQL":
        logger.info("Generando salida SQL")

        entities_for_sql = []
        for entity in all_entities:
            sql_ready_entity = entity.copy()
            for key, attr in sql_ready_entity.items():
                if isinstance(attr, dict) and 'value' in attr:
                    if isinstance(attr['value'], (dict, list)):
                        attr['value'] = json.dumps(attr['value'])
            entities_for_sql.append(sql_ready_entity)

        path_sql = Path(os.path.join(directory_path, "outputs", "inserts.sql"))

        logger.info("Guardando entidades en SQL: %s", path_sql)
        with tc.sqlFileStore(path=path_sql, subservice=service_path, schema="madrid", namespace=service_path.lstrip("/")) as store:
            store(all_entities)
        
        logger.info("Fichero SQL generado correctamente")
        return

    if not orion_base_url:
        logger.error("ORION_BASE_URL no está definida")
        sys.exit(1)

    # --------------------------------------------------
    # Keycloak authentication (OAuth2)
    # --------------------------------------------------
    auth = None
    if os.getenv("KEYCLOAK_URL"):
        logger.info("Configurando autenticación Keycloak")

        auth = KeycloakAuthManager(
            endpoint=os.getenv("KEYCLOAK_URL"),
            service=os.getenv("FIWARE_SERVICE"),
            user=os.getenv("KEYCLOAK_USER"),
            password=os.getenv("KEYCLOAK_PASSWORD"),
            client_id=os.getenv("KEYCLOAK_CLIENT_ID"),
            client_secret=os.getenv("KEYCLOAK_CLIENT_SECRET")
        )

        try:
            auth.get_auth_token_subservice(service_path)
        except Exception as e:
            logger.error("Error autenticando contra Keycloak: %s", e)
            raise

    # --------------------------------------------------
    # Send entities to Orion
    # --------------------------------------------------
    logger.info("Enviando entidades a Orion (%s)", orion_base_url)

    cbm = tc.cb.cbManager(endpoint=orion_base_url)

    with tc.orionStore(
        cb=cbm,
        auth=auth,
        subservice=service_path
    ) as store:
        for i, chunk in enumerate(chunked(all_entities, batch_size), start=1):
            # log_batch_payload(i, chunk)
            # log_suspicious_characters(i, chunk)
            logger.info("Enviando batch %d con %d entidades", i, len(chunk))
            try:
                store(chunk)
                time.sleep(batch_delay)
            except Exception as e:
                logger.error("Error enviando batch %d: %s", i, e)
                raise

    logger.info("Carga completada correctamente en Orion")

# --------------------------------------------------
# Entry point
# --------------------------------------------------
if __name__ == "__main__":
    main()
