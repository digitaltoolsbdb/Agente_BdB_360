from contextlib import asynccontextmanager
from datetime import datetime, timezone

from dotenv import load_dotenv
from mcp.server.fastmcp import FastMCP


from services.powerautomate_client import (
    enviar_solicitud_bloqueo,
)


from services.graph_mail_client import GraphMailClient, unlock_attachment_bytes
import os
from services.account_block_client import modify_account_block

# Carga variables desde .env
load_dotenv()

from mcp.server.transport_security import TransportSecuritySettings


@asynccontextmanager
async def mcp_lifespan(app):
    try:
        yield
    finally:
        global _graph_mail
        if _graph_mail is not None:
            await _graph_mail.close()
            _graph_mail = None


# Hosts permitidos configurables por entorno (separados por coma).
# En local, si no se define MCP_ALLOWED_HOSTS, solo se permite localhost.
_default_allowed_hosts = "localhost:*,127.0.0.1:*"
_allowed_hosts = [
    host.strip()
    for host in os.getenv("MCP_ALLOWED_HOSTS", _default_allowed_hosts).split(",")
    if host.strip()
]

mcp = FastMCP(
    "BDB Graph Services MCP",
    stateless_http=True,
    transport_security=TransportSecuritySettings(
        enable_dns_rebinding_protection=True,
        allowed_hosts=_allowed_hosts,
    ),
    lifespan=mcp_lifespan,
)

_graph_mail = None
_otp_store: dict[str, dict[str, int | str]] = {}


def get_mail_client() -> GraphMailClient:
    global _graph_mail
    if _graph_mail is None:
        _graph_mail = GraphMailClient()
    return _graph_mail


DEFAULT_OTP_TEMPLATE = os.getenv("GRAPH_MAIL_OTP_TEMPLATE", "notificacion_otp_banco_bogota.html")
# =====================================================================
# DESBLOQUEO DE CUENTAS
# =====================================================================


@mcp.tool()
async def modificar_bloqueo_cuenta(
    cuenta: str,
    tipo_cuenta: str,
    bloqueos: list[str],
    accion: str = "A",
    trn_code: str = "123",
) -> dict:

    result = await modify_account_block(
        acct_id=cuenta,
        acct_type=tipo_cuenta,
        lock_ids=bloqueos,
        action=accion,
        trn_code=trn_code,
    )

    return result.model_dump()

# =====================================================================
# CORREO ELECTRÓNICO - Mail Service Tools
# =====================================================================

@mcp.tool()
async def mail_send_simple(
    to_recipients: list[str],
    subject: str,
    body: str,
    is_html: bool = False,
    cc_recipients: list[str] | None = None,
    bcc_recipients: list[str] | None = None,
) -> dict:
    """
    Envía un correo electrónico simple.

    Args:
        to_recipients: Lista de direcciones de correo destinatarios
        subject: Asunto del correo
        body: Cuerpo del correo (texto plano o HTML)
        is_html: Si True, el body se trata como HTML; si False, como texto plano
        cc_recipients: Lista de direcciones para CC (opcional)
        bcc_recipients: Lista de direcciones para BCC (opcional)

    Returns:
        Diccionario con información del envío
    """
    client = get_mail_client()
    return await client.send_mail(
        to_recipients=to_recipients,
        subject=subject,
        body=body,
        is_html=is_html,
        cc_recipients=cc_recipients,
        bcc_recipients=bcc_recipients,
    )


@mcp.tool()
async def mail_send_with_attachment(
    to_recipients: list[str],
    subject: str,
    body: str,
    attachment_path: str | None = None,
    is_html: bool = False,
    cc_recipients: list[str] | None = None,
    bcc_recipients: list[str] | None = None,
    base64_content: str | None = None,
    file_name: str | None = None,
) -> dict:
    """
    Envía un correo electrónico con archivo adjunto.

    Args:
        to_recipients: Lista de direcciones de correo destinatarios
        subject: Asunto del correo
        body: Cuerpo del correo
        attachment_path: Ruta al archivo a adjuntar
        is_html: Si True, el body se trata como HTML
        cc_recipients: Lista de direcciones para CC (opcional)
        bcc_recipients: Lista de direcciones para BCC (opcional)

    Returns:
        Diccionario con información del envío
    """
    client = get_mail_client()
    return await client.send_mail_with_attachment(
        to_recipients=to_recipients,
        subject=subject,
        body=body,
        attachment_path=attachment_path,
        is_html=is_html,
        cc_recipients=cc_recipients,
        bcc_recipients=bcc_recipients,
    )


@mcp.tool()
async def unlock_protected_attachment(
    protected_payload: str,
    client_id: str,
) -> dict:
    """Desbloquea un adjunto protegido con la identificación del cliente."""
    try:
        decoded = unlock_attachment_bytes(client_id, protected_payload.encode("utf-8"))
        return {
            "success": True,
            "message": "Adjunto desbloqueado correctamente.",
            "content": decoded.decode("utf-8"),
        }
    except Exception as exc:
        return {
            "success": False,
            "message": str(exc),
        }


@mcp.tool()
async def mail_send_bulk(
    recipients: list[dict],
    subject: str,
    body_template: str,
    is_html: bool = False,
) -> dict:
    """
    Envía correos masivos con personalización.

    Args:
        recipients: Lista de dicts con 'email' y variables personalizadas
                   Ejemplo: [{'email': 'user@example.com', 'name': 'Usuario'}]
        subject: Asunto del correo
        body_template: Template del cuerpo con placeholders {variable}
        is_html: Si True, el body se trata como HTML

    Returns:
        Diccionario con información de envíos exitosos y fallidos
    """
    client = get_mail_client()
    return await client.send_bulk_mail(
        recipients=recipients,
        subject=subject,
        body_template=body_template,
        is_html=is_html,
    )


@mcp.tool()
async def mail_get_mailbox_info() -> dict:
    """
    Obtiene información del buzón del remitente configurado.

    Returns:
        Diccionario con información del usuario/buzón
    """
    client = get_mail_client()
    return await client.get_mailbox_info()


@mcp.tool()
async def verify_otp(client_id: str, otp_code: str) -> dict:
    """
    Verifica si el código OTP proporcionado coincide con el enviado al cliente.
    Máximo 3 intentos. Después de verificación exitosa o 3 fallos, el OTP se elimina.
    """
    stored = _otp_store.get(client_id)

    if not stored:
        return {
            "verified": False,
            "reason": "No hay un código de verificación pendiente para este cliente.",
            "can_retry": False,
        }

    if otp_code == stored["otp"]:
        del _otp_store[client_id]
        return {
            "verified": True,
            "client_id": client_id,
        }
    else:
        stored["attempts"] += 1
        if stored["attempts"] >= 3:
            del _otp_store[client_id]
            return {
                "verified": False,
                "reason": "Se agotaron los intentos de verificación.",
                "attempts": stored["attempts"],
                "can_retry": False,
            }
        return {
            "verified": False,
            "reason": "Código incorrecto.",
            "attempts": stored["attempts"],
            "max_attempts": 3,
            "can_retry": True,
        }