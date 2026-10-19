import os
import unittest
from unittest.mock import patch
from xml.etree import ElementTree

import httpx

from services import txdor_client


REAL_CLIENT = httpx.AsyncClient
BASE_ENV = {"TXDOR_USER": "usuario_prueba", "TXDOR_IDENTIFICATION": "000"}


class TxdorEnvironmentTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        env = patch.dict(os.environ, BASE_ENV)
        env.start()
        self.addCleanup(env.stop)
        for name in ("TXDOR_SOAP_URL", "TXDOR_OFFICE", "TXDOR_CLIENT_IP"):
            os.environ.pop(name, None)
        self.requests: list[httpx.Request] = []

        def handler(request: httpx.Request) -> httpx.Response:
            self.requests.append(request)
            return httpx.Response(200, text="<ok/>")

        def client_factory(*, timeout: float, verify: bool) -> httpx.AsyncClient:
            return REAL_CLIENT(
                transport=httpx.MockTransport(handler), timeout=timeout, verify=verify
            )

        client_patch = patch.object(
            txdor_client.httpx, "AsyncClient", side_effect=client_factory
        )
        client_patch.start()
        self.addCleanup(client_patch.stop)

    def _sent_values(self) -> tuple[str, str, str]:
        request = self.requests[-1]
        root = ElementTree.fromstring(request.content)
        ip = root.findtext(".//peConnectionIn/IP")
        office = next(
            entry.get("value") for entry in root.iter("EntryTxdor")
            if entry.get("key") == "PEOFIREC"
        )
        return str(request.url), office or "", ip or ""

    async def test_defaults_preserve_previous_values(self) -> None:
        await txdor_client.tranzar("ST", "123")
        self.assertEqual(self._sent_values(), (
            txdor_client.DEFAULT_TXDOR_SOAP_URL,
            txdor_client.DEFAULT_TXDOR_OFFICE,
            txdor_client.DEFAULT_TXDOR_CLIENT_IP,
        ))

    async def test_environment_overrides_are_used(self) -> None:
        with patch.dict(os.environ, {
            "TXDOR_SOAP_URL": "https://txdor.example.test/port",
            "TXDOR_OFFICE": "999",
            "TXDOR_CLIENT_IP": "192.0.2.10",
        }):
            await txdor_client.tranzar("ST", "123")
        self.assertEqual(self._sent_values(), (
            "https://txdor.example.test/port", "999", "192.0.2.10",
        ))

    async def test_invalid_values_never_reach_backend(self) -> None:
        for name, value in (
            ("TXDOR_SOAP_URL", "ftp://txdor.example.test"),
            ("TXDOR_SOAP_URL", "https://user:pass@txdor.example.test"),
            ("TXDOR_SOAP_URL", " "),
            ("TXDOR_OFFICE", " "),
            ("TXDOR_CLIENT_IP", "no-es-ip"),
        ):
            with self.subTest(name=name, value=value), patch.dict(
                os.environ, {name: value}
            ), self.assertRaisesRegex(ValueError, name):
                await txdor_client.tranzar("ST", "123")
        self.assertFalse(self.requests)


if __name__ == "__main__":
    unittest.main()
