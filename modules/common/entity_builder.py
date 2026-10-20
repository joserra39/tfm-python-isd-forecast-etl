import json
import copy

def load_entity_template(template_path):
    with open(template_path, "r", encoding="utf-8") as f:
        return json.load(f)

def build_entity_from_template(template, values):
    """
    Sustituye placeholders {xxx} por valores reales
    """
    entity = copy.deepcopy(template)
    entity_str = json.dumps(entity)

    for key, value in values.items():
        placeholder = f"{{{key}}}"
        
        # Si el valor es una lista (coordenadas) o dict, buscamos el placeholder con comillas
        if isinstance(value, (list, dict)):
            quoted_placeholder = f'"{placeholder}"'
            if quoted_placeholder in entity_str:
                # Reemplazamos '" {key} "' por [x, y] (sin comillas)
                entity_str = entity_str.replace(quoted_placeholder, json.dumps(value))
            else:
                entity_str = entity_str.replace(placeholder, json.dumps(value))
        else:
            # Comportamiento normal para el resto
            entity_str = entity_str.replace(placeholder, str(value))

    return json.loads(entity_str)
