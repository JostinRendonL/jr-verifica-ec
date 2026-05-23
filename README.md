# ⚙️ JR Verifica EC

> Verificación masiva de **Bachiller (Min. Educación)** + **Procesos Judiciales (SATJE)** desde un Excel.
> *Powered by JR Automata.*

## 🎯 Qué hace

1. Subes un Excel `.xlsx` con cédulas (columna `cedula`)
2. Marcas qué quieres verificar: ☑ Bachiller · ☑ Procesos Judiciales · o ambos
3. La app procesa en paralelo (hasta 3 cédulas a la vez)
4. Descargas un Excel con los resultados, semáforo incluido (🟢/🟡/🔴) si pediste ambas

## 🏗️ Stack

- **FastAPI** + Jinja2 templates + TailwindCSS (CDN)
- **openpyxl** para Excel I/O
- **httpx** asíncrono para llamar al `bg-api`
- **itsdangerous** para cookies firmadas
- Login: una sola contraseña global (env var)

## 🔌 Variables de entorno

| Variable | Descripción |
|----------|-------------|
| `APP_PASSWORD` | Contraseña global para entrar |
| `SESSION_SECRET` | Cadena aleatoria para firmar cookies |
| `BG_API_URL` | `http://dentaklin_bg-api:8000` (red interna Docker) |
| `BG_API_KEY` | Clave del bg-api |
| `BG_API_TIMEOUT` | Default `120` segundos |
| `MAX_WORKERS` | Cédulas en paralelo (default `3`) |

## 🚀 Despliegue (Easypanel)

1. New App → GitHub source: `JostinRendonL/jr-verifica-ec`
2. Build: Dockerfile
3. Domain: `verifica.dentaklin.shop` → puerto `8000`
4. Environment: copiar `.env.example` y rellenar
5. Deploy

## 💻 Local

```bash
pip install -r requirements.txt
cp .env.example .env  # editar valores
uvicorn src.main:app --reload --port 8000
```

## 📄 Licencia

MIT
