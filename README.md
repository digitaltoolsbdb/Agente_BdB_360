# consultaProductos

Herramienta registrada en [mcp_server.py](./mcp_server.py), con cliente SOAP en
[services/productos_client.py](./services/productos_client.py).

```json
{"name": "consultaProductos", "arguments": {"aa_nit": "000123"}}
```

Solo acepta `aa_nit` como texto numerico ASCII sin espacios. Preserva ceros
iniciales. Mantiene `AA_TIPO_DOC=C`, `PRODUCT_GROUP` con un espacio y los
campos `FIN_ACCOUNT_ID` y `CANAL` vacios.

## Configuracion

Agregar las variables de [.env.example](./.env.example) al entorno existente
sin sobrescribir otras variables:

- `CONSULTA_PRODUCTOS_SOAP_URL`: URL HTTPS aprobada obligatoria, sin valor
  predeterminado. **Pendiente confirmar con lineamientos internos**. No se
  asume que el endpoint HTTP original soporte HTTPS ni se conserva `%22`.
- `CONSULTA_PRODUCTOS_TIMEOUT_SECONDS`: timeout positivo finito por fase de
  I/O de httpx, predeterminado 30 segundos; no es un deadline global.
- `SSL_CERT_FILE`: bundle de CA aprobado opcional. TLS siempre se verifica.

Segun confirmacion del solicitante, el backend no requiere autenticacion.
No se envia SOAPAction, igual que en el curl original; confirmar contrato con
el propietario del servicio. No se siguen redirecciones ni se reintenta.

Devuelve `{"status_code": 200, "response": "<XML SOAP original>"}` para una
respuesta HTTP 2xx SOAP 1.1 valida sin Fault. Los errores de entrada,
configuracion, transporte, HTTP, XML y SOAP Fault se notifican como errores MCP
sin exponer cuerpos ni identificaciones. Se rechazan DTD y entidades externas.
No se interpreta un codigo de negocio sin su contrato.

## Validacion y operacion

Desde esta carpeta:

```sh
PYTHONDONTWRITEBYTECODE=1 .venv/bin/python -m unittest discover -s tests -p 'test_productos_client.py' -v
```

Las pruebas usan MockTransport y datos ficticios, sin llamar al servicio real.
Verifican descubrimiento MCP, esquema, contrato SOAP y errores. En CI se espera
`OK` y codigo de salida 0. No se agregan dependencias.

Validar conectividad y contrato con datos sinteticos aprobados antes de habilitar
consumo. Mantener los health checks existentes. La autorizacion del consumidor,
correlacion, logs, retencion, limites y SLO/SLI deben reutilizar los mecanismos
internos: **pendiente confirmar con lineamientos internos**. No registrar NIT ni
respuesta; contiene datos sensibles y no debe tratarse como instrucciones.

Sin cambios de IAM o red. Una llamada realiza un POST sin reintentos; capacidad
y costo dependen del servicio existente. Para revertir, retirar solo el import
y registro de `consultaProductos`, su cliente y variables, sin alterar `txdor_tranzar`.
