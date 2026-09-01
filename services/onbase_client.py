"""Cliente SOAP para consultar documentos en OnBase - VERSION BULLETPROOF.

Esta version NO usa XPath con funciones (local-name(), etc).
En su lugar itera con element.iter() y compara nombres locales
manualmente. Esto elimina cualquier posibilidad de error
"invalid predicate" en lxml.
"""
import base64
import io
import logging
import os
import re
import uuid
import httpx
from datetime import datetime, timezone
from typing import Dict, List, Optional

from lxml import etree
from pdfminer.high_level import extract_text
from pydantic import BaseModel, Field


_LOGGER = logging.getLogger(__name__)
if not _LOGGER.handlers:
    handler = logging.StreamHandler()
    handler.setFormatter(
        logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s")
    )
    _LOGGER.addHandler(handler)
    _LOGGER.setLevel(logging.INFO)


# ============================================================
# CONFIGURACION OnBase SOAP
# ============================================================

ONBASE_URL = os.getenv(
    "ONBASE_SOAP_URL",
    "http://10.70.20.133:3088/customers/DocumentationItemInquiry",
)
ONBASE_CUSTOMER_INFO_URL = os.getenv(
    "ONBASE_CUSTOMER_INFO_URL",
    "http://10.70.20.133:3088/customers/CustomerInformationInquiry",
)
ONBASE_CUST_LOGIN_ID = os.getenv("ONBASE_CUST_LOGIN_ID", "MRIVE19")
ONBASE_NETWORK_OWNER = os.getenv("ONBASE_NETWORK_OWNER", "MOF001")
ONBASE_BANK_ID = os.getenv("ONBASE_BANK_ID", "001")
ONBASE_TIMEOUT = int(os.getenv("ONBASE_TIMEOUT_SECONDS", "90"))
ONBASE_TERMINAL_ID = os.getenv("ONBASE_TERMINAL_ID", "1983")
ONBASE_TERMINAL_TYPE = os.getenv("ONBASE_TERMINAL_TYPE", "")
ONBASE_DELIVERY_METHOD = os.getenv("ONBASE_DELIVERY_METHOD", "B64") or "B64"
ONBASE_TRN_SEQ = os.getenv("ONBASE_TRN_SEQ", "1") or "1"

_LOGGER.info(
    "OnBase SOAP config: url=%s customer_info_url=%s network_owner=%s bank_id=%s cust_login_id=%s delivery=%s",
    ONBASE_URL,
    ONBASE_CUSTOMER_INFO_URL,
    ONBASE_NETWORK_OWNER,
    ONBASE_BANK_ID,
    ONBASE_CUST_LOGIN_ID,
    ONBASE_DELIVERY_METHOD,
)


# ============================================================
# CATALOGO DE TIPOS DOCUMENTALES
# ============================================================

class KeywordDef(BaseModel):
    key_id: int
    name: str
    operator: str = "="


class DocTypeDef(BaseModel):
    name: str
    doc_type_id: Optional[int] = None
    keywords: Dict[str, KeywordDef]


DOC_TYPES: Dict[str, DocTypeDef] = {
    "CB_EXTRACTOS_XML": DocTypeDef(
        name="CB - Extractos Version XML",
        doc_type_id=322,
        keywords={
            "cedula": KeywordDef(key_id=103, name="No. Identificacion", operator="="),
            "fecha": KeywordDef(key_id=193, name="Fecha", operator=">="),
        },
    ),

    "EC_DECLARACION_RENTA": DocTypeDef(
        name="EC - Declaración de Renta",
        doc_type_id=322,
        keywords={
            "cedula": KeywordDef(key_id=103, name="No. Identificacion", operator="="),
            "fecha": KeywordDef(key_id=193, name="Fecha", operator=">="),
        },
    ),
}


# ============================================================
# MODELOS DE RESPUESTA
# ============================================================

class DocumentItem(BaseModel):
    doc_handle: str
    doc_name: str
    doc_type_id: int
    doc_type_name: str
    update_date: str


class OnBaseResponse(BaseModel):
    success: bool
    status_code: str
    status_desc: str
    server_status_desc: Optional[str] = None
    total_found: int = 0
    documents: List[DocumentItem] = Field(default_factory=list)


class DocumentFileInfo(BaseModel):
    file_path: Optional[str] = None
    file_type: Optional[str] = None
    bin_data: Optional[str] = None


class DocumentDownloadItem(BaseModel):
    doc_handle: str
    doc_name: Optional[str] = None
    doc_type_id: Optional[int] = None
    doc_type_name: Optional[str] = None
    file_info: DocumentFileInfo = Field(default_factory=DocumentFileInfo)


class OnBaseDocumentResponse(BaseModel):
    success: bool
    status_code: str
    status_desc: str
    server_status_desc: Optional[str] = None
    documents: List[DocumentDownloadItem] = Field(default_factory=list)


class OnBaseMarkdownResponse(BaseModel):
    success: bool
    status_code: str
    status_desc: str
    server_status_desc: Optional[str] = None
    doc_handle: Optional[str] = None
    doc_name: Optional[str] = None
    markdown: Optional[str] = None


class PhoneNumber(BaseModel):
    phone_id: Optional[str] = None
    phone_type: Optional[str] = None
    phone: Optional[str] = None
    phone_ext: Optional[str] = None
    phone_area: Optional[str] = None


class EmailInfo(BaseModel):
    email_id: Optional[str] = None
    email_type: Optional[str] = None
    email_addr: Optional[str] = None
    delivery_destination: Optional[str] = None


class PostalAddress(BaseModel):
    addr1: Optional[str] = None
    addr2: Optional[str] = None
    addr3: Optional[str] = None
    addr4: Optional[str] = None
    city: Optional[str] = None
    state_prov: Optional[str] = None
    postal_code: Optional[str] = None
    country: Optional[str] = None
    addr_type: Optional[str] = None


class SafeContactInfo(BaseModel):
    safe_phone: Optional[str] = None
    safe_email_addr: Optional[str] = None


class CustomerBasicInfo(BaseModel):
    participant_id: Optional[str] = None
    type_id: Optional[str] = None
    first_name: Optional[str] = None
    middle_name: Optional[str] = None
    full_name: Optional[str] = None
    gender: Optional[str] = None
    marital_status: Optional[str] = None
    nationality: Optional[str] = None
    city: Optional[str] = None
    state_prov: Optional[str] = None
    country: Optional[str] = None
    birth_dt: Optional[str] = None
    phones: List[PhoneNumber] = Field(default_factory=list)
    emails: List[EmailInfo] = Field(default_factory=list)
    delivery_destinations: List[str] = Field(default_factory=list)
    postal_addresses: List[PostalAddress] = Field(default_factory=list)
    safe_info: SafeContactInfo = Field(default_factory=SafeContactInfo)


class CustomerContactInfoResponse(BaseModel):
    success: bool
    status_code: str
    status_desc: str
    server_status_desc: Optional[str] = None
    cust_login_id: Optional[str] = None
    basic_info: CustomerBasicInfo = Field(default_factory=CustomerBasicInfo)


# ============================================================
# TEMPLATES SOAP
# ============================================================

_SOAP_ENVELOPE = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ns2="urn://bancodebogota.com/resources/classification/v1/"
    xmlns:ns3="urn://bancodebogota.com/ifx/base/v1/"
    xmlns:ns4="urn://bancodebogota.com/resources/classification/event/"
    xmlns:ns5="urn://bancodebogota.com/resources/classification/service/">
    <soapenv:Header/>
    <soapenv:Body>
        <ns5:getDocumentsByTypeRequest>
            <ns4:DocumentsByTypeInqRq>
                <ns3:RqUID>{rq_uid}</ns3:RqUID>
                <ns3:CustId>
                    <ns3:CustLoginId>{cust_login_id}</ns3:CustLoginId>
                </ns3:CustId>
                <ns3:NetworkTrnInfo>
                    <ns3:NetworkOwner>{network_owner}</ns3:NetworkOwner>
                    <ns3:BankId>{bank_id}</ns3:BankId>
                </ns3:NetworkTrnInfo>
                <ns3:ClientDt>{client_dt}</ns3:ClientDt>
                <ns2:DocQuery>
                    <ns2:DocTypeRef>
                        <ns2:DocTypeName>{doc_type_name}</ns2:DocTypeName>
                    </ns2:DocTypeRef>
{keyword_blocks}
                    <ns2:GetKeywordsInd>0</ns2:GetKeywordsInd>
                </ns2:DocQuery>
            </ns4:DocumentsByTypeInqRq>
        </ns5:getDocumentsByTypeRequest>
    </soapenv:Body>
</soapenv:Envelope>"""

_KEYWORD_BLOCK = """                    <ns2:DocKeywords>
                        <ns2:KeyId>{key_id}</ns2:KeyId>
                        <ns3:Operator>{operator}</ns3:Operator>
                        <ns2:KeyValue>{key_value}</ns2:KeyValue>
                        <ns2:Condition>AND</ns2:Condition>
                    </ns2:DocKeywords>"""

_DOCUMENT_SOAP_ENVELOPE = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ser="urn://bancodebogota.com/resources/classification/service/"
    xmlns:even="urn://bancodebogota.com/resources/classification/event/"
    xmlns:v1="urn://bancodebogota.com/ifx/base/v1/"
    xmlns:v11="urn://bancodebogota.com/resources/classification/v1/">
    <soapenv:Header/>
    <soapenv:Body>
        <ser:getDocumentsRequest>
            <even:DocumentsInqRq>
                <v1:RqUID>{rq_uid}</v1:RqUID>
                <v1:CustId>
                    <v1:CustLoginId>{cust_login_id}</v1:CustLoginId>
                </v1:CustId>
                <v1:NetworkTrnInfo>
                    <v1:NetworkOwner>{network_owner}</v1:NetworkOwner>
                    <v1:TerminalId>{terminal_id}</v1:TerminalId>
                    <v1:TerminalType>{terminal_type}</v1:TerminalType>
                    <v1:BankId>{bank_id}</v1:BankId>
                </v1:NetworkTrnInfo>
                <v1:ClientDt>{client_dt}</v1:ClientDt>
                <v11:DocList>
                    <v11:DocHandle>{doc_handle}</v11:DocHandle>
                </v11:DocList>
                <v1:DeliveryMethod>{delivery_method}</v1:DeliveryMethod>
                <v1:TrnSeq>{trn_seq}</v1:TrnSeq>
            </even:DocumentsInqRq>
        </ser:getDocumentsRequest>
    </soapenv:Body>
</soapenv:Envelope>"""

_CUSTOMER_BASIC_INFO_SOAP_ENVELOPE = """<soapenv:Envelope xmlns:soapenv="http://schemas.xmlsoap.org/soap/envelope/"
    xmlns:ser="urn://bancodebogota.com/customers/involvedparty/service/"
    xmlns:even="urn://bancodebogota.com/customers/involvedparty/event/"
    xmlns:v1="urn://bancodebogota.com/ifx/base/v1/"
    xmlns:v11="urn://bancodebogota.com/customers/involvedparty/v1/">
    <soapenv:Header/>
    <soapenv:Body>
        <ser:getCustBasicInfoRequest>
            <even:CustBasicInfoInqRq>
                <v1:RqUID>{rq_uid}</v1:RqUID>
                <v1:CustId>
                    <v1:CustLoginId>{cust_login_id}</v1:CustLoginId>
                </v1:CustId>
                <v1:NetworkTrnInfo>
                    <v1:NetworkOwner>{network_owner}</v1:NetworkOwner>
                    <v1:TerminalId>{terminal_id}</v1:TerminalId>
                    <v1:BankId>{bank_id}</v1:BankId>
                </v1:NetworkTrnInfo>
                <v1:ClientDt>{client_dt}</v1:ClientDt>
{other_ident_doc}
                <v11:FilterInfo>
                    <v1:GetBasicInfo>0</v1:GetBasicInfo>
                    <v1:GetGeneralInfo>0</v1:GetGeneralInfo>
                    <v1:GetFinantialInfo>0</v1:GetFinantialInfo>
                    <v1:GetLocationInfo>0</v1:GetLocationInfo>
                    <v1:GetSecureInfo>1</v1:GetSecureInfo>
                </v11:FilterInfo>
            </even:CustBasicInfoInqRq>
        </ser:getCustBasicInfoRequest>
    </soapenv:Body>
</soapenv:Envelope>"""


def _build_customer_basic_info_envelope(
    cust_login_id: str,
    network_owner: str,
    terminal_id: str,
    bank_id: str,
    client_dt: str,
    participant_id: Optional[str] = None,
    type_id: str = "C",
    rq_uid: Optional[str] = None,
) -> str:
    other_ident_doc = ""
    if participant_id:
        other_ident_doc = f"""
                <v1:OtherIdentDoc>
                    <v1:TypeId>{type_id}</v1:TypeId>
                    <v1:ParticipantId>{participant_id}</v1:ParticipantId>
                </v1:OtherIdentDoc>"""
    return _CUSTOMER_BASIC_INFO_SOAP_ENVELOPE.format(
        rq_uid=rq_uid or str(uuid.uuid4()),
        cust_login_id=cust_login_id,
        network_owner=network_owner,
        terminal_id=terminal_id,
        bank_id=bank_id,
        client_dt=client_dt,
        other_ident_doc=other_ident_doc,
    )


# ============================================================
# HELPERS XML (SIN XPATH, SOLO ITERACION)
# ============================================================

def _local_name(tag: str) -> str:
    """Extrae el nombre local de una etiqueta con namespace.
    Ejemplo: '{urn://...}DocHandle' -> 'DocHandle'
    """
    if tag is None:
        return ""
    if "}" in tag:
        return tag.split("}", 1)[1]
    return tag


def _find_first(root: etree._Element, local_name: str) -> Optional[etree._Element]:
    """Devuelve el primer descendiente cuyo nombre local coincida."""
    if root is None:
        return None
    for elem in root.iter():
        if _local_name(elem.tag) == local_name:
            return elem
    return None


def _find_all(root: etree._Element, local_name: str) -> List[etree._Element]:
    """Devuelve todos los descendientes cuyo nombre local coincida."""
    if root is None:
        return []
    result = []
    for elem in root.iter():
        if _local_name(elem.tag) == local_name:
            result.append(elem)
    return result


def _find_element_text(parent: etree._Element, local_name: str) -> Optional[str]:
    """Busca el texto del primer elemento con ese nombre local."""
    elem = _find_first(parent, local_name)
    if elem is not None and elem.text is not None:
        return elem.text.strip()
    return None


def _find_document_nodes(root: etree._Element) -> List[etree._Element]:
    """Devuelve los nodos que contienen informacion de documento."""
    candidates = ["DocList", "DocListInfo", "Document", "DocumentInfo", "Doc"]
    nodes: List[etree._Element] = []
    for name in candidates:
        for node in _find_all(root, name):
            if node not in nodes:
                nodes.append(node)
    return nodes


# ============================================================
# HELPERS DE FORMATO
# ============================================================

def _format_date_onbase(fecha: str) -> str:
    """Convierte fecha al formato esperado por OnBase: AAAAMMDD HH:MM:SS."""
    for fmt in ("%Y-%m-%d", "%Y-%m-%dT%H:%M:%S", "%d/%m/%Y"):
        try:
            return datetime.strptime(fecha, fmt).strftime("%Y%m%d %H:%M:%S")
        except ValueError:
            continue
    raise ValueError(
        f"Formato de fecha invalido: '{fecha}'. "
        "Use 'YYYY-MM-DD', 'YYYY-MM-DDTHH:MM:SS' o 'DD/MM/YYYY'."
    )


def _build_envelope(
    doc_type: DocTypeDef,
    cedula: str,
    fecha: str,
    cust_login_id: Optional[str] = None,
    rq_uid: Optional[str] = None,
) -> str:
    """Construye el SOAP Envelope completo para getDocumentsByType."""
    kw_cedula = doc_type.keywords["cedula"]
    kw_fecha = doc_type.keywords["fecha"]

    keyword_blocks = "\n".join([
        _KEYWORD_BLOCK.format(
            key_id=kw_cedula.key_id,
            operator=kw_cedula.operator,
            key_value=cedula,
        ),
        _KEYWORD_BLOCK.format(
            key_id=kw_fecha.key_id,
            operator=kw_fecha.operator,
            key_value=_format_date_onbase(fecha),
        ),
    ])

    return _SOAP_ENVELOPE.format(
        rq_uid=rq_uid or str(uuid.uuid4()),
        cust_login_id=cust_login_id or ONBASE_CUST_LOGIN_ID,
        network_owner=ONBASE_NETWORK_OWNER,
        bank_id=ONBASE_BANK_ID,
        client_dt=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        doc_type_name=doc_type.name,
        keyword_blocks=keyword_blocks,
    )


# ============================================================
# PARSEO DE RESPUESTAS
# ============================================================

def _parse_response(xml_text: str) -> OnBaseResponse:
    """Parsea la respuesta SOAP de getDocumentsByType."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except Exception as exc:
        _LOGGER.exception("Error parseando XML de respuesta")
        return OnBaseResponse(
            success=False,
            status_code="-1",
            status_desc=f"XML invalido: {exc}",
        )

    status_code = _find_element_text(root, "StatusCode") or ""
    status_desc = _find_element_text(root, "StatusDesc") or ""
    server_status_desc = _find_element_text(root, "ServerStatusDesc")

    success = status_code == "0"

    documents: List[DocumentItem] = []
    for node in _find_document_nodes(root):
        doc_handle = _find_element_text(node, "DocHandle")
        if not doc_handle:
            continue
        try:
            doc_type_id_txt = _find_element_text(node, "DocTypeId")
            doc_type_id = int(doc_type_id_txt) if doc_type_id_txt else 0
        except ValueError:
            doc_type_id = 0

        documents.append(
            DocumentItem(
                doc_handle=doc_handle,
                doc_name=_find_element_text(node, "DocName") or "",
                doc_type_id=doc_type_id,
                doc_type_name=_find_element_text(node, "DocTypeName") or "",
                update_date=_find_element_text(node, "DocDate")
                or _find_element_text(node, "UpdateDate")
                or "",
            )
        )

    return OnBaseResponse(
        success=success,
        status_code=status_code,
        status_desc=status_desc,
        server_status_desc=server_status_desc,
        total_found=len(documents),
        documents=documents,
    )


def _parse_document_response(xml_text: str) -> OnBaseDocumentResponse:
    """Parsea la respuesta SOAP de getDocuments (descarga por handle)."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except Exception as exc:
        _LOGGER.exception("Error parseando XML de respuesta de descarga")
        return OnBaseDocumentResponse(
            success=False,
            status_code="-1",
            status_desc=f"XML invalido: {exc}",
        )

    status_code = _find_element_text(root, "StatusCode") or ""
    status_desc = _find_element_text(root, "StatusDesc") or ""
    server_status_desc = _find_element_text(root, "ServerStatusDesc")

    success = status_code == "0"

    documents: List[DocumentDownloadItem] = []
    for node in _find_document_nodes(root):
        doc_handle = _find_element_text(node, "DocHandle")
        if not doc_handle:
            continue

        file_info = DocumentFileInfo(
            file_path=_find_element_text(node, "FilePath"),
            file_type=_find_element_text(node, "FileType"),
            bin_data=_find_element_text(node, "BinData"),
        )

        try:
            doc_type_id_txt = _find_element_text(node, "DocTypeId")
            doc_type_id = int(doc_type_id_txt) if doc_type_id_txt else None
        except ValueError:
            doc_type_id = None

        documents.append(
            DocumentDownloadItem(
                doc_handle=doc_handle,
                doc_name=_find_element_text(node, "DocName"),
                doc_type_id=doc_type_id,
                doc_type_name=_find_element_text(node, "DocTypeName"),
                file_info=file_info,
            )
        )

    return OnBaseDocumentResponse(
        success=success,
        status_code=status_code,
        status_desc=status_desc,
        server_status_desc=server_status_desc,
        documents=documents,
    )


# ============================================================
# CONVERSION PDF -> MARKDOWN
# ============================================================

def _build_markdown_from_pdf_bytes(pdf_bytes: bytes) -> str:
    """Extrae texto de PDF en bytes y devuelve un documento Markdown simple."""
    text = extract_text(io.BytesIO(pdf_bytes))
    if not text:
        return ""
    text = re.sub(r"\r\n?", "\n", text)
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _is_pdf_file(doc_name: Optional[str], file_type: Optional[str]) -> bool:
    if file_type and "pdf" in file_type.lower():
        return True
    if doc_name and doc_name.lower().endswith(".pdf"):
        return True
    return False


def _is_pdf_bytes(pdf_bytes: bytes) -> bool:
    return pdf_bytes.startswith(b"%PDF")


def _parse_document_markdown_response(xml_text: str) -> OnBaseMarkdownResponse:
    """Parsea la respuesta de documento y convierte el PDF a Markdown."""
    document_response = _parse_document_response(xml_text)

    if not document_response.documents:
        return OnBaseMarkdownResponse(
            success=document_response.success,
            status_code=document_response.status_code,
            status_desc=document_response.status_desc,
            server_status_desc=document_response.server_status_desc,
        )

    doc = document_response.documents[0]
    file_info = doc.file_info

    if not file_info.bin_data:
        _LOGGER.warning(
            "BinData vacio para DocHandle=%s. FilePath=%s",
            doc.doc_handle,
            file_info.file_path,
        )
        return OnBaseMarkdownResponse(
            success=False,
            status_code=document_response.status_code,
            status_desc=document_response.status_desc,
            server_status_desc="El servicio no entrego BinData (Base64). "
            "Verifique DeliveryMethod=B64.",
            doc_handle=doc.doc_handle,
            doc_name=doc.doc_name,
        )

    try:
        pdf_bytes = base64.b64decode(file_info.bin_data)
    except Exception as exc:
        _LOGGER.exception("Error decodificando Base64 del documento")
        return OnBaseMarkdownResponse(
            success=False,
            status_code=document_response.status_code,
            status_desc=document_response.status_desc,
            server_status_desc=f"Base64 invalido: {exc}",
            doc_handle=doc.doc_handle,
            doc_name=doc.doc_name,
        )

    if not (_is_pdf_file(doc.doc_name, file_info.file_type) or _is_pdf_bytes(pdf_bytes)):
        return OnBaseMarkdownResponse(
            success=False,
            status_code=document_response.status_code,
            status_desc=document_response.status_desc,
            server_status_desc="El documento no es un PDF; conversion a Markdown omitida.",
            doc_handle=doc.doc_handle,
            doc_name=doc.doc_name,
        )

    try:
        markdown = _build_markdown_from_pdf_bytes(pdf_bytes)
    except Exception as exc:
        _LOGGER.exception("Error extrayendo texto del PDF")
        return OnBaseMarkdownResponse(
            success=False,
            status_code=document_response.status_code,
            status_desc=document_response.status_desc,
            server_status_desc=f"Fallo extrayendo texto del PDF: {exc}",
            doc_handle=doc.doc_handle,
            doc_name=doc.doc_name,
        )

    return OnBaseMarkdownResponse(
        success=document_response.success,
        status_code=document_response.status_code,
        status_desc=document_response.status_desc,
        server_status_desc=document_response.server_status_desc,
        doc_handle=doc.doc_handle,
        doc_name=doc.doc_name,
        markdown=markdown,
    )


def _parse_phone_number(node: etree._Element) -> PhoneNumber:
    return PhoneNumber(
        phone_id=_find_element_text(node, "PhoneId"),
        phone_type=_find_element_text(node, "PhoneType"),
        phone=_find_element_text(node, "Phone"),
        phone_ext=_find_element_text(node, "PhoneExt"),
        phone_area=_find_element_text(node, "PhoneArea"),
    )


def _parse_email_info(node: etree._Element) -> EmailInfo:
    return EmailInfo(
        email_id=_find_element_text(node, "EmailId"),
        email_type=_find_element_text(node, "EmailType"),
        email_addr=_find_element_text(node, "EmailAddr"),
        delivery_destination=_find_element_text(node, "DeliveryDestination"),
    )


def _parse_postal_address(node: etree._Element) -> PostalAddress:
    return PostalAddress(
        addr1=_find_element_text(node, "Addr1"),
        addr2=_find_element_text(node, "Addr2"),
        addr3=_find_element_text(node, "Addr3"),
        addr4=_find_element_text(node, "Addr4"),
        city=_find_element_text(node, "City"),
        state_prov=_find_element_text(node, "StateProv"),
        postal_code=_find_element_text(node, "PostalCode"),
        country=_find_element_text(node, "Country"),
        addr_type=_find_element_text(node, "AddrType"),
    )


def _parse_safe_contact_info(node: etree._Element) -> SafeContactInfo:
    return SafeContactInfo(
        safe_phone=_find_element_text(node, "SafePhone"),
        safe_email_addr=_find_element_text(node, "SafeEmailAddr"),
    )


def _parse_customer_info_response(xml_text: str) -> CustomerContactInfoResponse:
    """Parsea la respuesta SOAP de getCustBasicInfoResponse."""
    try:
        root = etree.fromstring(xml_text.encode("utf-8"))
    except Exception as exc:
        _LOGGER.exception("Error parseando XML de customer info")
        return CustomerContactInfoResponse(
            success=False,
            status_code="-1",
            status_desc=f"XML invalido: {exc}",
        )

    status_code = _find_element_text(root, "StatusCode") or ""
    status_desc = _find_element_text(root, "StatusDesc") or ""
    server_status_desc = _find_element_text(root, "ServerStatusDesc")
    cust_login_id = _find_element_text(root, "CustLoginId")
    success = status_code == "0"

    basic_info = CustomerBasicInfo(
        participant_id=_find_element_text(root, "ParticipantId"),
        type_id=_find_element_text(root, "TypeId"),
        first_name=_find_element_text(root, "FirstName"),
        middle_name=_find_element_text(root, "MiddleName"),
        full_name=_find_element_text(root, "FullName"),
        gender=_find_element_text(root, "Gender"),
        marital_status=_find_element_text(root, "MaritalStatus"),
        nationality=_find_element_text(root, "Nationality"),
        city=_find_element_text(root, "City"),
        state_prov=_find_element_text(root, "StateProv"),
        country=_find_element_text(root, "Country"),
        birth_dt=_find_element_text(root, "BirthDt"),
    )

    cust_basic_info_node = _find_first(root, "CustBasicInfo")
    if cust_basic_info_node is not None:
        for phone_node in _find_all(cust_basic_info_node, "PhoneNum"):
            basic_info.phones.append(_parse_phone_number(phone_node))

        for email_node in _find_all(cust_basic_info_node, "ContactInfo"):
            email_info = _parse_email_info(email_node)
            if any((email_info.email_id, email_info.email_type, email_info.email_addr, email_info.delivery_destination)):
                basic_info.emails.append(email_info)
            delivery_destination = _find_element_text(email_node, "DeliveryDestination")
            if delivery_destination:
                basic_info.delivery_destinations.append(delivery_destination)

        for address_node in _find_all(cust_basic_info_node, "PostAddr"):
            basic_info.postal_addresses.append(_parse_postal_address(address_node))

        safe_info_node = _find_first(cust_basic_info_node, "SafeInfo")
        if safe_info_node is not None:
            basic_info.safe_info = _parse_safe_contact_info(safe_info_node)

    return CustomerContactInfoResponse(
        success=success,
        status_code=status_code,
        status_desc=status_desc,
        server_status_desc=server_status_desc,
        cust_login_id=cust_login_id,
        basic_info=basic_info,
    )


# ============================================================
# CLIENTE PUBLICO
# ============================================================

async def _post_soap(envelope: str, url: str | None = None) -> str:
    """Envia el envelope SOAP y devuelve el XML de respuesta como texto."""
    target_url = url or ONBASE_URL
    headers = {"Content-Type": "text/xml; charset=UTF-8"}
    async with httpx.AsyncClient(timeout=ONBASE_TIMEOUT) as client:
        _LOGGER.info("POST -> %s", target_url)
        response = await client.post(target_url, content=envelope, headers=headers)
        response.raise_for_status()
        return response.text


async def get_documents_by_type(
    cedula: str,
    fecha: str,
    doc_type_key: str,
    # doc_type_key: str = "CB_EXTRACTOS_XML",
    cust_login_id: Optional[str] = None,
    rq_uid: Optional[str] = None,
) -> OnBaseResponse:
    """Consulta documentos en OnBase por cedula + fecha + tipo documental."""
    doc_type = DOC_TYPES.get(doc_type_key)
    if not doc_type:
        raise ValueError(
            f"Tipo documental '{doc_type_key}' no soportado. "
            f"Disponibles: {list(DOC_TYPES.keys())}"
        )

    envelope = _build_envelope(
        doc_type,
        cedula,
        fecha,
        cust_login_id=cust_login_id,
        rq_uid=rq_uid,
    )
    xml_text = await _post_soap(envelope)
    return _parse_response(xml_text)


async def get_document_by_handle(
    doc_handle: str,
    cust_login_id: Optional[str] = None,
    rq_uid: Optional[str] = None,
) -> OnBaseDocumentResponse:
    """Descarga un documento en OnBase usando su identificador (DocHandle)."""
    envelope = _DOCUMENT_SOAP_ENVELOPE.format(
        rq_uid=str(uuid.uuid4()),
        cust_login_id=ONBASE_CUST_LOGIN_ID,
        network_owner=ONBASE_NETWORK_OWNER,
        terminal_id=ONBASE_TERMINAL_ID,
        terminal_type=ONBASE_TERMINAL_TYPE,
        bank_id=ONBASE_BANK_ID,
        client_dt=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        doc_handle=doc_handle,
        delivery_method=ONBASE_DELIVERY_METHOD,
        trn_seq=ONBASE_TRN_SEQ,
    )
    xml_text = await _post_soap(envelope)
    return _parse_document_response(xml_text)


async def get_document_markdown_by_handle(
    doc_handle: str,
    cust_login_id: Optional[str] = None,
    rq_uid: Optional[str] = None,
) -> OnBaseMarkdownResponse:
    """Descarga un documento en OnBase y devuelve su contenido PDF en Markdown."""
    envelope = _DOCUMENT_SOAP_ENVELOPE.format(
        rq_uid=str(uuid.uuid4()),
        cust_login_id=ONBASE_CUST_LOGIN_ID,
        network_owner=ONBASE_NETWORK_OWNER,
        terminal_id=ONBASE_TERMINAL_ID,
        terminal_type=ONBASE_TERMINAL_TYPE,
        bank_id=ONBASE_BANK_ID,
        client_dt=datetime.utcnow().strftime("%Y-%m-%dT%H:%M:%S"),
        doc_handle=doc_handle,
        delivery_method=ONBASE_DELIVERY_METHOD,
        trn_seq=ONBASE_TRN_SEQ,
    )
    xml_text = await _post_soap(envelope)
    return _parse_document_markdown_response(xml_text)


async def get_customer_contact_info(
    participant_id: str,
    service_login_id: Optional[str] = None,
    type_id: str = "C",
    rq_uid: Optional[str] = None,
) -> CustomerContactInfoResponse:
    """Consulta datos de contacto del cliente mediante CustomerInformationInquiry SOAP.

    Args:
        participant_id: Identificación del cliente (ParticipantId).
        service_login_id: Login de servicio para CustLoginId.
        type_id: Tipo de identificación del cliente.
    """
    client_dt = datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")
    envelope = _build_customer_basic_info_envelope(
        cust_login_id=service_login_id or ONBASE_CUST_LOGIN_ID,
        network_owner=ONBASE_NETWORK_OWNER,
        terminal_id=ONBASE_TERMINAL_ID,
        bank_id=ONBASE_BANK_ID,
        client_dt=client_dt,
        participant_id=participant_id,
        type_id=type_id,
        rq_uid=rq_uid,
    )
    xml_text = await _post_soap(envelope, url=ONBASE_CUSTOMER_INFO_URL)
    return _parse_customer_info_response(xml_text)


def list_doc_types() -> List[dict]:
    """Devuelve la lista de tipos documentales soportados."""
    return [
        {
            "clave": key,
            "nombre": dt.name,
            "doc_type_id": dt.doc_type_id,
            "keywords": list(dt.keywords.keys()),
        }
        for key, dt in DOC_TYPES.items()
    ]
