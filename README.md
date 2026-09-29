# Portal Ingresos

Aplicación Flask + Supabase para control de asistencia laboral.

## Ejecutar

```powershell
py -m venv .venv
.\.venv\Scripts\Activate.ps1
pip install -r requirements.txt
Copy-Item .env.example .env
py app.py
```

Abre `http://127.0.0.1:5000`. Con `DEMO_MODE=true` se puede probar la interfaz sin credenciales de Supabase.

En producción, configura Supabase, Gmail SMTP y una clave Fernet en `.env`,
ejecuta `schema.sql` en el SQL Editor y crea el usuario administrador
directamente en Supabase Auth. Para habilitar la persistencia real usa
`DEMO_MODE=false`, `SUPABASE_PUBLISHABLE_KEY` y `SUPABASE_SECRET_KEY`
(solo del servidor). La clave Fernet se obtiene, por ejemplo,
con `py -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.

El servidor guarda la sesión en una cookie HttpOnly; ninguna API interna
responde sin sesión y las rutas de empleado/administrador verifican además
su rol. Los documentos se cifran antes de insertar el perfil.

## Abrir desde el escritorio

Con Python y dependencias ya instaladas, ejecuta una sola vez:

```powershell
powershell -ExecutionPolicy Bypass -File .\crear_acceso_directo.ps1
```

Después usa el acceso directo **ControlAsist** del escritorio. Abre el navegador
y el servidor local mediante `pythonw.exe`, sin dejar una ventana de consola abierta.
Esto no cambia la conexión a Supabase, el archivo `.env` ni Gmail.

## Usuarios demo

- Administrador: `admin@positivus.com` / `Admin12345`
- Empleado: `empleado@positivus.com` / `Empleado123`

El modo demo mantiene los registros en memoria para probar el flujo de interfaz.
Con `DEMO_MODE=false`, registro, acceso, asistencias, códigos y restablecimiento
de contraseña usan Supabase Auth y las tablas creadas por `schema.sql`.
