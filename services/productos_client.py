import math
import os
from urllib.parse import urlsplit
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx
from lxml import etree
from mcp.server.fastmcp.exceptions import ToolError


SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
PRODUCTOS_NS = (
    "http://xmlns.oracle.com/Enterprise/Tools/schemas/BB_PECONSUPRODPSREQ.V1"
)


def _configuration() -> tuple[httpx.URL, float]:
    configured_url = os.getenv("CONSULTA_PRODUCTOS_SOAP_URL", "").strip()
    try:
        urlsplit(configured_url)
        url = httpx.URL(configured_url)
    except (httpx.InvalidURL, ValueError):
        raise ToolError("CONSULTA_PRODUCTOS_SOAP_URL no es una URL valida.") from None
    if (
        url.scheme != "http"
        or not url.host
        or url.userinfo
        or url.fragment
        or '"' in configured_url
        or "%22" in configured_url.lower()
    ):
        raise ToolError(
            "Configure CONSULTA_PRODUCTOS_SOAP_URL con la URL HTTPS aprobada, "
            "sin credenciales, fragmentos ni comillas."
        )

    try:
        timeout = float(os.getenv("CONSULTA_PRODUCTOS_TIMEOUT_SECONDS", "30"))
    except ValueError:
        raise ToolError(
            "CONSULTA_PRODUCTOS_TIMEOUT_SECONDS debe ser un numero positivo finito."
        ) from None
    if not math.isfinite(timeout) or timeout <= 0:
        raise ToolError(
            "CONSULTA_PRODUCTOS_TIMEOUT_SECONDS debe ser un numero positivo finito."
        )
    return url, timeout


def _build_request(aa_nit: str) -> bytes:
    envelope = Element(f"{{{SOAP_ENV_NS}}}Envelope")
    SubElement(envelope, f"{{{SOAP_ENV_NS}}}Header")
    body = SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    request = SubElement(body, f"{{{PRODUCTOS_NS}}}BB_PECONSUPRODPSREQ")
    data = SubElement(request, f"{{{PRODUCTOS_NS}}}MsgData")
    transaction = SubElement(data, f"{{{PRODUCTOS_NS}}}Transaction")
    record = SubElement(
        transaction, f"{{{PRODUCTOS_NS}}}BB_PECLIPRGET_I", {"class": "R"}
    )
    for name, value in (
        ("AA_TIPO_DOC", "C"),
        ("AA_NIT", aa_nit),
        ("PRODUCT_GROUP", " "),
        ("FIN_ACCOUNT_ID", ""),
    ):
        SubElement(record, f"{{{PRODUCTOS_NS}}}{name}", {"type": "CHAR"}).text = value
    SubElement(record, f"{{{PRODUCTOS_NS}}}CANAL")
    return tostring(envelope, encoding="utf-8", xml_declaration=True)


def _validate_response(content: bytes) -> None:
    parser = etree.XMLParser(
        resolve_entities=False,
        no_network=True,
        load_dtd=False,
        recover=False,
    )
    try:
        root = etree.fromstring(content, parser=parser)
    except etree.XMLSyntaxError:
        raise ToolError("consultaProductos recibio una respuesta XML invalida.") from None
    if root.getroottree().docinfo.doctype:
        raise ToolError("consultaProductos rechazo una respuesta XML con DTD.")
    bodies = root.findall(f"{{{SOAP_ENV_NS}}}Body")
    if root.tag != f"{{{SOAP_ENV_NS}}}Envelope" or len(bodies) != 1 or not len(bodies[0]):
        raise ToolError("consultaProductos recibio una respuesta SOAP 1.1 invalida.")
    if bodies[0].find(f"{{{SOAP_ENV_NS}}}Fault") is not None:
        # El detalle del Fault puede incluir identificaciones o datos del cliente.
        raise ToolError("El servicio de consultaProductos reporto un SOAP Fault.")


async def consultar_productos(aa_nit: str) -> dict[str, str | int]:
    """Consulta SOAP sin autenticacion; la URL solo se obtiene del entorno."""
    if (
        not isinstance(aa_nit, str)
        or not aa_nit
        or not aa_nit.isascii()
        or not aa_nit.isdecimal()
    ):
        raise ToolError("aa_nit debe ser un texto no vacio con solo digitos ASCII.")
    url, timeout = _configuration()
    try:
        async with httpx.AsyncClient(
            timeout=timeout,
            verify=True,
            follow_redirects=False,
        ) as client:
            response = await client.post(
                url,
                content=_build_request(aa_nit),
                headers={"Content-Type": "text/xml; charset=utf-8"},
            )
    except httpx.TimeoutException:
        raise ToolError("Se agoto el tiempo de consultaProductos.") from None
    except httpx.HTTPError:
        raise ToolError("No fue posible conectar con el servicio de consultaProductos.") from None
    except (OSError, ValueError):
        raise ToolError("No fue posible inicializar la conexion HTTPS de consultaProductos.") from None

    if not 200 <= response.status_code < 300:
        raise ToolError(
            f"El servicio de consultaProductos respondio HTTP {response.status_code}."
        )
    _validate_response(response.content)
    return {"status_code": response.status_code, "response": response.text}
