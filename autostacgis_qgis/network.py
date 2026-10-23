import json
from urllib.parse import urljoin

from qgis.core import QgsNetworkAccessManager
from qgis.PyQt.QtCore import QByteArray, QUrl
from qgis.PyQt.QtNetwork import QNetworkRequest

from .compat import qt_enum
from .model import api_url, same_origin


class Client:
    def __init__(self, url, token=""):
        self.url = api_url(url)
        self.token = token
        self.pending = set()
        self.closed = False

    def request(self, path, success, error, method="GET", body=None):
        url = urljoin(self.url, path)
        if not same_origin(self.url, url):
            raise ValueError("Requests must remain on the connected API origin")
        request = QNetworkRequest(QUrl(url))
        request.setRawHeader(b"Accept", b"application/geo+json, application/json")
        request.setRawHeader(b"Content-Type", b"application/json")
        if self.token:
            request.setRawHeader(b"Authorization", ("Bearer " + self.token).encode())
        if hasattr(request, "setTransferTimeout"):
            request.setTransferTimeout(600000 if "plugins/install" in path else 60000)
        manager = QgsNetworkAccessManager.instance()
        if method == "GET":
            reply = manager.get(request)
        else:
            payload = QByteArray(json.dumps(body).encode()) if body is not None else QByteArray()
            reply = manager.sendCustomRequest(request, method.encode(), payload)
        self.pending.add(reply)

        def finished():
            self.pending.discard(reply)
            try:
                if self.closed:
                    return
                raw = bytes(reply.readAll()).decode()
                status = reply.attribute(qt_enum(QNetworkRequest, "Attribute", "HttpStatusCodeAttribute"))
                if not status or int(status) >= 400:
                    error(raw or reply.errorString())
                else:
                    success(json.loads(raw) if raw else {}, url)
            except Exception as exc:
                error(str(exc))
            finally:
                reply.deleteLater()

        reply.finished.connect(finished)

    def close(self):
        self.closed = True
        for reply in list(self.pending):
            reply.abort()
