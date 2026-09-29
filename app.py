import hashlib
import os
import secrets
import smtplib
import ssl
import re
from datetime import datetime, timedelta, timezone
from email.message import EmailMessage
from functools import wraps

from cryptography.fernet import Fernet
from dotenv import load_dotenv
from flask import Flask, jsonify, render_template, request, session

try:
    from supabase import create_client
except ImportError:
    create_client = None

load_dotenv()
app = Flask(__name__)
app.config.update(
    SECRET_KEY=os.getenv("FLASK_SECRET_KEY", "local-development-key-change-me"),
    SESSION_COOKIE_HTTPONLY=True,
    SESSION_COOKIE_SAMESITE="Lax",
)
DEMO_MODE = os.getenv("DEMO_MODE", "true").lower() == "true"
SUPER_ADMIN_PASSWORD = os.getenv("SUPER_ADMIN_PASSWORD", "admin123")
# Colombia keeps UTC-5 throughout the year; a fixed zone avoids OS tzdata
# dependencies on minimal Windows/Python installations.
BOGOTA = timezone(timedelta(hours=-5), name="America/Bogota")


def supabase_client(service=False):
    """Use service key for trusted server-only database/admin operations."""
    if not create_client or not os.getenv("SUPABASE_URL"):
        return None
    # Nombres nuevos de Supabase; los antiguos se conservan como compatibilidad.
    key = (
        os.getenv("SUPABASE_SECRET_KEY") or os.getenv("SUPABASE_SERVICE_KEY")
        if service
        else os.getenv("SUPABASE_PUBLISHABLE_KEY") or os.getenv("SUPABASE_KEY")
    )
    return create_client(os.environ["SUPABASE_URL"], key) if key else None


def using_supabase():
    return (
        not DEMO_MODE
        and supabase_client() is not None
        and supabase_client(True) is not None
    )


def now():
    return datetime.now(BOGOTA)


def today():
    return now().date().isoformat()


def encrypt_document(value):
    key = os.getenv("DOCUMENT_ENCRYPTION_KEY")
    if not key:
        if DEMO_MODE:
            return "demo-encrypted-document"
        raise ValueError("Falta DOCUMENT_ENCRYPTION_KEY en el archivo .env")
    return Fernet(key.encode()).encrypt(value.encode()).decode()


def valid_password(password):
    return (
        len(password) >= 10
        and not any(char.isspace() for char in password)
        and any(char.isupper() for char in password)
        and any(char.islower() for char in password)
        and any(char.isdigit() for char in password)
    )


def valid_email(email):
    return " " not in email and "@" in email and email.endswith(".com")


def valid_name(value):
    """Nombres y apellidos: letras Unicode, sin espacios, máximo varchar(20)."""
    return value.isalpha() and len(value) <= 20


def valid_document_number(value):
    return value.isdigit() and len(value) <= 15


def query_first(query):
    """Compatible con Supabase nuevo: evita errores de maybe_single cuando no hay filas."""
    response = query.limit(1).execute()
    rows = response.data or []
    return rows[0] if rows else None


def is_late(check_in, schedule_start):
    """Un ingreso posterior a la hora inicial del turno asignado cuenta como retardo."""
    return bool(check_in and schedule_start and check_in > schedule_start[:5])


def schedule_for_check_in(timestamp):
    """Asigna turno por la hora de ingreso, no al momento de registrar el perfil."""
    return 1 if timestamp.time().strftime("%H:%M") < "13:00" else 2


def schedule_id_from_record(record):
    """Compatibilidad para asistencias antiguas creadas antes del turno dinámico."""
    if record.get("work_schedule_id"):
        return record["work_schedule_id"]
    return 1 if (record.get("check_in") or "00:00")[:5] < "13:00" else 2


def require_session(role=None):
    """Bloquea las APIs internas y, cuando aplica, comprueba el rol solicitado."""

    def decorator(view):
        @wraps(view)
        def wrapped(*args, **kwargs):
            if not session.get("user"):
                return jsonify({"error": "Sesión requerida"}), 401
            if role and session["user"]["role"] != role:
                return jsonify({"error": "No autorizado"}), 403
            return view(*args, **kwargs)

        return wrapped

    return decorator


DEMO_USERS = {
    "admin@positivus.com": {
        "id": "admin-demo",
        "first_name": "Ana",
        "last_name": "Admin",
        "role": "admin",
        "password": "Admin12345",
    },
    "empleado@positivus.com": {
        "id": "employee-demo",
        "first_name": "Camila",
        "last_name": "Torres",
        "role": "employee",
        "document_type": "Cédula de ciudadanía",
        "employment_type": "employee",
        "password": "Empleado123",
    },
}
DEMO_ATTENDANCE = [
    {
        "employee_id": "employee-demo",
        "date": "2026-09-18",
        "check_in": "07:58",
        "check_out": "17:12",
    },
    {
        "employee_id": "employee-demo",
        "date": "2026-09-17",
        "check_in": "08:18",
        "check_out": "17:01",
    },
]
DEMO_CODES = {}


def send_code_email(email, code):
    """Envía con Gmail SMTP; en demo escribe el código en el log local."""
    gmail_user, gmail_password = os.getenv("GMAIL_USER"), os.getenv(
        "GMAIL_APP_PASSWORD"
    )
    if not gmail_user or not gmail_password:
        app.logger.warning("Modo local: código para %s: %s", email, code)
        return False
    message = EmailMessage()
    message["Subject"] = "Tu código de ingreso | ControlAsist"
    message["From"], message["To"] = gmail_user, email
    message.set_content(
        f"Tu código de verificación es {code}. Caduca en 5 minutos, es de un solo uso y tiene máximo 3 intentos."
    )
    with smtplib.SMTP_SSL(
        "smtp.gmail.com", 465, context=ssl.create_default_context()
    ) as smtp:
        smtp.login(gmail_user, gmail_password)
        smtp.send_message(message)
    return True


def attendance_row(row):
    return {
        "date": row["attendance_date"],
        "check_in": format_time(row.get("check_in")),
        "check_out": format_time(row.get("check_out")),
    }


def format_time(value):
    if not value:
        return None
    # Postgres puede devolver microsegundos con distinta precisión. Python 3.10
    # no acepta todas esas variantes con fromisoformat(), así que hay respaldo.
    timestamp = value.replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(timestamp)
    except ValueError:
        match = re.fullmatch(
            r"(\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2})(?:\.\d+)?([+-]\d{2}:\d{2})",
            timestamp,
        )
        if not match:
            raise ValueError(f"Marca de tiempo no válida: {value}")
        parsed = datetime.strptime(
            f"{match.group(1)}{match.group(2).replace(':', '')}",
            "%Y-%m-%dT%H:%M:%S%z",
        )
    return parsed.astimezone(BOGOTA).strftime("%H:%M")


def is_active_code(entry):
    """Centraliza las reglas de vigencia para no reutilizar códigos vencidos o gastados."""
    expires_at = entry["expires_at"]
    if isinstance(expires_at, str):
        expires_at = datetime.fromisoformat(expires_at.replace("Z", "+00:00"))
    return (
        not entry["used"]
        and entry["attempts"] < 3
        and expires_at > datetime.now(timezone.utc)
    )


@app.get("/")
def index():
    return render_template("index.html")


@app.get("/empleado")
@require_session("employee")
def employee_page():
    return render_template("employee.html")


@app.get("/administrador")
@require_session("admin")
def admin_page():
    return render_template("admin.html")


@app.get("/api/session")
def get_session():
    return jsonify({"user": session.get("user")})


@app.post("/api/register")
def register():
    payload = request.get_json() or {}
    needed = (
        "email",
        "first_name",
        "last_name",
        "document_type",
        "document_number",
        "password",
        "password_confirmation",
        "super_admin_password",
    )
    if any(not str(payload.get(field, "")).strip() for field in needed):
        return jsonify({"error": "Completa todos los campos"}), 400
    email = payload["email"].lower().strip()
    first_name, last_name = payload["first_name"].strip(), payload["last_name"].strip()
    if payload["super_admin_password"] != SUPER_ADMIN_PASSWORD:
        return jsonify({"error": "La contraseña Super Admin no es correcta"}), 403
    if not valid_email(email):
        return (
            jsonify(
                {
                    "error": "El correo debe incluir @, terminar en .com y no tener espacios"
                }
            ),
            400,
        )
    if not (valid_name(first_name) and valid_name(last_name)):
        return (
            jsonify(
                {
                    "error": "Nombre y apellido: solo letras, sin espacios y máximo 20 caracteres"
                }
            ),
            400,
        )
    if not valid_document_number(str(payload["document_number"])):
        return (
            jsonify({"error": "El documento solo puede contener hasta 15 dígitos"}),
            400,
        )
    if payload["password"] != payload["password_confirmation"]:
        return jsonify({"error": "Las contraseñas no coinciden"}), 400
    if not valid_password(payload["password"]):
        return (
            jsonify(
                {
                    "error": "La contraseña requiere 10 caracteres, mayúscula, minúscula, número y sin espacios"
                }
            ),
            400,
        )
    try:
        if using_supabase():
            db = supabase_client(True)
            created = db.auth.admin.create_user(
                {"email": email, "password": payload["password"], "email_confirm": True}
            )
            user_id = created.user.id
            db.table("profiles").insert(
                {
                    "id": user_id,
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "document_type": payload["document_type"],
                    "document_number_encrypted": encrypt_document(
                        str(payload["document_number"])
                    ),
                    "role": "employee",
                }
            ).execute()
            user = {
                "id": user_id,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": "employee",
            }
        else:
            if email in DEMO_USERS:
                return jsonify({"error": "Este correo ya está registrado"}), 409
            user = {
                "id": f"demo-{secrets.token_hex(4)}",
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "role": "employee",
            }
            DEMO_USERS[email] = {
                **user,
                "password": payload["password"],
                "document_type": payload["document_type"],
                "employment_type": "employee",
            }
    except Exception as exc:
        return jsonify({"error": f"No fue posible crear la cuenta: {exc}"}), 400
    session["user"] = user
    return jsonify({"message": "Cuenta creada correctamente", "user": user})


@app.get("/api/document-types")
def document_types():
    """Catálogo para formularios: no se deben quemar tipos documentales en HTML."""
    if using_supabase():
        rows = (
            supabase_client(True)
            .table("document_types")
            .select("id,name")
            .order("name")
            .execute()
            .data
        )
    else:
        rows = [
            {"id": 1, "name": "Cédula de ciudadanía"},
            {"id": 2, "name": "Cédula de extranjería"},
            {"id": 3, "name": "Pasaporte"},
        ]
    return jsonify({"rows": rows})


@app.get("/api/work-schedules")
def work_schedules():
    if using_supabase():
        rows = (
            supabase_client(True)
            .table("work_schedules")
            .select("id,name,start_time,end_time")
            .order("start_time")
            .execute()
            .data
        )
    else:
        rows = [
            {
                "id": 1,
                "name": "Mañana · 08:00–13:00",
                "start_time": "08:00:00",
                "end_time": "13:00:00",
            },
            {
                "id": 2,
                "name": "Tarde · 13:00–17:00",
                "start_time": "13:00:00",
                "end_time": "17:00:00",
            },
        ]
    return jsonify({"rows": rows})


@app.post("/api/login")
def login():
    payload = request.get_json() or {}
    email, password = str(payload.get("email", "")).lower().strip(), payload.get(
        "password", ""
    )
    try:
        if using_supabase():
            authenticated = supabase_client().auth.sign_in_with_password(
                {"email": email, "password": password}
            )
            user = (
                supabase_client(True)
                .table("profiles")
                .select("id,email,first_name,last_name,role")
                .eq("id", authenticated.user.id)
                .single()
                .execute()
                .data
            )
        else:
            candidate = DEMO_USERS.get(email)
            if not candidate or candidate["password"] != password:
                raise ValueError("invalid credentials")
            user = {
                key: candidate[key] for key in ("id", "first_name", "last_name", "role")
            }
            user["email"] = email
    except Exception:
        return jsonify({"error": "Correo o contraseña incorrectos"}), 401
    session.clear()
    session["user"] = user
    return jsonify({"user": user})


@app.post("/api/logout")
def logout():
    session.clear()
    return jsonify({"message": "Sesión cerrada"})


@app.get("/api/employee/attendance")
@require_session("employee")
def employee_attendance():
    employee_id = session["user"]["id"]
    if using_supabase():
        records = (
            supabase_client(True)
            .table("attendance")
            .select("attendance_date,check_in,check_out")
            .eq("employee_id", employee_id)
            .order("attendance_date", desc=True)
            .execute()
            .data
        )
        rows = [attendance_row(row) for row in records]
    else:
        rows = [
            {k: row[k] for k in ("date", "check_in", "check_out")}
            for row in DEMO_ATTENDANCE
            if row["employee_id"] == employee_id
        ]
        rows.sort(key=lambda row: row["date"], reverse=True)
    return jsonify(
        {
            "rows": rows,
            "today": next((row for row in rows if row["date"] == today()), None),
        }
    )


@app.get("/api/employee/profile")
@require_session("employee")
def employee_profile():
    """Nunca devuelve el documento cifrado ni permite cambiar su número."""
    user = session["user"]
    if using_supabase():
        profile = (
            supabase_client(True)
            .table("profiles")
            .select("email,first_name,last_name,document_type,employment_type")
            .eq("id", user["id"])
            .single()
            .execute()
            .data
        )
    else:
        profile = {
            key: DEMO_USERS[user["email"]].get(key, "employee")
            for key in (
                "email",
                "first_name",
                "last_name",
                "document_type",
                "employment_type",
            )
        }
    return jsonify({"profile": profile})


@app.put("/api/employee/profile")
@require_session("employee")
def update_employee_profile():
    """El propio empleado/practicante edita sus datos excepto número documental."""
    payload = request.get_json() or {}
    user = session["user"]
    email = str(payload.get("email", "")).lower().strip()
    first_name = str(payload.get("first_name", "")).strip()
    last_name = str(payload.get("last_name", "")).strip()
    document_type = str(payload.get("document_type", "")).strip()
    if not valid_email(email):
        return (
            jsonify(
                {
                    "error": "El correo debe incluir @, terminar en .com y no tener espacios"
                }
            ),
            400,
        )
    if not (valid_name(first_name) and valid_name(last_name)):
        return (
            jsonify(
                {
                    "error": "Nombre y apellido: solo letras, sin espacios y máximo 20 caracteres"
                }
            ),
            400,
        )
    if not document_type:
        return jsonify({"error": "Selecciona un tipo de documento"}), 400
    try:
        if using_supabase():
            db = supabase_client(True)
            allowed = query_first(
                db.table("document_types").select("id").eq("name", document_type)
            )
            if not allowed:
                return jsonify({"error": "Tipo de documento no válido"}), 400
            db.auth.admin.update_user_by_id(
                user["id"], {"email": email, "email_confirm": True}
            )
            db.table("profiles").update(
                {
                    "email": email,
                    "first_name": first_name,
                    "last_name": last_name,
                    "document_type": document_type,
                }
            ).eq("id", user["id"]).execute()
        else:
            current = DEMO_USERS.pop(user["email"])
            if email in DEMO_USERS:
                DEMO_USERS[user["email"]] = current
                return jsonify({"error": "Este correo ya está registrado"}), 409
            DEMO_USERS[email] = {
                **current,
                "email": email,
                "first_name": first_name,
                "last_name": last_name,
                "document_type": document_type,
            }
        session["user"].update(
            {"email": email, "first_name": first_name, "last_name": last_name}
        )
        return jsonify(
            {"message": "Datos actualizados correctamente", "user": session["user"]}
        )
    except Exception as exc:
        return jsonify({"error": f"No fue posible actualizar los datos: {exc}"}), 400


@app.post("/api/employee/request-code")
@require_session("employee")
def request_code():
    employee_id, current_day = session["user"]["id"], today()
    try:
        if using_supabase():
            db = supabase_client(True)
            existing = query_first(
                db.table("verification_codes")
                .select("*")
                .eq("employee_id", employee_id)
                .eq("attendance_date", current_day)
            )
            if existing and is_active_code(existing):
                return jsonify(
                    {
                        "message": "Ya tienes un código activo. Revisa el correo anterior.",
                        "reused": True,
                    }
                )
        else:
            existing = DEMO_CODES.get(f"{employee_id}:{current_day}")
            if existing and is_active_code(existing):
                return jsonify(
                    {
                        "message": "Ya tienes un código activo. Revisa el correo anterior.",
                        "reused": True,
                    }
                )
        code = f"{secrets.randbelow(1_000_000):06d}"
        code_hash, expires_at = hashlib.sha256(code.encode()).hexdigest(), datetime.now(
            timezone.utc
        ) + timedelta(minutes=5)
        if using_supabase():
            supabase_client(True).table("verification_codes").upsert(
                {
                    "employee_id": employee_id,
                    "attendance_date": current_day,
                    "code_hash": code_hash,
                    "expires_at": expires_at.isoformat(),
                    "attempts": 0,
                    "used": False,
                },
                on_conflict="employee_id,attendance_date",
            ).execute()
        else:
            DEMO_CODES[f"{employee_id}:{current_day}"] = {
                "hash": code_hash,
                "expires_at": expires_at,
                "attempts": 0,
                "used": False,
            }
        send_code_email(session["user"]["email"], code)
        return jsonify({"message": "Código enviado al correo", "reused": False})
    except Exception as exc:
        return jsonify({"error": f"No fue posible enviar el código: {exc}"}), 500


@app.post("/api/employee/verify-code")
@require_session("employee")
def verify_code():
    employee_id, current_day = session["user"]["id"], today()
    submitted_hash = hashlib.sha256(
        str((request.get_json() or {}).get("code", "")).encode()
    ).hexdigest()
    try:
        if using_supabase():
            db = supabase_client(True)
            entry = query_first(
                db.table("verification_codes")
                .select("*")
                .eq("employee_id", employee_id)
                .eq("attendance_date", current_day)
            )
            saved_hash = entry["code_hash"]
        else:
            db, entry = None, DEMO_CODES.get(f"{employee_id}:{current_day}")
            saved_hash = entry["hash"] if entry else ""
        if not entry or not is_active_code(entry):
            return (
                jsonify({"error": "El código expiró o superó el límite de intentos"}),
                400,
            )
        attempts = entry["attempts"] + 1
        if submitted_hash != saved_hash:
            if using_supabase():
                db.table("verification_codes").update({"attempts": attempts}).eq(
                    "id", entry["id"]
                ).execute()
            else:
                entry["attempts"] = attempts
            return (
                jsonify({"error": f"Código incorrecto. Intento {attempts} de 3"}),
                400,
            )
        check_in_time = now()
        timestamp = check_in_time.isoformat()
        if using_supabase():
            db.table("verification_codes").update(
                {"attempts": attempts, "used": True}
            ).eq("id", entry["id"]).execute()
            db.table("attendance").upsert(
                {
                    "employee_id": employee_id,
                    "attendance_date": current_day,
                    "check_in": timestamp,
                    "work_schedule_id": schedule_for_check_in(check_in_time),
                },
                on_conflict="employee_id,attendance_date",
            ).execute()
        else:
            entry["used"] = True
            DEMO_ATTENDANCE.insert(
                0,
                {
                    "employee_id": employee_id,
                    "date": current_day,
                    "check_in": now().strftime("%H:%M"),
                    "check_out": None,
                    "work_schedule_id": schedule_for_check_in(check_in_time),
                },
            )
        return jsonify({"message": "Ingreso registrado correctamente"})
    except Exception as exc:
        return jsonify({"error": f"No fue posible validar el código: {exc}"}), 500


@app.post("/api/employee/check-out")
@require_session("employee")
def check_out():
    employee_id, current_day = session["user"]["id"], today()
    if using_supabase():
        db = supabase_client(True)
        record = (
            db.table("attendance")
            .select("*")
            .eq("employee_id", employee_id)
            .eq("attendance_date", current_day)
            .single()
            .execute()
            .data
        )
        if not record or not record["check_in"] or record["check_out"]:
            return jsonify({"error": "No hay un ingreso abierto para hoy"}), 400
        db.table("attendance").update({"check_out": now().isoformat()}).eq(
            "id", record["id"]
        ).execute()
    else:
        record = next(
            (
                r
                for r in DEMO_ATTENDANCE
                if r["employee_id"] == employee_id and r["date"] == current_day
            ),
            None,
        )
        if not record or not record["check_in"] or record["check_out"]:
            return jsonify({"error": "No hay un ingreso abierto para hoy"}), 400
        record["check_out"] = now().strftime("%H:%M")
    return jsonify({"message": "Salida registrada correctamente"})


def demo_admin_rows():
    names = {
        value["id"]: f"{value['first_name']} {value['last_name']}"
        for value in DEMO_USERS.values()
    }
    return [
        {
            "employee_id": r["employee_id"],
            "name": names.get(r["employee_id"], "Empleado"),
            "date": r["date"],
            "check_in": r["check_in"],
            "check_out": r["check_out"],
        }
        for r in DEMO_ATTENDANCE
    ]


@app.get("/api/admin/summary")
@require_session("admin")
def admin_summary():
    start, end, employee_filter = (
        request.args.get("start"),
        request.args.get("end"),
        request.args.get("employee", "").lower(),
    )
    if using_supabase():
        db = supabase_client(True)
        profiles = (
            db.table("profiles")
            .select("id,first_name,last_name,email")
            .eq("role", "employee")
            .execute()
            .data
        )
        profile_map = {p["id"]: p for p in profiles}
        schedules = (
            db.table("work_schedules")
            .select("id,start_time,end_time,name")
            .execute()
            .data
        )
        schedule_map = {schedule["id"]: schedule for schedule in schedules}
        records = (
            db.table("attendance")
            .select("employee_id,attendance_date,check_in,check_out,work_schedule_id")
            .order("attendance_date", desc=True)
            .execute()
            .data
        )
        rows = [
            {
                "employee_id": r["employee_id"],
                "name": f"{profile_map.get(r['employee_id'], {}).get('first_name','')} {profile_map.get(r['employee_id'], {}).get('last_name','')}",
                "schedule": schedule_map.get(schedule_id_from_record(r), {}).get(
                    "name", "Sin turno"
                ),
                "schedule_start": schedule_map.get(schedule_id_from_record(r), {}).get(
                    "start_time"
                ),
                **attendance_row(r),
            }
            for r in records
        ]
        employees_count = len(profiles)
    else:
        rows, employees_count = demo_admin_rows(), len(
            [u for u in DEMO_USERS.values() if u["role"] == "employee"]
        )
    rows = [
        r
        for r in rows
        if (not start or r["date"] >= start)
        and (not end or r["date"] <= end)
        and (not employee_filter or employee_filter in r["name"].lower())
    ]
    for row in rows:
        row["status"] = (
            "Pendiente"
            if not row["check_out"]
            else (
                "Retardo"
                if is_late(row["check_in"], row.get("schedule_start", "08:00"))
                else "A tiempo"
            )
        )
        if row["check_in"] and row["check_out"]:
            a, b = datetime.strptime(row["check_in"], "%H:%M"), datetime.strptime(
                row["check_out"], "%H:%M"
            )
            row["hours"] = round((b - a).seconds / 3600, 2)
        else:
            row["hours"] = 0
    completed, late = [r for r in rows if r["check_in"]], [
        r for r in rows if r["status"] == "Retardo"
    ]
    chart = []
    for label, offset in zip(
        ["Lun", "Mar", "Mié", "Jue", "Vie", "Sáb", "Dom"], range(7)
    ):
        day = (
            now().date() - timedelta(days=now().weekday()) + timedelta(days=offset)
        ).isoformat()
        chart.append(
            {
                "day": label,
                "value": sum(r["date"] == day and bool(r["check_in"]) for r in rows),
            }
        )
    max_value = max(1, *(x["value"] for x in chart))
    for point in chart:
        point["percent"] = max(8, round(point["value"] / max_value * 100))
    return jsonify(
        {
            "stats": {
                "present": len(completed),
                "late": len(late),
                "hours": round(sum(r["hours"] for r in rows), 1),
                "employees": employees_count,
            },
            "chart": chart,
            "rows": rows,
        }
    )


@app.post("/api/admin/change-password")
@require_session("admin")
def change_password():
    """Administra contraseña y documento cifrado del empleado indicado."""
    payload = request.get_json() or {}
    password = str(payload.get("password", ""))
    document_number = str(payload.get("document_number", ""))
    if not any((password, document_number)):
        return (
            jsonify({"error": "Indica una contraseña o documento para actualizar"}),
            400,
        )
    if password and not valid_password(password):
        return (
            jsonify(
                {
                    "error": "La contraseña requiere 10 caracteres, mayúscula, minúscula, número y sin espacios"
                }
            ),
            400,
        )
    if document_number and not valid_document_number(document_number):
        return (
            jsonify({"error": "El documento solo puede contener hasta 15 dígitos"}),
            400,
        )
    email = str(payload.get("email", "")).lower().strip()
    if using_supabase():
        try:
            db = supabase_client(True)
            profile = (
                db.table("profiles")
                .select("id,role")
                .eq("email", email)
                .single()
                .execute()
                .data
            )
            if profile["role"] != "employee":
                return jsonify({"error": "Solo se pueden gestionar empleados"}), 400
            if password:
                db.auth.admin.update_user_by_id(profile["id"], {"password": password})
            updates = {}
            if document_number:
                updates["document_number_encrypted"] = encrypt_document(document_number)
            if updates:
                db.table("profiles").update(updates).eq("id", profile["id"]).execute()
        except Exception:
            return jsonify({"error": "No se encontró el empleado"}), 404
    else:
        if email not in DEMO_USERS or DEMO_USERS[email]["role"] != "employee":
            return jsonify({"error": "No se encontró el empleado"}), 404
        if password:
            DEMO_USERS[email]["password"] = password
    return jsonify({"message": "Datos del empleado actualizados correctamente"})


@app.post("/api/employee/change-password")
@require_session("employee")
def employee_change_password():
    """El empleado/practicante cambia únicamente su propia contraseña."""
    payload = request.get_json() or {}
    password = str(payload.get("password", ""))
    confirmation = str(payload.get("password_confirmation", ""))
    if password != confirmation:
        return jsonify({"error": "Las contraseñas no coinciden"}), 400
    if not valid_password(password):
        return (
            jsonify(
                {
                    "error": "La contraseña requiere 10 caracteres, mayúscula, minúscula, número y sin espacios"
                }
            ),
            400,
        )
    user = session["user"]
    try:
        if using_supabase():
            supabase_client(True).auth.admin.update_user_by_id(
                user["id"], {"password": password}
            )
        else:
            DEMO_USERS[user["email"]]["password"] = password
        return jsonify({"message": "Contraseña actualizada correctamente"})
    except Exception:
        return jsonify({"error": "No fue posible actualizar la contraseña"}), 400


if __name__ == "__main__":
    # Para escritorio local no se habilita el depurador salvo que se pida en .env.
    app.run(debug=os.getenv("FLASK_DEBUG", "false").lower() == "true", port=5000)
