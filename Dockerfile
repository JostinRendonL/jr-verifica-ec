# ── Stage 1: Build React frontend ─────────────────────────────────────────────
# Cambiado a node:22-alpine para romper caché de Docker y forzar build limpio
FROM node:22-alpine AS frontend-build

WORKDIR /frontend
COPY frontend/package*.json ./
RUN npm install --legacy-peer-deps

COPY frontend/ .
# Saltar tsc (ya verificado en CI/local) — solo compilar con Vite
RUN npx vite build
# vite.config.ts → build.outDir: '../src/static/frontend'
# Con WORKDIR /frontend → output en /src/static/frontend

# ── Stage 2: Python + FastAPI ─────────────────────────────────────────────────
FROM python:3.12-slim

RUN apt-get update && apt-get install -y \
    curl ca-certificates \
    libpango-1.0-0 libpangoft2-1.0-0 libharfbuzz-subset0 \
    libcairo2 libgdk-pixbuf-2.0-0 shared-mime-info \
    fonts-dejavu fonts-noto-color-emoji \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .

# Copiar el build de React desde el stage anterior
COPY --from=frontend-build /src/static/frontend /app/src/static/frontend

# Verificar que el build llegó (falla el deploy si Node no compiló)
RUN ls /app/src/static/frontend/index.html

# Carpeta para historial persistente (montar volumen en Easypanel)
RUN mkdir -p /app/data
VOLUME ["/app/data"]

EXPOSE 8000

HEALTHCHECK --interval=30s --timeout=10s --start-period=20s --retries=3 \
    CMD curl -f http://localhost:8000/health || exit 1

CMD ["uvicorn", "src.main:app", "--host", "0.0.0.0", "--port", "8000", "--workers", "1"]
