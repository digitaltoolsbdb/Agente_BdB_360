import base64
import hashlib
import os
import re
import secrets
from pathlib import Path
from string import Template

import certifi
import httpx
from azure.identity.aio import ClientSecretCredential
from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

load_dotenv(dotenv_path=ENV_FILE)


def _derive_key(client_id: str) -> bytes:
    secret = os.getenv("MAIL_ATTACHMENT_ENCRYPTION_KEY", "mail-attachment-default-key")
    digest = hashlib.sha256(f"{secret}:{client_id}".encode("utf-8")).digest()
    return digest


def encrypt_bytes_for_client(client_id: str, payload: bytes) -> bytes:
    key = _derive_key(client_id)
    return base64.b64encode(payload + key[:1])


def decrypt_bytes_for_client(client_id: str, payload: bytes) -> bytes:
    decoded = base64.b64decode(payload)
    key_byte = _derive_key(client_id)[:1]
    if decoded.endswith(key_byte):
        return decoded[:-1]
    raise ValueError("Payload no coincide con el cliente o la clave de cifrado")


def unlock_attachment_bytes(client_id: str, payload: bytes) -> bytes:
    """Desbloquea el contenido de un adjunto protegido con la identificación del cliente."""
    return decrypt_bytes_for_client(client_id, payload)


class GraphMailClient:
    def __init__(self) -> None:
        self.tenant_id = os.getenv("GRAPH_TENANT_ID")
        self.client_id = os.getenv("GRAPH_MAIL_CLIENT_ID")
        self.client_secret = os.getenv("GRAPH_MAIL_CLIENT_SECRET")
        self.sender_address = os.getenv("GRAPH_MAIL_SENDER_ADDRESS")

        missing = [n for n, v in {
            "GRAPH_TENANT_ID": self.tenant_id,
            "GRAPH_MAIL_CLIENT_ID": self.client_id,
            "GRAPH_MAIL_CLIENT_SECRET": self.client_secret,
            "GRAPH_MAIL_SENDER_ADDRESS": self.sender_address,
        }.items() if not v]

        if missing:
            raise ValueError(f"Faltan variables: {', '.join(missing)}")

        self.base_url = "https://graph.microsoft.com/v1.0"
        self.ssl_verify = certifi.where()
        os.environ.setdefault("SSL_CERT_FILE", self.ssl_verify)
        os.environ.setdefault("REQUESTS_CA_BUNDLE", self.ssl_verify)
        self.credential = ClientSecretCredential(
            tenant_id=self.tenant_id,
            client_id=self.client_id,
            client_secret=self.client_secret,
        )

    async def close(self) -> None:
        await self.credential.close()

    async def _get_token(self) -> str:
        token = await self.credential.get_token("https://graph.microsoft.com/.default")
        return token.token

    async def _headers(self) -> dict[str, str]:
        return {
            "Authorization": f"Bearer {await self._get_token()}",
            "Content-Type": "application/json",
        }

    def _resolve_template_path(self, template_path: str) -> Path:
        path = Path(template_path).expanduser()
        if not path.is_absolute():
            path = Path(__file__).resolve().parent.parent / template_path
        if not path.exists():
            raise FileNotFoundError(f"Template HTML no encontrado: {path}")
        return path

    def _render_html_template(self, template_path: str, variables: dict[str, str]) -> str:
        template_file = self._resolve_template_path(template_path)
        content = template_file.read_text(encoding="utf-8")
        if "{{" in content and "}}" in content:
            content = re.sub(r"\{\{\s*([A-Za-z0-9_]+)\s*\}\}", r"$\1", content)
        template = Template(content)
        return template.safe_substitute(**variables)

    def _generate_otp(self, length: int = 6) -> str:
        alphabet = "0123456789"
        return "".join(secrets.choice(alphabet) for _ in range(length))

    def generate_otp(self, length: int = 6) -> str:
        """Genera un OTP numérico."""
        return self._generate_otp(length)

    async def _request_json(self, method: str, url: str, json=None, **kwargs):
        async with httpx.AsyncClient(timeout=30.0, verify=self.ssl_verify) as client:
            response = await client.request(
                method=method, url=url, headers=await self._headers(), json=json, **kwargs
            )
            response.raise_for_status()
            return response.json() if response.content else {}

    async def send_mail(
        self,
        to_recipients: list[str],
        subject: str,
        body: str,
        is_html: bool = False,
        cc_recipients: list[str] | None = None,
        bcc_recipients: list[str] | None = None,
    ) -> dict:
        to_list = [{"emailAddress": {"address": addr.strip()}} for addr in to_recipients]
        cc_list = [{"emailAddress": {"address": addr.strip()}} for addr in (cc_recipients or [])]
        bcc_list = [{"emailAddress": {"address": addr.strip()}} for addr in (bcc_recipients or [])]

        message = {
            "subject": subject,
            "body": {"contentType": "HTML" if is_html else "text", "content": body},
            "toRecipients": to_list,
        }
        if cc_list:
            message["ccRecipients"] = cc_list
        if bcc_list:
            message["bccRecipients"] = bcc_list

        payload = {"message": message, "saveToSentItems": True}
        url = f"{self.base_url}/users/{self.sender_address}/sendMail"

        try:
            await self._request_json("POST", url, json=payload)
            return {"success": True, "message": "Correo enviado", "sender": self.sender_address, "subject": subject}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"Error: {exc.response.status_code}"}

    async def send_mail_from_html_template(
        self,
        to_recipients: list[str],
        subject: str,
        template_path: str,
        variables: dict[str, str],
        cc_recipients: list[str] | None = None,
        bcc_recipients: list[str] | None = None,
    ) -> dict:
        html_body = self._render_html_template(template_path, variables)
        return await self.send_mail(
            to_recipients=to_recipients,
            subject=subject,
            body=html_body,
            is_html=True,
            cc_recipients=cc_recipients,
            bcc_recipients=bcc_recipients,
        )

    async def send_mail_with_attachment(
        self,
        to_recipients: list[str],
        subject: str,
        body: str,
        attachment_path: str | None = None,
        is_html: bool = False,
        cc_recipients: list[str] | None = None,
        bcc_recipients: list[str] | None = None,
        base64_content: str | None = None,
        file_name: str | None = None,
        template_path: str | None = None,
        template_variables: dict[str, str] | None = None,
        client_id: str | None = None,
    ) -> dict:
        if template_path:
            body = self._render_html_template(template_path, template_variables or {})
            is_html = True

        if attachment_path:
            file_path = Path(attachment_path)
            if not file_path.exists():
                return {"success": False, "error": f"Archivo no existe: {attachment_path}"}
            file_name = file_name or file_path.name
            encoded_content = base64.b64encode(file_path.read_bytes()).decode("utf-8")
            content_type = self._get_content_type(file_path)
        elif base64_content and file_name:
            encoded_content = base64_content
            content_type = self._get_content_type(Path(file_name))
        else:
            return {
                "success": False,
                "error": "Se requiere attachment_path o base64_content y file_name.",
            }

        if client_id:
            encrypted_bytes = encrypt_bytes_for_client(
                client_id,
                base64.b64decode(encoded_content),
            )
            encoded_content = encrypted_bytes.decode("utf-8")

        to_list = [{"emailAddress": {"address": addr.strip()}} for addr in to_recipients]
        message = {
            "subject": subject,
            "body": {"contentType": "HTML" if is_html else "text", "content": body},
            "toRecipients": to_list,
            "attachments": [{
                "@odata.type": "#microsoft.graph.fileAttachment",
                "name": file_name,
                "contentBytes": encoded_content,
                "contentType": content_type,
            }],
        }

        if cc_recipients:
            message["ccRecipients"] = [{"emailAddress": {"address": addr.strip()}} for addr in cc_recipients]
        if bcc_recipients:
            message["bccRecipients"] = [{"emailAddress": {"address": addr.strip()}} for addr in bcc_recipients]

        payload = {"message": message, "saveToSentItems": True}
        url = f"{self.base_url}/users/{self.sender_address}/sendMail"

        try:
            await self._request_json("POST", url, json=payload)
            return {"success": True, "message": "Correo con adjunto enviado", "attachment": file_name}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"Error: {exc.response.status_code}"}

    def _get_content_type(self, file_path: Path) -> str:
        types = {
            ".pdf": "application/pdf", ".doc": "application/msword",
            ".docx": "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
            ".xls": "application/vnd.ms-excel",
            ".xlsx": "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            ".txt": "text/plain", ".csv": "text/csv", ".jpg": "image/jpeg", ".png": "image/png",
        }
        return types.get(file_path.suffix.lower(), "application/octet-stream")

    async def send_bulk_mail(
        self, recipients: list[dict], subject: str, body_template: str, is_html: bool = False
    ) -> dict:
        successful, failed = [], []
        for recipient in recipients:
            if "email" not in recipient:
                failed.append({"recipient": recipient, "error": "Campo 'email' requerido"})
                continue
            try:
                body = body_template.format(**recipient)
                result = await self.send_mail([recipient["email"]], subject, body, is_html)
                if result["success"]:
                    successful.append(recipient["email"])
                else:
                    failed.append({"recipient": recipient["email"], "error": result.get("error")})
            except Exception as exc:
                failed.append({"recipient": recipient.get("email"), "error": str(exc)})
        return {"successful_count": len(successful), "failed_count": len(failed), "successful": successful, "failed": failed}

    async def get_mailbox_info(self) -> dict:
        url = f"{self.base_url}/users/{self.sender_address}"
        try:
            user_info = await self._request_json("GET", url)
            return {"success": True, "user_id": user_info.get("id"), "display_name": user_info.get("displayName")}
        except httpx.HTTPStatusError as exc:
            return {"success": False, "error": f"Error: {exc.response.status_code}"}
