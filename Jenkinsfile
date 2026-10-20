pipeline {
  agent any

  stages {
    stage('1. Checkout') {
      steps {
        checkout scm
      }
    }

    stage('2. Mostrar variables') {
      steps {
        script {
          echo "KEYCLOAK_URL=${env.KEYCLOAK_URL}"
          echo "ORION_BASE_URL=${env.ORION_BASE_URL}"
          echo "FIWARE_SERVICE=${env.FIWARE_SERVICE}"
          echo "FIWARE_SERVICEPATH=${env.FIWARE_SERVICEPATH}"
        }
        sh 'printenv | sort | grep -E "KEYCLOAK|ORION|FIWARE" || true'
      }
    }

    stage('3. Crear venv e instalar dependencias') {
      steps {
        echo 'Creando entorno virtual y cargando dependencias...'
        sh '''
        set -e

        echo "Python3 en el nodo:"
        python3 --version

        echo "Creando entorno virtual (si no existe)..."
        if [ ! -d ".venv" ]; then
            python3 -m venv .venv
        fi

        echo "Activando entorno virtual..."
        . .venv/bin/activate

        echo "Pip dentro del venv:"
        which pip
        python3 -m pip --version

        echo "Instalando dependencias..."
        python3 -m pip install --break-system-packages -r requirements.txt
        '''
      }
    }

    stage('4. Ejecutar ETL') {
      steps {
        withCredentials([
        usernamePassword(
            credentialsId: 'KEYCLOAK_CLIENT',
            usernameVariable: 'KEYCLOAK_CLIENT_ID',
            passwordVariable: 'KEYCLOAK_CLIENT_SECRET'
        ),
        usernamePassword(
            credentialsId: 'KEYCLOAK_USER',
            usernameVariable: 'KEYCLOAK_USER',
            passwordVariable: 'KEYCLOAK_PASSWORD'
        )
        ]) {
        timeout(time: 10, unit: 'MINUTES') {
            sh """
                set +x

                echo "PWD: \$(pwd)"

                echo "Activando venv..."
                . .venv/bin/activate || echo "No se pudo activar .venv"

                echo "which python3:"
                which python3 || echo "python3 no encontrado"

                echo "python3 --version:"
                python3 --version || echo "No se pudo obtener version de python3"

                echo "Ejecutando main.py..."
                python3 main.py
            """
            }
        }
      }
    }
  }

  post {
    failure {
      echo 'Error detectado. Revisa la instalación de dependencias o el código Python.'
    }
    always {
      echo 'Finalizando pipeline.'
    }
  }
}