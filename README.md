# MCP BdB 360

Servidor MCP (Model Context Protocol) construido con FastMCP que permite a
agentes y clientes MCP invocar dos servicios SOAP: el Transaccionador v4 y
la consulta de productos de un cliente. Las herramientas se registran en
[mcp_server.py](./mcp_server.py) y se publican mediante Streamable HTTP desde
[app.py](./app.py).

## Herramientas y parametros

Todos los parametros de las herramientas son obligatorios y de tipo texto
(`string`). Los destinos y la configuracion tecnica se obtienen en el servidor;
no son argumentos de las llamadas.

### txdor_tranzar

Ejecuta la operacion `tranzar` del Transaccionador v4 para consultar una cuenta.
Su cliente SOAP esta en [services/txdor_client.py](./services/txdor_client.py).

| Parametro | Tipo | Descripcion |
| --- | --- | --- |
| `tipo_cuenta` | `string` | Codigo de cuenta: `ST` para ahorros, `IM` para corriente o `AM` para creditos ALS. Se eliminan espacios al inicio y al final y se convierte a mayusculas. |
| `numero_cuenta` | `string` | Numero de cuenta no vacio. Se eliminan espacios al inicio y al final. Enviarlo como texto para preservar ceros iniciales. |

Ejemplo con datos ficticios:

```json
{
  "name": "txdor_tranzar",
  "arguments": {
    "tipo_cuenta": "ST",
    "numero_cuenta": "000123456"
  }
}
```

### consultaProductos

Consulta los productos asociados a la identificacion de un cliente.
Su cliente SOAP esta en
[services/productos_client.py](./services/productos_client.py).

| Parametro | Tipo | Descripcion |
| --- | --- | --- |
| `aa_nit` | `string` | Identificacion no vacia, formada unicamente por digitos ASCII, sin espacios, puntos ni guiones. Preserva ceros iniciales. |

Ejemplo con datos ficticios:

```json
{
  "name": "consultaProductos",
  "arguments": {
    "aa_nit": "000123"
  }
}
```

### Respuesta de las herramientas

Ambas devuelven un objeto con el estado HTTP y la respuesta XML original del
servicio. No transforman el XML en una lista normalizada de cuentas o productos.

```json
{
  "status_code": 200,
  "response": "<XML SOAP original del servicio>"
}
```

Las identificaciones, cuentas y respuestas deben tratarse como datos sensibles.
El consumidor debe estar autorizado para realizar la consulta; no registrar esos
datos en logs.

## Detalle de consultaProductos

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
