# Extensión de Sentinel

Analiza el correo abierto en Gmail u Outlook web. No tiene dependencias ni paso de compilación.

## Instalación

1. Abre `chrome://extensions` y activa el **Modo de desarrollador**.
2. Pulsa **Cargar descomprimida** y elige esta carpeta.
3. Arranca la app en `http://localhost:8000`.

Para otro servidor, cambia `API_URL` en `popup.js` y añade su origen a `host_permissions` en `manifest.json`.

## Uso

1. En Sentinel, ve a **Mi cuenta** y pulsa **Generar token**. Solo se muestra una vez.
2. Abre un correo, pulsa el icono de Sentinel y guarda el token.
3. Pulsa **Analizar este correo**.

Los correos con menos de 100 caracteres no se envían: el modelo no es fiable con tan poco texto.

## Privacidad

- `activeTab`: la extensión solo lee la pestaña cuando se pulsa su icono.
- Del correo salen el asunto, el texto visible, los enlaces y los resultados de SPF, DKIM y DMARC, solo hacia `API_URL`.
- El token se guarda en `chrome.storage.local`, sin cifrar en el perfil del navegador. Nunca llega a la página del correo.

## Limitaciones

- Los selectores de Gmail y Outlook no son una API pública: pueden dejar de funcionar si cambian su HTML.
- SPF, DKIM y DMARC solo se leen en Gmail. En Outlook el resultado se basa solo en el contenido, y el popup lo avisa.

## Pruebas

```sh
node --test "extension/tests/*.test.js"
```
