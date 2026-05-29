# JR Verifica EC — Context Bible

> **Lee este archivo antes de empezar a trabajar.** Te da el contexto completo del proyecto para retomar trabajo sin re-aprenderlo todo.
>
> Última actualización: 2026-05-29 · Commit base: `035c18a`

---

## 🎯 Qué es esto

**JR Verifica EC** es una app SaaS-ready de verificación de antecedentes en Ecuador, para equipos de RR.HH.

**Cliente actual:** Rubasa (Guayaquil) — el usuario (Jostin) lo construyó para su mamá que trabaja en RR.HH. ahí. Próximo cliente potencial: Dentaklin (también del usuario).

**Lo que hace:** Verifica una cédula (o un Excel con muchas cédulas) en 4 fuentes oficiales ecuatorianas, devuelve un semáforo (APTO / OBSERVACIÓN / RECHAZAR / CRÍTICO), genera PDF oficial y Excel de reporte.

**4 fuentes oficiales:**
| Fuente | Qué verifica |
|---|---|
| **Bachiller** (Min. Educación / SENESCYT) | Título de bachillerato registrado |
| **SATJE** (Consejo de la Judicatura) | Procesos judiciales como demandado/actor |
| **SETEC** (Min. del Trabajo) | Certificaciones de capacitación oficial |
| **Fiscalía** (SIAF) | Noticias del delito (sospechoso/imputado) |

**URL producción:** `https://verifica.dentaklin.shop` (Easypanel + VPS)

---

## 🏗️ Arquitectura

```
┌────────────────────────────────────────────────────────────┐
│  Usuario (RR.HH. / mamá del usuario)                       │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTPS
                       ▼
┌────────────────────────────────────────────────────────────┐
│  Servicio "verifica" (este repo: jr-verifica-ec)           │
│  • FastAPI + Jinja2 + SQLite                               │
│  • UI Verifica Console v2 (no React, server-rendered)      │
│  • Auth multi-usuario (bcrypt) + roles                     │
│  • Genera PDFs (WeasyPrint) + Excel (openpyxl)             │
│  • Compliance LOPDP                                         │
└──────────────────────┬─────────────────────────────────────┘
                       │ HTTP interno (red Docker)
                       ▼
┌────────────────────────────────────────────────────────────┐
│  Servicio "bg-api" (repo: background-checks-ec)            │
│  • FastAPI + Playwright (Chromium headless)                │
│  • Scraping de Mineduc / SATJE / SETEC / Fiscalía          │
│  • Cache Redis interno (TTL configurable)                  │
│  • Acepta force_refresh para saltar Redis                   │
└──────────────────────┬─────────────────────────────────────┘
                       │
                       ▼
              (Portales oficiales del Estado EC)
```

**Dos repos separados:**
1. `JostinRendonL/jr-verifica-ec` ← este, la UI + lógica de negocio
2. `JostinRendonL/background-checks-ec` ← scrapers de las fuentes

**Despliegue:**
- **Easypanel** en VPS con IP `31.220.99.243`
- Ambos servicios son contenedores Docker
- Se comunican por red interna Docker (`http://dentaklin_bg-api:8000`)
- Build trigger: `git push origin main` → Easypanel detecta y rebuilda

---

## 📦 Stack técnico

```
Python 3.12 + FastAPI 0.115
Jinja2 templates (server-rendered, no React activo)
SQLite (WAL mode) — historial + audit_log + verificaciones + usuarios
bcrypt 4.2 — password hashing
WeasyPrint 62.3 — generación de PDF (requiere GTK en Docker)
openpyxl 3.1 — Excel I/O
httpx — cliente HTTP async para bg-api
itsdangerous — cookies firmadas
slowapi — rate limiting
Sentry SDK — error tracking (opt-in via SENTRY_DSN)
prometheus-fastapi-instrumentator — métricas (opt-in via METRICS_ENABLED)
apscheduler — limpieza periódica LOPDP
Resend (preferido) o SMTP — envío de emails
```

---

## 🗂️ Estructura del código

```
src/
├── main.py                  # 1,800+ LOC — routes (god-module, pendiente split)
├── auth.py                  # bcrypt + cookies + cedula_valida_ec + rate-limit por IP
├── usuarios.py              # CRUD usuarios, roles (admin/operador), debe_cambiar_pass
├── password_reset.py        # tokens de reset por email
├── historial_sqlite.py      # DB principal — todas las verificaciones
├── audit_log.py             # DB separada audit.db — acciones admin auditadas
├── verificaciones.py        # códigos públicos de verificación de PDFs (QR)
├── compliance.py            # LOPDP — derecho al olvido + limpieza periódica
├── scheduler.py             # apscheduler — cron de limpieza
├── bg_client.py             # cliente HTTP del bg-api
├── processor.py             # async batch — _procesar_una, ejecutar_job, _calcular_semaforo
├── excel_io.py              # leer Excel + generar Excel premium con stats
├── pdf_generator.py         # WeasyPrint — PDF con logos fuentes, QR, notas
├── delitos_clasificacion.py # mapeo delitos → CRITICO/RECHAZAR/OBSERVACION
├── mailer.py                # Resend / SMTP / console fallback
├── obs.py                   # Sentry init + capture_exception helper
├── metrics.py               # Prometheus opt-in
└── templates/
    ├── base.html            # shell con sidebar drawer (responsive)
    ├── login.html           # logos flotantes, glows
    ├── upload.html          # tabs Búsqueda / Lote + JS pesado para resultado dinámico
    ├── resultado.html       # vista detallada de una verificación
    ├── historial.html       # tabla con multi-select, dedup, orden, badge ↻
    ├── lotes.html           # cards de lotes con stats
    ├── timeline.html        # historia completa de una cédula
    ├── dashboard.html       # KPIs (verificaciones, horas, días, hoy)
    ├── job.html             # progreso de lote en tiempo real
    ├── perfil.html          # cambio de pass
    ├── admin_usuarios.html  # gestión de usuarios (admin)
    ├── verificar.html       # PÚBLICO — validar PDF por código QR
    ├── olvide_pass.html, reset_pass.html
    └── email_*.html         # bienvenida, reset, password_cambiada, lote_terminado

tests/                       # 101 tests pytest
```

---

## 💾 Schema de SQLite

### Tabla `historial` (DB: `historial.db`)
```sql
id              TEXT PRIMARY KEY    -- hex timestamp + uuid
cedula          TEXT NOT NULL
tipo            TEXT NOT NULL       -- 'completo'|'bachiller'|'satje'|'setec'
timestamp       INTEGER NOT NULL
semaforo        TEXT                -- '🟢 APTO' / '🟡 OBSERVACIÓN' / etc (con emoji)
nombre          TEXT
resultado_json  TEXT NOT NULL       -- todo el resultado de las 4 fuentes
usuario_id      TEXT                -- FK a usuarios.id
lote_id         TEXT                -- = job_id, NULL para búsquedas individuales
lote_nombre     TEXT                -- "Rubasa Mayo 2026" u otro
notas           TEXT                -- notas del operador, por cédula (no por verificación)

-- Índices:
idx_cedula_ts, idx_ts, idx_semaforo, idx_lote
```

### Tablas adicionales:
- **`usuarios`** — id, email, nombre, password_hash (bcrypt), rol, activo, debe_cambiar_pass, ultimo_login
- **`verificaciones`** — códigos públicos para validar PDFs (escaneo QR)
- **`audit_log`** (DB separada `audit.db`) — ts, actor_id, actor_email, accion, target, ip, metadata_json

---

## 🚦 Lógica de semáforo (CRÍTICO entender)

Definida en `processor._calcular_semaforo()`. Solo aplica al tipo `completo`:

1. **SIN DATOS (⚪)** — si bachiller o SATJE retornaron ERROR
2. **CRÍTICO (🚨)** — delito grave: asesinato, violación, narcotráfico, secuestro, terrorismo, etc.
3. **RECHAZAR (🔴)** — delito mediano o demandado activo (excluyendo pensión alimenticia)
4. **OBSERVACIÓN (🟡)** — delito personal/civil, o bachiller NO ENCONTRADO, o sospechoso en Fiscalía
5. **APTO (🟢)** — Bachiller OK + sin procesos como demandado + sin antecedentes Fiscalía

**Casos especiales:**
- Solo causas de **alimentos** = OBSERVACIÓN (no RECHAZAR) — regla aprobada por RR.HH.
- `intimidación`, `accidente`, `abuso` = OBSERVACIÓN
- `receptación` = RECHAZAR
- El **semáforo manual** (editado por operador) **se preserva** tras re-verificación

---

## 🔄 Sistema de cache de 2 niveles

```
Usuario → app (SQLite TTL 24h) → bg-api (Redis TTL ?) → portales oficiales
```

- **App SQLite**: TTL `CACHE_TTL_SEG=86400` (24h). Función `buscar_cache()`.
- **bg-api Redis**: cache interno separado, también con TTL propio.
- **Re-verificar** (`force_refresh=True`): salta AMBOS caches, va a portales oficiales (~30s).

**Importante:** `obtener_resultado(entrada_id)` NO tiene TTL — siempre devuelve la entrada por ID. Por eso PDFs viejos siguen siendo descargables (los lee del historial, no del cache).

---

## 🔐 Seguridad implementada

| Mecanismo | Detalle |
|---|---|
| Auth | bcrypt + cookie firmada `itsdangerous`, `secure=True, samesite=strict` |
| Rate limit | slowapi: login 10/min, búsqueda 50/min, lote 5/min, ZIP 3/min, export-excel 10/min |
| Headers | HSTS, X-Frame-Options DENY, X-Content-Type-Options nosniff, Referrer-Policy strict-origin |
| CSP | `default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline' fonts.googleapis.com; font-src fonts.gstatic.com; img-src 'self' data:; connect-src 'self'` |
| Audit | acciones admin críticas auditadas en `audit.db` (derecho al olvido, usuario_creado, etc.) |
| Compliance LOPDP | Derecho al olvido (Art. 14) + limpieza periódica (Art. 12, RETENCION_MESES=12) |
| Rate limit por IP en login | en `auth.py` (independiente de slowapi) |
| PDF anti-falsificación | QR + código firmado con `PDF_VERIFY_SECRET` + endpoint público `/verificar/{codigo}` |

**Pendiente:** quitar `'unsafe-inline'` de CSP (requiere migrar todos los `onclick=""` a `addEventListener`).

---

## 🌐 Endpoints principales

```
GET  /                          home — tab Búsqueda o Lote
GET  /login, POST /login        autenticación
GET  /logout
GET  /perfil                    cambio de password propio
GET  /historial                 tabla con filtros, dedup, orden
GET  /historial/persona/{ced}   timeline vertical de una cédula
GET  /historial/{id}            ver una verificación específica
GET  /historial/{id}/pdf        descargar PDF
GET  /lotes                     cards de lotes con stats
POST /pdf                       generar PDF desde cache
POST /buscar                    búsqueda individual (form tradicional)
POST /procesar                  subir Excel de lote
POST /historial/export-excel    Excel filtrado o de selección
POST /historial/pdf-zip         ZIP de hasta 200 PDFs
POST /historial/borrar-multiple borrado en bulk
POST /historial/cedula/{ced}/notas       guardar notas
POST /historial/cedula/{ced}/nombre      editar nombre manualmente
POST /historial/cedula/{ced}/semaforo    override manual del semáforo
POST /derecho-al-olvido         LOPDP Art. 14
POST /lotes/{id}/reprocesar-errores      re-corre cédulas con error en un lote
GET  /verificar/{codigo}        PÚBLICO — validar PDF emitido
GET  /dashboard                 KPIs
GET  /admin/usuarios            gestión usuarios (admin)
GET  /health, /health?deep=1    healthcheck (Docker + deep)
POST /api/buscar, /api/procesar JSON APIs (para React futuro)
GET  /api/stats, /api/historial JSON APIs
```

---

## 🎨 Sistema de diseño (Verifica Console v2)

**Tipografías:**
- Plus Jakarta Sans 600/700/800 — titulares
- Inter 400-700 — body
- JetBrains Mono — cédulas y números

**Paleta:**
```
--canvas:  #F4F5F8     --rail:    #14141C   (sidebar oscuro)
--primary: #5B4BE3     --primary-soft: #ECEAFC
--apto:    #12A150     --obs:     #E08C0B
--rech:    #E04338     --crit:    #7C1D14
```

**Sidebar fijo 244px** en desktop, **drawer hamburger** en mobile (≤900px).

**Responsive:** breakpoints `@media (max-width: 900px)` y `(max-width: 640px)`. Grids inline `repeat(4,1fr)` se transforman vía CSS attribute selector.

---

## 📋 Variables de entorno

### Obligatorias en prod
```
APP_PASSWORD=...                 # legacy single-pass (queda por compat)
SESSION_SECRET=<aleatorio>       # firma de cookies
BG_API_URL=http://dentaklin_bg-api:8000
BG_API_KEY=<token>
ADMIN_EMAIL=jostinrendon5@gmail.com
ADMIN_NOMBRE=Jostin Rendon
```

### Opcionales con defaults
```
BG_API_TIMEOUT=120
MAX_WORKERS=3                    # cédulas en paralelo
CACHE_TTL_SEG=86400              # 24h cache SQLite
LOG_LEVEL=INFO                   # DEBUG para troubleshooting
RATE_LIMIT_ENABLED=1             # 0 = apagar slowapi
JOB_RETENTION_HOURS=24           # limpieza de jobs en RAM
RETENCION_MESES=12               # LOPDP — borrar historial > 12 meses
PUBLIC_URL=https://verifica.dentaklin.shop
APP_BASE_URL=https://verifica.dentaklin.shop
PDF_VERIFY_SECRET=...            # firma de códigos QR
```

### Email (opt-in)
```
RESEND_API_KEY=...               # preferido
MAIL_FROM="JR Verifica EC <noreply@jrautomata.com>"
# o SMTP_HOST/PORT/USER/PASS/SSL
```

### Observabilidad (opt-in)
```
SENTRY_DSN=...
SENTRY_ENV=production
METRICS_ENABLED=1
```

---

## ✅ Features implementadas (full timeline)

### v2 Diseño + base
- Verifica Console v2 con sidebar oscuro, glows ambientales en login
- Logos oficiales de las 4 fuentes en login/upload/PDF
- Dashboard con 4 KPI cards, gráfico barras, donut distribución
- Auth multi-usuario con roles + reset password por email
- Compliance LOPDP completo

### Sistema de lotes
- Subir Excel con cédulas → procesa con MAX_WORKERS en paralelo
- Cada lote tiene `lote_nombre` opcional (default auto-generado con fecha+cantidad)
- Página `/lotes` con cards mostrando stats por lote (semáforo + errores)
- Filtro `/historial?lote=XXX` con breadcrumb
- **Re-procesar errores del lote** — banner ámbar automático si hay vacíos del Ministerio
- Email automático cuando termina el lote (HTML con stats)

### Historial
- Multi-select con FAB flotante: Excel / PDFs ZIP / Borrar
- **Dedup por default** (1 fila por cédula con badge `↻ N`)
- **Toggle "Ver todas"** para modo auditoría
- **Búsqueda inteligente**: dígitos → cédula (cliente), letras → nombre (servidor, tokens)
- **Filtros por semáforo** (APTO/OBS/RECH/CRIT/SIN DATOS)
- **Ordenar por**: fecha/nombre/cédula/semáforo (server-side, exports respetan)
- **Vista timeline** (`/historial/persona/{ced}`) con dots coloreados
- Edición inline de nombre y semáforo (con persistencia tras re-verificación)
- Borrado individual + bulk + derecho al olvido

### Verificación individual
- Tab "Búsqueda" con cédula + checkboxes de fuentes
- Resultado en panel lateral con cards por fuente
- Editor de notas inline (autosave on blur)
- Botón "Re-verificar" (`force_refresh=True`)
- Toggle "Forzar re-consulta (ignorar caché)"

### PDF
- WeasyPrint con logos oficiales de cada fuente
- Sección "📝 Notas del operador" violeta (si hay notas)
- QR + código firmado para validación pública
- Bulk download ZIP (hasta 200 a la vez)

### Excel
- Excel premium con banner navy, stats, semáforo coloreado
- 4 modos: completo/bachiller/satje/setec con columnas dinámicas
- Export filtrado (de la vista actual) o por selección
- Respeta el orden elegido en la UI

### Auditoría / observabilidad
- Audit log estructurado para acciones admin
- Logging con `logger = getLogger("verifica")` (no más print())
- Sentry opt-in con capture_exception
- Prometheus metrics opt-in
- Healthcheck deep (SQLite + bg-api + scheduler)

### Rate limiting + seguridad
- slowapi por usuario logueado (uid) o IP
- `_to_bool()` helper para Form booleanos (vs `bool(str)` frágil)
- Notificación email al cambiar password

### Mobile
- Sidebar drawer hamburger ≤900px
- Tablas: oculta cols menos críticas en mobile (operador, fecha rel)
- Grids 4→2→1 columnas
- Modales casi full-screen

---

## ⚠️ Deuda técnica conocida

### Alta
- `main.py` 1,800+ LOC — split pendiente en `src/routes/{auth,historial,admin,api}.py`
- CSP tiene `'unsafe-inline'` — requiere migrar todos los `onclick=""` a `addEventListener`
- Jobs viven en RAM (`processor._jobs`) — no sobreviven reinicio. `JOB_RETENTION_HOURS=24` mitiga OOM

### Media
- React SPA dormido en `frontend/` (compilado en `src/static/frontend/`) — no se usa, decidir si completar o borrar
- Endpoints `/api/*` JSON no tienen tests de integración
- `processor.py` tiene `excel_bytes` en memoria — para lotes > 5000 cédulas puede ser problema

### Baja
- `historial.py` (legacy JSON) ya fue borrado en commit `fbe92b5` ✅
- Requirements sin hashes (`--require-hashes`) — supply chain leve

---

## 🚀 Próximos pasos sugeridos

### Producto (cuando el usuario quiera)
1. **SaaS multi-empresa** — tabla `empresas`, cupo por empresa, superadmin role, aislamiento de datos. 1-2 días.
2. **Comparar 2 cédulas lado a lado** — útil para RR.HH. dudando entre candidatos. ~3h
3. **Plantilla Excel mejorada** — con validación de cédula, dropdowns. ~1h
4. **Webhook a Slack** cuando termina lote. ~2h
5. **Reporte mensual auto** — email el 1ro del mes con stats. ~3h
6. **Backup automático de SQLite** a S3/Backblaze. ~2h
7. **Tags/etiquetas por cédula** (puesto, turno, etc.) — filtros más útiles. ~2h

### Hardening técnico
1. Split `main.py` en `routes/` (riesgo regresión alto, hacer con tests de integración primero)
2. Quitar `unsafe-inline` de CSP
3. Persistir `_jobs` en SQLite (sobreviven restart)
4. Tests de integración para endpoints HTTP

---

## 🔧 Comandos útiles

```bash
# Tests
python -m pytest tests/ -x -q

# Validar Python + Jinja2
python -c "
import ast, os
from jinja2 import Environment, FileSystemLoader
for root,_,files in os.walk('src'):
    for f in files:
        if f.endswith('.py'): ast.parse(open(os.path.join(root,f),encoding='utf-8').read())
env = Environment(loader=FileSystemLoader('src/templates'))
for f in os.listdir('src/templates'):
    if f.endswith('.html'): env.parse(open('src/templates/'+f,encoding='utf-8').read())
print('OK')
"

# Build + deploy
git add -A && git commit -m "..." && git push origin main
# Easypanel detecta el push y rebuilda automáticamente

# Local dev (NO funciona en Windows directo — WeasyPrint requiere GTK)
# Usar Docker o WSL2 para correr localmente
```

---

## 📚 Repos relacionados

- `JostinRendonL/jr-verifica-ec` — este repo
- `JostinRendonL/background-checks-ec` — bg-api con scrapers (carpeta local: `C:\Users\Home\Desktop\background-checks-ec`)
- (Filtro_CVs) — proyecto hermano del usuario, NO mezclar contextos

---

## 🤝 Cómo retomar trabajo en una nueva conversación

Pega esto al inicio:

> "Estoy trabajando en `jr-verifica-ec`. Lee `C:\Users\Home\Desktop\jr-verifica-ec\PROJECT_CONTEXT.md` para entender el proyecto. Lo último que hicimos fue [X]. Ahora quiero [Y]."

O más corto:

> "Sigue trabajando en jr-verifica-ec. Lee PROJECT_CONTEXT.md y dime qué hicimos último."
