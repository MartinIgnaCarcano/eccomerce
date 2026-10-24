"""Manda TODOS los logs de la API (cualquier nivel) y los print() a logs/app.log.

En el servidor (LiteSpeed) la salida de print() se pierde y además es ASCII
(un print con tilde explota). Flask, por su parte, solo muestra WARNING.
Esto se llama desde passenger_wsgi.py antes de importar la app.

Ver en vivo:   tail -f /home/loveuotk/caricias/api/logs/app.log
"""
import io
import logging
import os
import sys
from logging.handlers import WatchedFileHandler

LOG_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "logs")
LOG_FILE = os.path.join(LOG_DIR, "app.log")

_configurado = False


class _PrintALog(io.TextIOBase):
    """Reemplaza sys.stdout: cada línea de print() sale como un log con fecha."""

    def __init__(self, logger):
        self._logger = logger
        self._buf = ""

    def writable(self):
        return True

    def write(self, s):
        self._buf += s
        while "\n" in self._buf:
            linea, self._buf = self._buf.split("\n", 1)
            if linea.strip():
                self._logger.info(linea)
        return len(s)

    def flush(self):
        if self._buf.strip():
            self._logger.info(self._buf)
        self._buf = ""


def configurar_logs():
    global _configurado
    if _configurado:
        return
    _configurado = True

    os.makedirs(LOG_DIR, exist_ok=True)
    # El log tiene emails de clientes: que no se pueda bajar por la web
    htaccess = os.path.join(LOG_DIR, ".htaccess")
    if not os.path.exists(htaccess):
        with open(htaccess, "w") as f:
            f.write("Require all denied\n")

    # WatchedFileHandler: si se borra o rota app.log, lo vuelve a crear solo
    handler = WatchedFileHandler(LOG_FILE, encoding="utf-8")
    handler.setFormatter(logging.Formatter(
        "[%(asctime)s] %(levelname)s %(name)s (pid %(process)d): %(message)s"
    ))

    root = logging.getLogger()
    root.setLevel(logging.INFO)
    root.addHandler(handler)

    # Flask no agrega su handler a stderr si el root ya tiene uno: todo va a app.log
    sys.stdout = _PrintALog(logging.getLogger("print"))
    logging.getLogger("print").info("===== API iniciada =====")
