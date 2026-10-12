"""Estado de cada equipamento vigiado e a regra que decide quando avisar.

Uma falha isolada não gera alerta: só depois de N falhas seguidas o equipamento
é considerado "fora do ar" (evita alarme falso por um ping perdido). Na primeira
resposta boa ele volta a "no ar" e o tempo fora é calculado a partir da 1ª falha.
"""
from dataclasses import dataclass
from datetime import datetime


@dataclass
class EstadoAlvo:
    ok: bool | None = None          # None = ainda não sabemos (acabou de iniciar)
    falhas: int = 0                 # falhas seguidas
    desde: str | None = None        # quando caiu (horário da 1ª falha), se estiver fora
    primeira_falha: str | None = None
    detalhe: str = ""
    latencia_ms: float | None = None
    ultima_verificacao: str | None = None


def atualizar(est: EstadoAlvo, ok: bool, agora: str, detalhe: str,
              falhas_para_alerta: int, latencia_ms: float | None = None):
    """Aplica o resultado de uma verificação e devolve o evento gerado (ou None).

    Eventos:  ("caiu", inicio, detalhe)   ("voltou", inicio, fim)
    """
    est.detalhe = detalhe
    est.latencia_ms = latencia_ms if ok else None
    est.ultima_verificacao = agora

    if ok:
        evento = ("voltou", est.desde, agora) if est.ok is False else None
        est.ok, est.falhas, est.desde, est.primeira_falha = True, 0, None, None
        return evento

    est.falhas += 1
    if est.falhas == 1:
        est.primeira_falha = agora
    if est.ok is not False and est.falhas >= falhas_para_alerta:
        est.ok, est.desde = False, est.primeira_falha
        return ("caiu", est.desde, detalhe)
    return None


def duracao_legivel(inicio: str, fim: str) -> str:
    """'2026-10-12 08:00:00' → '2026-10-12 09:15:30' = '1 h 15 min'."""
    segundos = int((datetime.fromisoformat(fim) - datetime.fromisoformat(inicio)).total_seconds())
    return formatar_segundos(segundos)


def formatar_segundos(segundos: float) -> str:
    segundos = int(segundos)
    if segundos < 60:
        return "menos de 1 min"
    minutos = segundos // 60
    if minutos < 60:
        return f"{minutos} min"
    horas, minutos = divmod(minutos, 60)
    if horas < 24:
        return f"{horas} h {minutos} min" if minutos else f"{horas} h"
    dias, horas = divmod(horas, 24)
    return f"{dias} d {horas} h" if horas else f"{dias} d"
