"""Small email transport abstraction; no credentials or message bodies are persisted."""

from email.message import EmailMessage
from html import escape
import logging
import smtplib

from app.core.config import Settings, get_settings


logger = logging.getLogger(__name__)


class EmailService:
    """Deliver an already-rendered message through SMTP or a development backend."""

    mock_outbox: list[dict[str, str]] = []

    def __init__(self, settings: Settings | None = None):
        self.settings = settings or get_settings()

    def send(self, *, recipient: str, subject: str, text_body: str, html_body: str, message_id: str | None = None) -> None:
        backend = self.settings.email_backend
        if backend == "mock":
            self.mock_outbox.append({
                "recipient": recipient,
                "subject": subject,
                "text_body": text_body,
                "html_body": html_body,
            })
            return
        if backend == "console":
            logger.info("Email(console) to=%s subject=%s\n%s", recipient, subject, text_body)
            return

        message = EmailMessage()
        message["Subject"] = subject
        message["From"] = f"{self.settings.smtp_from_name} <{self.settings.smtp_from_email}>"
        message["To"] = recipient
        if message_id:
            message["Message-ID"] = message_id
        message.set_content(text_body)
        message.add_alternative(html_body, subtype="html")
        with smtplib.SMTP(self.settings.smtp_host, self.settings.smtp_port, timeout=20) as client:
            if self.settings.smtp_use_tls:
                client.starttls()
            if self.settings.smtp_username:
                client.login(self.settings.smtp_username, self.settings.smtp_password or "")
            client.send_message(message)


LABELS = {
    "en": {
        "summary": "Summary", "vehicle_driver": "Vehicle / Driver", "due": "Due Date",
        "priority": "Priority", "open": "Open in VehicleFleetControl",
    },
    "sq": {
        "summary": "Përmbledhje", "vehicle_driver": "Automjeti / Shoferi", "due": "Data e afatit",
        "priority": "Prioriteti", "open": "Hap në VehicleFleetControl",
    },
}

SQ_TITLES = {
    "Service due soon": "Servisi po afron",
    "Service overdue": "Servisit i ka kaluar afati",
    "Driver licence expiring": "Patenta po skadon",
    "Driver licence expired": "Patenta ka skaduar",
    "Inspection failed": "Inspektimi dështoi",
    "Inspection item failed": "Një pikë e inspektimit dështoi",
    "Inspection required": "Kërkohet inspektim",
    "Critical Work Order created": "U krijua një Urdhër Pune kritik",
    "Work Order overdue": "Urdhrit të Punës i ka kaluar afati",
    "Reservation pending approval": "Rezervimi pret miratim",
    "Reservation starting soon": "Rezervimi fillon së shpejti",
    "Reservation overdue for return": "Kthimit të rezervimit i ka kaluar afati",
    "Vehicle return overdue": "Kthimit të automjetit i ka kaluar afati",
    "Program task due": "Detyra e programit të mirëmbajtjes është në afat",
    "Part low stock": "Stok i ulët i pjesës",
    "Insurance claim reminder": "Përkujtues për kërkesën e sigurimit",
}

SQ_SUMMARIES = {
    "Service due soon": "{plate} kërkon {service_type}.",
    "Service overdue": "{plate} kërkon {service_type}.",
    "Document compliance missing": "{owner} · dokumenti mungon.",
    "Document compliance expired": "{owner} · dokumenti ka skaduar më {date}.",
    "Document compliance expiring soon": "{owner} · dokumenti skadon më {date}.",
    "Document compliance renewal in progress": "{owner} · rinovimi është në proces.",
    "Document compliance rejected": "{owner} · dokumenti u refuzua.",
    "Driver licence expiring": "Patenta e {name} skadon më {date}.",
    "Driver licence expired": "Patenta e {name} ka skaduar më {date}.",
    "Inspection failed": "Automjeti #{vehicle_id} kërkon vëmendje.",
    "Inspection item failed": "Pika {item} kërkon vëmendje.",
    "Inspection required": "Kërkohet inspektimi #{id} për automjetin #{vehicle_id}.",
    "Critical Work Order created": "Urdhri i Punës #{id}: {title}",
    "Work Order overdue": "Urdhri i Punës #{id}: {title}",
    "Reservation pending approval": "{plate} për {reserved_by}.",
    "Reservation starting soon": "{plate} për {reserved_by}.",
    "Reservation overdue for return": "{plate} duhej të ishte kthyer.",
    "Vehicle return overdue": "{plate} · {driver}",
    "Program task due": "{plate}: {title} ({status}).",
    "Part low stock": "{part_number}: {quantity} {unit} · {location}.",
    "Insurance claim reminder": "Kërkesa për aksidentin #{id} kërkon vëmendje.",
}

PRIORITIES_SQ = {"Low": "I ulët", "Medium": "Mesatar", "High": "I lartë", "Critical": "Kritik"}


def _record_url(notification, base_url: str) -> str:
    paths = {
        "VehicleService": "/services/{id}",
        "WorkOrder": "/work-orders/{id}",
        "Driver": "/drivers/{id}",
        "Inspection": "/inspections/{id}",
        "VehicleAssignment": "/vehicle-assignments/{id}",
        "VehicleReservation": "/reservations",
        "VehicleAccident": "/accidents/{id}",
        "AccidentClaim": "/accidents",
        "VehiclePaper": "/compliance/documents",
        "DocumentRequirement": "/compliance/documents",
        "ServiceProgramReminder": "/maintenance/programs",
        "Part": "/maintenance/inventory",
    }
    pattern = paths.get(notification.entity_type, "/notifications")
    path = pattern.format(id=notification.entity_id) if "{id}" in pattern and notification.entity_id else pattern
    return f"{base_url.rstrip('/')}{path}"


def render_notification_email(notification, language: str, base_url: str) -> tuple[str, str, str]:
    language = language if language in LABELS else "en"
    labels = LABELS[language]
    params = notification.message_params or {}
    title = SQ_TITLES.get(notification.notification_type, notification.title) if language == "sq" else notification.title
    summary_template = SQ_SUMMARIES.get(notification.notification_type) if language == "sq" else None
    try:
        summary = summary_template.format_map(params) if summary_template else notification.message
    except KeyError:
        summary = notification.message
    subject = f"[VehicleFleetControl] {title}"
    vehicle_driver = " · ".join(str(value) for value in (
        params.get("plate") or params.get("license_plate") or params.get("owner") or params.get("vehicle_id"),
        params.get("driver") or params.get("name"),
    ) if value not in (None, "")) or "-"
    due_date = str(params.get("date") or params.get("due_date") or "-")
    priority = PRIORITIES_SQ.get(notification.priority, notification.priority) if language == "sq" else notification.priority
    url = _record_url(notification, base_url)
    rows = (
        (labels["summary"], summary),
        (labels["vehicle_driver"], vehicle_driver),
        (labels["due"], due_date),
        (labels["priority"], priority),
    )
    text = title + "\n\n" + "\n".join(f"{label}: {value}" for label, value in rows) + f"\n\n{labels['open']}: {url}"
    html_rows = "".join(f"<tr><th align='left'>{escape(label)}</th><td>{escape(str(value))}</td></tr>" for label, value in rows)
    html = (
        f"<h1>{escape(title)}</h1><table cellpadding='6'>{html_rows}</table>"
        f"<p><a href='{escape(url, quote=True)}'>{escape(labels['open'])}</a></p>"
    )
    return subject, text, html
