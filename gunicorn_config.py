import os

# Render inyecta la variable de entorno PORT en el contenedor (normalmente 10000)
port = int(os.environ.get("PORT", "5050"))

# Obligar a Gunicorn a escuchar en todas las interfaces de red de ese puerto
bind = f"0.0.0.0:{port}"

# Configuraciones anti-crash para entornos hostiles tipo Docker/Render
workers = 1
worker_class = "gthread"
threads = 4
timeout = 160
capture_output = True
enable_stdio_inheritance = True
loglevel = "debug"
