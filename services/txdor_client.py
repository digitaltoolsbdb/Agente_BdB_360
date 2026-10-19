from __future__ import annotations

import os
from ipaddress import ip_address
from xml.etree.ElementTree import Element, SubElement, tostring

import httpx


SOAP_ENV_NS = "http://schemas.xmlsoap.org/soap/envelope/"
TXDOR_NS = "http://bancodebogota.com/txdorservice/v3"
# Valores previos fijos en codigo; se conservan como predeterminados.
DEFAULT_TXDOR_SOAP_URL = "http://10.0.0.7:8400/TransaccionadorV4/TxdorServicePort"
DEFAULT_TXDOR_OFFICE = "025"
DEFAULT_TXDOR_CLIENT_IP = "10.86.124.1"
ACCOUNT_TYPE_CODES = {
    "ST": "Cuenta de Ahorros",
    "IM": "Cuenta Corriente",
    "AM": "Creditos ALS",
}


def _required_value(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} no puede estar vacío.")
    return normalized


def _soap_url() -> str:
    value = _required_value(
        os.getenv("TXDOR_SOAP_URL", DEFAULT_TXDOR_SOAP_URL), "TXDOR_SOAP_URL"
    )
    try:
        url = httpx.URL(value)
    except httpx.InvalidURL:
        raise ValueError("TXDOR_SOAP_URL no es una URL valida.") from None
    if url.scheme not in ("http", "https") or not url.host or url.userinfo:
        raise ValueError("TXDOR_SOAP_URL debe ser una URL http(s) sin credenciales.")
    return value


def _office() -> str:
    return _required_value(
        os.getenv("TXDOR_OFFICE", DEFAULT_TXDOR_OFFICE), "TXDOR_OFFICE"
    )


def _client_ip() -> str:
    value = _required_value(
        os.getenv("TXDOR_CLIENT_IP", DEFAULT_TXDOR_CLIENT_IP), "TXDOR_CLIENT_IP"
    )
    try:
        ip_address(value)
    except ValueError:
        raise ValueError("TXDOR_CLIENT_IP debe ser una direccion IP valida.") from None
    return value


def _build_request(
    tipo_cuenta: str,
    numero_cuenta: str,
) -> bytes:
    envelope = Element(f"{{{SOAP_ENV_NS}}}Envelope")
    SubElement(envelope, f"{{{SOAP_ENV_NS}}}Header")
    body = SubElement(envelope, f"{{{SOAP_ENV_NS}}}Body")
    tranzar = SubElement(body, f"{{{TXDOR_NS}}}tranzar")
    arg0 = SubElement(tranzar, "arg0")
    connection = SubElement(arg0, "peConnectionIn")

    for name, value in (
        ("service", "TSPPEREC"),
        ("msgName", "OFBS"),
        ("message", ""),
        ("sendUser", "false"),
        ("numericUser", "false"),
        ("reversion", "false"),
        ("reversionNum", ""),
        ("user", _required_value(os.getenv("TXDOR_USER", ""), "TXDOR_USER")),
        (
            "identification",
            _required_value(
                os.getenv("TXDOR_IDENTIFICATION", ""),
                "TXDOR_IDENTIFICATION",
            ),
        ),
        ("IP", _client_ip()),
    ):
        SubElement(connection, name).text = value

    additional_params = SubElement(connection, "additionalparams")
    entry = SubElement(additional_params, "Entry")
    entry.set("key", "")
    entry.set("value", "")

    fields_list = SubElement(arg0, "fieldsList")
    for key, value in (
        ("PEPAGCONSALFA", tipo_cuenta),
        ("PENUMCTA", numero_cuenta),
        ("PEOFIREC", _office()),
    ):
        entry = SubElement(fields_list, "EntryTxdor")
        entry.set("key", key)
        entry.set("value", value)

    return tostring(envelope, encoding="utf-8", xml_declaration=True)


async def tranzar(
    tipo_cuenta: str,
    numero_cuenta: str,
) -> dict[str, str | int]:
    account_code = _required_value(tipo_cuenta, "tipo_cuenta").upper()
    if account_code not in ACCOUNT_TYPE_CODES:
        valid_codes = ", ".join(ACCOUNT_TYPE_CODES)
        raise ValueError(
            f"tipo_cuenta debe ser uno de los códigos: {valid_codes}."
        )

    values = {
        "tipo_cuenta": account_code,
        "numero_cuenta": _required_value(numero_cuenta, "numero_cuenta"),
    }
    timeout = float(os.getenv("TXDOR_TIMEOUT_SECONDS", "30"))
    soap_url = _soap_url()
    request_body = _build_request(**values)

    async with httpx.AsyncClient(timeout=timeout, verify=True) as client:
        response = await client.post(
            soap_url,
            content=request_body,
            headers={
                "Content-Type": "text/xml; charset=UTF-8",
                "SOAPAction": '""',
            },
        )
        response.raise_for_status()

    return {
        "status_code": response.status_code,
        "response": response.text,
    }
