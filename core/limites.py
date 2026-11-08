"""Límites del análisis de phishing: peticiones por usuario y tamaño de la petición."""
from __future__ import annotations

import math
import threading
import time
from collections import deque
from collections.abc import Callable, Hashable

from starlette.responses import JSONResponse
from starlette.types import ASGIApp, Message, Receive, Scope, Send


class LimiteVentana:
    """Ventana deslizante en memoria por clave. Devuelve 0 si permite, o los segundos de espera.

    Es por proceso: cada worker de gunicorn lleva su propia cuenta. Basta para su
    objetivo (acotar la CPU de cada worker) y no exige Redis, que el modo eager no tiene.
    Usa un lock porque los endpoints `def` corren en el threadpool.
    """

    def __init__(self, ventana_s: float = 60.0, reloj: Callable[[], float] = time.monotonic):
        self._ventana_s = ventana_s
        self._reloj = reloj
        self._lock = threading.Lock()
        self._marcas: dict[Hashable, deque[float]] = {}

    def comprobar(self, clave: Hashable, maximo: int) -> int:
        with self._lock:
            ahora = self._reloj()
            self._purgar(ahora)
            marcas = self._marcas.setdefault(clave, deque())
            if len(marcas) >= maximo:
                return max(1, math.ceil(marcas[0] + self._ventana_s - ahora))
            marcas.append(ahora)
            return 0

    def reiniciar(self) -> None:
        with self._lock:
            self._marcas.clear()

    def _purgar(self, ahora: float) -> None:
        # Quita las marcas vencidas de todos y olvida a los inactivos: el dict no crece sin límite.
        for clave in list(self._marcas):
            marcas = self._marcas[clave]
            while marcas and marcas[0] <= ahora - self._ventana_s:
                marcas.popleft()
            if not marcas:
                del self._marcas[clave]


class LimiteTamañoPeticion:
    """Responde 413 sin leer de más. Va como middleware porque FastAPI lee el cuerpo antes de las dependencias.

    Cuenta los bytes recibidos además de mirar Content-Length, que puede faltar (chunked) o mentir.
    """

    def __init__(self, app: ASGIApp, ruta: str, max_bytes: int):
        self.app = app
        self.ruta = ruta
        self.max_bytes = max_bytes

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http" or scope["path"] != self.ruta or scope["method"] != "POST":
            await self.app(scope, receive, send)
            return

        longitud = dict(scope["headers"]).get(b"content-length", b"")
        if longitud.isdigit() and int(longitud) > self.max_bytes:
            await self._rechazar(scope, receive, send)
            return

        recibidos: list[Message] = []
        total = 0
        while True:
            mensaje = await receive()
            recibidos.append(mensaje)
            if mensaje["type"] != "http.request":
                break
            total += len(mensaje.get("body", b""))
            if total > self.max_bytes:
                await self._rechazar(scope, receive, send)
                return
            if not mensaje.get("more_body", False):
                break

        async def reproducir() -> Message:
            return recibidos.pop(0) if recibidos else await receive()

        await self.app(scope, reproducir, send)

    @staticmethod
    async def _rechazar(scope: Scope, receive: Receive, send: Send) -> None:
        respuesta = JSONResponse({"detail": "El correo es demasiado grande para analizarlo."}, status_code=413)
        await respuesta(scope, receive, send)
