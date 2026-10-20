import requests
import logging
import os

logger = logging.getLogger(__name__)

class KeycloakAuthManager:
    """
    Reemplazo de authManager compatible con Keycloak (OAuth2).
    Mantiene la compatibilidad con tc.orionStore al usar el diccionario 'tokens'.
    """
    def __init__(self, endpoint, service, user, password, client_id, client_secret):
        self.endpoint = endpoint.rstrip('/')
        self.service = service
        self.user = user
        self.password = password
        self.client_id = client_id
        self.client_secret = client_secret
        self.tokens = {}

    def get_auth_token_subservice(self, subservice):
        """Obtiene el token de Keycloak y lo guarda en el formato que espera la librería"""
        token_url = f"{self.endpoint}"
        
        data = {
            'grant_type': 'password',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
            'username': self.user,
            'password': self.password
        }

        headers = {
            "Content-Type": "application/x-www-form-urlencoded"
        }

        try:
            logger.debug(f"Solicitando token a Keycloak para {subservice} a {token_url}")
            response = requests.post(token_url, data=data, headers=headers, timeout=30)
            logger.debug(f"TOKEN_STATUS {response.status_code}")
            response.raise_for_status()
            
            token = response.json()['access_token']
            # logger.debug(f"TOKEN={token}")
            # Guardamos el token en el diccionario interno para que orionStore lo encuentre
            self.tokens[subservice] = token
            return token
            
        except Exception as e:
            logger.error(f"Error en la autenticación Keycloak: {e}")
            raise