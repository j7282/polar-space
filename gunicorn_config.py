import os

# Render inyecta la variable de entorno PORT en el contenedor (normalmente 10000)
port = os.environ.get("PORT", "5050")

# Obligar a Gunicorn a escuchar en todas las interfaces de red de ese puerto
bind = f"0.0.0.0:{port}"

# Configuraciones de rendimiento básicas
workers = 2
threads = 4
timeout = 120
