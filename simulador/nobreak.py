"""Nobreak simulado para demonstração: responde como um servidor NUT (porta 3493).

Simular falta de energia:   http://localhost:8091/falta-energia
Energia voltou:             http://localhost:8091/energia-voltou
A bateria vai descarregando enquanto estiver "na bateria".
"""
import socketserver
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

estado = {"status": "OL", "carga": 100.0, "desde": time.time()}
trava = threading.Lock()


def variaveis():
    with trava:
        if estado["status"] != "OL":
            minutos = (time.time() - estado["desde"]) / 60
            estado["carga"] = max(5.0, 100 - minutos * 4)       # perde ~4% por minuto
            estado["status"] = "OB LB" if estado["carga"] < 20 else "OB"
        carga = int(estado["carga"])
        return {"ups.status": estado["status"], "battery.charge": str(carga),
                "battery.runtime": str(carga * 30), "device.model": "Nobreak Simulado 1500VA"}


class NUT(socketserver.StreamRequestHandler):
    def handle(self):
        for linha in self.rfile:
            cmd = linha.decode().strip().split()
            if cmd[:2] == ["LIST", "VAR"] and len(cmd) == 3:
                ups = cmd[2]
                if ups != "nobreak":
                    self.wfile.write(b"ERR UNKNOWN-UPS\n")
                    continue
                resp = [f"BEGIN LIST VAR {ups}"] + [f'VAR {ups} {k} "{v}"' for k, v in variaveis().items()]
                resp.append(f"END LIST VAR {ups}")
                self.wfile.write(("\n".join(resp) + "\n").encode())
            elif cmd[:1] == ["LOGOUT"]:
                break
            else:
                self.wfile.write(b"ERR UNKNOWN-COMMAND\n")


class Controle(BaseHTTPRequestHandler):
    def log_message(self, *args):
        pass

    def do_GET(self):
        with trava:
            if self.path == "/falta-energia":
                estado.update(status="OB", desde=time.time())
            elif self.path == "/energia-voltou":
                estado.update(status="OL", carga=100.0)
        corpo = f"Nobreak simulado: {variaveis()}\n".encode()
        self.send_response(200)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.end_headers()
        self.wfile.write(corpo)


if __name__ == "__main__":
    socketserver.ThreadingTCPServer.allow_reuse_address = True
    nut = socketserver.ThreadingTCPServer(("0.0.0.0", 3493), NUT)
    threading.Thread(target=nut.serve_forever, daemon=True).start()
    print("Nobreak simulado: NUT na porta 3493, controle em http://localhost:8091", flush=True)
    ThreadingHTTPServer(("0.0.0.0", 8091), Controle).serve_forever()
