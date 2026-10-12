"""Verificações: ping, porta TCP, site (HTTP) e nobreak (NUT).

Cada função devolve um Resultado(ok, latencia_ms, detalhe) e nunca levanta exceção.
"""
import re
import socket
import subprocess
import time
import urllib.error
import urllib.request
from dataclasses import dataclass


@dataclass
class Resultado:
    ok: bool
    latencia_ms: float | None
    detalhe: str


def checar(alvo: dict, timeout: float = 3.0) -> Resultado:
    tipo = alvo.get("tipo")
    try:
        if tipo == "ping":
            return ping(alvo["host"], timeout)
        if tipo == "tcp":
            return tcp(alvo["host"], int(alvo["porta"]), timeout)
        if tipo == "http":
            return http(alvo["url"], timeout, int(alvo.get("status_esperado", 0)))
        if tipo == "nut":
            return nut(alvo["host"], alvo.get("ups", "ups"), int(alvo.get("porta", 3493)), timeout)
        return Resultado(False, None, f"tipo desconhecido: {tipo}")
    except Exception as erro:  # qualquer surpresa vira "falhou", nunca derruba o monitor
        return Resultado(False, None, f"erro: {erro}")


# --- ping ---------------------------------------------------------------
_TEMPO_PING = re.compile(r"time[=<]([\d.]+)\s*ms")


def interpretar_ping(saida: str) -> float | None:
    m = _TEMPO_PING.search(saida)
    return float(m.group(1)) if m else None


def ping(host: str, timeout: float) -> Resultado:
    proc = subprocess.run(
        ["ping", "-c", "1", "-W", str(max(1, int(timeout))), host],
        capture_output=True, text=True, timeout=timeout + 2,
    )
    if proc.returncode == 0:
        return Resultado(True, interpretar_ping(proc.stdout), "respondendo")
    return Resultado(False, None, "sem resposta ao ping")


# --- porta TCP (câmera, servidor, impressora...) --------------------------
def tcp(host: str, porta: int, timeout: float) -> Resultado:
    inicio = time.perf_counter()
    try:
        with socket.create_connection((host, porta), timeout=timeout):
            pass
    except OSError:
        return Resultado(False, None, f"porta {porta} não responde")
    return Resultado(True, round((time.perf_counter() - inicio) * 1000, 1), f"porta {porta} aberta")


# --- site / sistema web -------------------------------------------------
def http(url: str, timeout: float, status_esperado: int = 0) -> Resultado:
    pedido = urllib.request.Request(url, headers={"User-Agent": "monitor-rede-energia/1.0"})
    inicio = time.perf_counter()
    try:
        with urllib.request.urlopen(pedido, timeout=timeout) as resp:
            status = resp.status
    except urllib.error.HTTPError as erro:
        status = erro.code
    except (urllib.error.URLError, OSError) as erro:
        return Resultado(False, None, f"site não abre ({getattr(erro, 'reason', erro)})")
    ms = round((time.perf_counter() - inicio) * 1000, 1)
    ok = status == status_esperado if status_esperado else status < 400
    return Resultado(ok, ms if ok else None, f"HTTP {status}")


# --- nobreak via NUT (Network UPS Tools) ---------------------------------
# Status mais comuns: OL = na tomada, OB = na bateria, LB = bateria fraca
_VAR = re.compile(r'^VAR \S+ (\S+) "(.*)"$')


def interpretar_nut(texto: str) -> dict:
    variaveis = {}
    for linha in texto.splitlines():
        m = _VAR.match(linha.strip())
        if m:
            variaveis[m.group(1)] = m.group(2)
    return variaveis


def descrever_nobreak(v: dict) -> Resultado:
    status = v.get("ups.status", "").split()
    carga = v.get("battery.charge")
    autonomia = v.get("battery.runtime")
    partes = []
    if carga:
        partes.append(f"bateria {carga}%")
    if autonomia and autonomia.isdigit():
        partes.append(f"autonomia ~{int(autonomia) // 60} min")
    extra = (", " + ", ".join(partes)) if partes else ""

    if "OB" in status or "LB" in status:
        fraca = " (BATERIA FRACA)" if "LB" in status else ""
        return Resultado(False, None, f"nobreak na bateria{fraca}{extra}")
    if "OL" in status:
        return Resultado(True, None, f"energia normal{extra}")
    return Resultado(False, None, f"status desconhecido: {v.get('ups.status', '?')}")


def nut(host: str, ups: str, porta: int, timeout: float) -> Resultado:
    try:
        with socket.create_connection((host, porta), timeout=timeout) as s:
            s.sendall(f"LIST VAR {ups}\n".encode())
            dados = b""
            while b"END LIST VAR" not in dados and b"ERR" not in dados:
                pedaco = s.recv(4096)
                if not pedaco:
                    break
                dados += pedaco
    except OSError:
        return Resultado(False, None, "sem comunicação com o nobreak")
    texto = dados.decode(errors="replace")
    if "ERR" in texto:
        return Resultado(False, None, f"nobreak respondeu erro: {texto.strip()[:60]}")
    return descrever_nobreak(interpretar_nut(texto))
