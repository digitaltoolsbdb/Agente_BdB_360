import os
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import httpx
from mcp.server.fastmcp.exceptions import ToolError

from mcp_server import mcp
from services import productos_client


REAL_CLIENT = httpx.AsyncClient
SOAP_RESPONSE = b"""<s:Envelope xmlns:s="http://schemas.xmlsoap.org/soap/envelope/">
<s:Body><ProductsResponse/></s:Body></s:Envelope>"""


class ProductosTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, {
            "CONSULTA_PRODUCTOS_SOAP_URL": "https://productos.example.test/soap",
            "CONSULTA_PRODUCTOS_TIMEOUT_SECONDS": "5",
        })
        env.start()
        self.addCleanup(env.stop)
        self.requests: list[httpx.Request] = []
        self.response = httpx.Response(200, content=SOAP_RESPONSE)
        self.failure: httpx.HTTPError | None = None

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            if self.failure is not None:
                raise self.failure
            return self.response

        def client_factory(
            *, timeout: float, verify: bool, follow_redirects: bool
        ) -> httpx.AsyncClient:
            self.assertEqual(timeout, 5)
            self.assertTrue(verify)
            self.assertFalse(follow_redirects)
            return REAL_CLIENT(
                transport=httpx.MockTransport(handler),
                timeout=timeout, verify=verify, follow_redirects=follow_redirects,
            )

        client_patch = patch.object(
            productos_client.httpx, "AsyncClient", side_effect=client_factory
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    async def test_real_server_lists_both_tools_and_single_product_argument(self) -> None:
        tools = {tool.name: tool for tool in await mcp.list_tools()}
        self.assertIn("txdor_tranzar", tools)
        self.assertIn("consultaProductos", tools)
        schema = tools["consultaProductos"].inputSchema
        self.assertEqual(schema["required"], ["aa_nit"])
        self.assertEqual(set(schema["properties"]), {"aa_nit"})
        self.assertEqual(schema["properties"]["aa_nit"]["type"], "string")

    async def test_mcp_call_and_exact_soap_contract(self) -> None:
        result = await mcp.call_tool("consultaProductos", {"aa_nit": "000123"})
        self.assertIsInstance(result, tuple)
        assert isinstance(result, tuple)
        self.assertEqual(result[1], {
            "status_code": 200, "response": SOAP_RESPONSE.decode(),
        })
        self.assertEqual(len(self.requests), 1)
        request = self.requests[0]
        self.assertEqual(request.method, "POST")
        self.assertEqual(str(request.url), "https://productos.example.test/soap")
        self.assertEqual(request.headers["Content-Type"], "text/xml; charset=utf-8")
        self.assertNotIn("authorization", request.headers)
        self.assertNotIn("soapaction", request.headers)
        soap = f"{{{productos_client.SOAP_ENV_NS}}}"
        bb = f"{{{productos_client.PRODUCTOS_NS}}}"
        root = ElementTree.fromstring(request.content)
        self.assertEqual(root.tag, f"{soap}Envelope")
        self.assertIsNotNone(root.find(f"{soap}Header"))
        record = root.find(
            f"{soap}Body/{bb}BB_PECONSUPRODPSREQ/{bb}MsgData/"
            f"{bb}Transaction/{bb}BB_PECLIPRGET_I"
        )
        assert record is not None
        self.assertEqual(record.attrib, {"class": "R"})
        self.assertEqual([(node.tag, node.attrib, node.text) for node in record], [
            (f"{bb}AA_TIPO_DOC", {"type": "CHAR"}, "C"),
            (f"{bb}AA_NIT", {"type": "CHAR"}, "000123"),
            (f"{bb}PRODUCT_GROUP", {"type": "CHAR"}, " "),
            (f"{bb}FIN_ACCOUNT_ID", {"type": "CHAR"}, None),
            (f"{bb}CANAL", {}, None),
        ])

    async def test_invalid_mcp_arguments_never_reach_backend(self) -> None:
        for arguments in ({}, {"aa_nit": 123}, {"aa_nit": ""}, {"aa_nit": "<tag/>"}):
            with self.subTest(arguments=arguments), self.assertRaises(ToolError):
                await mcp.call_tool("consultaProductos", arguments)
        self.assertFalse(self.requests)

    async def test_unconfigured_or_unsafe_url_never_reaches_backend(self) -> None:
        for url in ("", "http://productos.example.test/soap", "https://[invalid",
                    "https://productos.example.test/soap%22"):
            with self.subTest(url=url), patch.dict(
                os.environ, {"CONSULTA_PRODUCTOS_SOAP_URL": url}
            ), self.assertRaises(ToolError):
                await productos_client.consultar_productos("000123")
        self.assertFalse(self.requests)

    async def test_invalid_timeouts_never_reach_backend(self) -> None:
        for value in ("0", "-1", "nan", "inf", "abc"):
            with self.subTest(timeout=value), patch.dict(
                os.environ, {"CONSULTA_PRODUCTOS_TIMEOUT_SECONDS": value}
            ), self.assertRaises(ToolError):
                await productos_client.consultar_productos("000123")
        self.assertFalse(self.requests)

    async def test_http_errors_and_redirects_are_not_retried(self) -> None:
        for status in (301, 307, 401, 403, 500):
            self.requests.clear()
            self.response = httpx.Response(
                status, text="sensitive detail",
                headers={"Location": "https://other.example.test"},
            )
            with self.subTest(status=status), self.assertRaisesRegex(
                ToolError, f"HTTP {status}"
            ) as caught:
                await productos_client.consultar_productos("000123")
            self.assertNotIn("sensitive", str(caught.exception))
            self.assertEqual(len(self.requests), 1)

    async def test_timeout_and_connection_errors_are_sanitized(self) -> None:
        for failure in (httpx.ReadTimeout("sensitive"), httpx.ConnectError("sensitive")):
            self.failure = failure
            with self.subTest(failure=type(failure)), self.assertRaises(ToolError) as caught:
                await productos_client.consultar_productos("000123")
            self.assertNotIn("sensitive", str(caught.exception))

    async def test_fault_invalid_xml_and_dtd_are_errors(self) -> None:
        for content in (
            b"", b"<html/>",
            SOAP_RESPONSE.replace(b"<ProductsResponse/>", b"<s:Fault/>"),
            b"<!DOCTYPE Envelope>" + SOAP_RESPONSE,
        ):
            self.response = httpx.Response(200, content=content)
            with self.subTest(content=content), self.assertRaises(ToolError):
                await productos_client.consultar_productos("000123")


if __name__ == "__main__":
    unittest.main()
