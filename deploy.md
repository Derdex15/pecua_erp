# 🚀 Guía de Deploy — ERP Pecuario

Esta guía cubre los pasos 2, 3 y 4 del roadmap:
- Deploy en producción con HTTPS (Render.com)
- TWA para publicar en Play Store (Bubblewrap)
- Configurar assetlinks.json

---

## PASO 1: Subir el código a GitHub

Si aún no tienes repositorio:

```bash
git init
git add .
git commit -m "Initial commit - ERP Pecuario"
git remote add origin https://github.com/TU_USUARIO/erp-pecuario.git
git push -u origin main
```

**Asegúrate de que `.env` esté en `.gitignore`** — nunca subas credenciales:

```
# .gitignore
.env
__pycache__/
*.pyc
*.pyo
.DS_Store
```

---

## PASO 2: Deploy en Render.com

### 2.1 Crear cuenta y conectar repositorio

1. Ve a [render.com](https://render.com) y crea cuenta gratuita
2. Dashboard → **New +** → **Web Service**
3. Conecta tu repositorio de GitHub
4. Render detecta el `render.yaml` automáticamente

### 2.2 Configurar variables de entorno

En el dashboard de Render, ve a **Environment** y agrega:

| Variable | Valor |
|---|---|
| `SUPABASE_KEY` | Tu clave de Supabase |
| `SECRET_KEY` | (Render la genera automáticamente) |
| `ENV` | `production` |
| `TWA_PACKAGE_NAME` | `app.erpecuario.twa` (o el que elijas) |
| `TWA_SHA256_CERT` | Lo obtienes en el Paso 3 |

### 2.3 Dominio

Render te da un dominio gratis: `erp-pecuario.onrender.com`

Para dominio propio (recomendado para Play Store):
1. Compra un dominio en Namecheap / GoDaddy (~$12/año)
2. En Render → Settings → Custom Domains → agrega tu dominio
3. Render configura HTTPS automáticamente con Let's Encrypt

> ⚠️ El plan gratuito de Render hiberna después de 15 minutos sin tráfico.
> Para producción usa el plan **Starter ($7/mes)** que mantiene la app siempre activa.

---

## PASO 3: Empaquetar como TWA con Bubblewrap

### 3.1 Instalar Bubblewrap

Necesitas Node.js 14+ instalado.

```bash
npm install -g @bubblewrap/cli
```

### 3.2 Inicializar el proyecto TWA

```bash
mkdir erp-pecuario-twa
cd erp-pecuario-twa
bubblewrap init --manifest https://TU_DOMINIO.com/manifest.json
```

Bubblewrap te hará preguntas. Respuestas recomendadas:

| Pregunta | Respuesta |
|---|---|
| Application name | ERP Pecuario |
| Short name | Pecuario |
| Package ID | app.erpecuario.twa |
| Start URL | https://TU_DOMINIO.com/ |
| Display mode | standalone |
| Theme color | #27ae60 |
| Background color | #f4f6f9 |
| Icon 512px | ruta a tu icon-512.png |

### 3.3 Generar el keystore (firma de la app)

Cuando Bubblewrap te pida crear un keystore, **guarda bien**:
- El archivo `.keystore` que genera (copia de seguridad en lugar seguro)
- La contraseña del keystore
- El alias de la clave

```bash
bubblewrap build
```

### 3.4 Obtener el SHA-256 para assetlinks.json

```bash
bubblewrap fingerprint list
```

Copia el SHA-256 que aparece. Ejemplo:
```
AB:CD:12:34:56:78:...
```

Ponlo en Render como variable de entorno `TWA_SHA256_CERT`.

---

## PASO 4: Configurar assetlinks.json

El archivo se sirve automáticamente desde `/. well-known/assetlinks.json`
gracias a la ruta que agregamos en `app.py`.

Verifica que funciona correctamente:
```
https://TU_DOMINIO.com/.well-known/assetlinks.json
```

Debe devolver un JSON con tu package name y SHA-256.

Google también tiene una herramienta de verificación:
https://developers.google.com/digital-asset-links/tools/generator

---

## PASO 5: Publicar en Google Play Store

### 5.1 Crear cuenta de desarrollador

- Ve a [play.google.com/console](https://play.google.com/console)
- Crea cuenta ($25 USD pago único)

### 5.2 Crear la app

1. **Crear aplicación**
2. Nombre: "ERP Pecuario"
3. Tipo: Aplicación
4. ¿Es gratuita?: Sí (con compras in-app para Premium)

### 5.3 Lo que necesitas tener listo

| Asset | Especificación | Dónde crear |
|---|---|---|
| Ícono de app | 512×512 PNG, fondo sólido | Canva, Figma |
| Feature graphic | 1024×500 PNG | Canva |
| Screenshots (mínimo 2) | 1080×1920 PNG | Captura de pantalla del celular |
| Descripción corta | Máx. 80 caracteres | — |
| Descripción larga | Máx. 4000 caracteres | — |
| Política de privacidad | URL pública | https://TU_DOMINIO.com/privacidad |

### 5.4 Subir el APK/AAB

El archivo `app-release.aab` lo genera Bubblewrap en el paso 3.2.

En Play Console: **Versiones** → **Producción** → **Crear versión nueva** → subir el `.aab`

### 5.5 Completar la ficha

Completa todas las secciones:
- Clasificación de contenido (el cuestionario tarda ~10 minutos)
- Precio y distribución (todos los países, o solo Ecuador/Latinoamérica)
- Política de privacidad: `https://TU_DOMINIO.com/privacidad`

### 5.6 Enviar a revisión

La revisión de Google tarda entre **1 y 7 días hábiles** para apps nuevas.

---

## CHECKLIST FINAL antes de publicar

- [ ] App accesible en HTTPS sin errores
- [ ] `/.well-known/assetlinks.json` responde correctamente
- [ ] `/privacidad` accesible sin login
- [ ] `/manifest.json` tiene todos los campos requeridos
- [ ] Score de Lighthouse PWA ≥ 80 (verifica en Chrome DevTools)
- [ ] `.aab` generado con Bubblewrap y firmado
- [ ] Cuenta de Play Console activa ($25 pagados)
- [ ] Ícono 512×512 y Feature Graphic 1024×500 listos
- [ ] Al menos 2 screenshots del celular
- [ ] Clasificación de contenido completada

---

## Solución de problemas frecuentes

**"El navegador no reconoce la app como TWA"**
→ El assetlinks.json debe estar en HTTPS, sin errores de JSON y sin redirecciones.

**"Render hiberna mi app"**
→ Usa el plan Starter ($7/mes) o configura un cron job externo que haga ping cada 14 minutos.

**"Bubblewrap dice que el manifest no es válido"**
→ Verifica que `/manifest.json` tenga `start_url`, `display: standalone`, ícono de al menos 512px y `theme_color`.

**"Google rechaza la app"**
→ Los motivos más comunes son: política de privacidad faltante, ícono de baja calidad, o declaración incorrecta de permisos. Lee el email de rechazo con detalle.
