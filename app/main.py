"""Loop principal: verifica tudo a cada intervalo, guarda o histórico e dispara os alertas."""
import os
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta

from . import checks, relatorio
from .alertas import Alertas
from .banco import Banco
from .config import carregar
from .estado import EstadoAlvo, atualizar, duracao_legivel
from .painel import iniciar_painel

FMT = "%Y-%m-%d %H:%M:%S"


def agora() -> datetime:
    return datetime.now().replace(microsecond=0)


def log(msg):
    print(f"{agora():%d/%m %H:%M:%S} {msg}", flush=True)


class Monitor:
    def __init__(self, cfg, banco: Banco, alertas: Alertas):
        self.cfg = cfg
        self.geral = cfg["geral"]
        self.alvos = cfg["alvos"]
        self.banco = banco
        self.alertas = alertas
        self.estados = {a["nome"]: EstadoAlvo() for a in self.alvos}
        self.trava = threading.Lock()
        self.iniciado_em = agora()

        # Quedas que estavam abertas quando o monitor foi desligado continuam "fora"
        for ev in banco.eventos_abertos():
            if ev["alvo"] in self.estados:
                est = self.estados[ev["alvo"]]
                est.ok, est.desde, est.falhas = False, ev["inicio"], self.geral["falhas_para_alerta"]

    # --- mensagens ---------------------------------------------------------
    def _mensagem(self, alvo, evento):
        cliente = self.geral["cliente"]
        energia = alvo["categoria"] == "energia"
        if evento[0] == "caiu":
            hora = datetime.strptime(evento[1], FMT).strftime("%H:%M")
            if energia:
                return f"⚡ {cliente}: falta de energia — {alvo['nome']}: {evento[2]} (desde {hora})."
            return f"🔴 {cliente}: {alvo['nome']} está fora do ar desde {hora}.\nDetalhe: {evento[2]}"
        duracao = duracao_legivel(evento[1], evento[2]) if evento[1] else "tempo desconhecido"
        if energia:
            return f"🔌 {cliente}: energia restabelecida ({alvo['nome']}). Ficou {duracao} sem energia."
        return f"🟢 {cliente}: {alvo['nome']} voltou. Ficou fora por {duracao}."

    # --- um ciclo de verificações -------------------------------------------
    def ciclo(self, executor):
        timeout = self.geral["timeout_segundos"]
        resultados = list(executor.map(lambda a: checks.checar(a, timeout), self.alvos))
        ts = agora().strftime(FMT)

        for alvo, res in zip(self.alvos, resultados):
            self.banco.medicao(ts, alvo["nome"], res.ok, res.latencia_ms)
            with self.trava:
                evento = atualizar(self.estados[alvo["nome"]], res.ok, ts, res.detalhe,
                                   self.geral["falhas_para_alerta"], res.latencia_ms)
            if not evento:
                continue
            if evento[0] == "caiu":
                self.banco.abrir_evento(alvo["nome"], alvo["categoria"], evento[1], evento[2])
            else:
                self.banco.fechar_evento(alvo["nome"], evento[2])
            self.alertas.enviar(self._mensagem(alvo, evento), {
                "evento": evento[0], "alvo": alvo["nome"], "categoria": alvo["categoria"],
                "cliente": self.geral["cliente"], "inicio": evento[1],
                "fim": evento[2] if evento[0] == "voltou" else None,
            })

        self.alertas.heartbeat(self.cfg["segredos"]["heartbeat_url"])

    # --- relatório mensal (dia 1, a partir das 8h, do mês anterior) -------
    def relatorio_mensal_se_for_hora(self):
        hoje = agora()
        if hoje.day != 1 or hoje.hour < 8:
            return
        anterior = hoje.replace(day=1) - timedelta(days=1)
        chave = f"{anterior:%Y-%m}"
        if self.banco.meta("ultimo_relatorio") == chave:
            return
        self.enviar_relatorio(anterior.year, anterior.month)
        self.banco.meta("ultimo_relatorio", chave)

    def enviar_relatorio(self, ano, mes):
        dados = relatorio.calcular(self.banco, self.alvos, ano, mes, agora())
        conteudo = relatorio.html(self.geral["cliente"], self.geral["responsavel"], dados, ano, mes)
        nome = f"relatorio-{ano}-{mes:02d}.html"
        pasta = os.getenv("PASTA_RELATORIOS", "/dados/relatorios")
        os.makedirs(pasta, exist_ok=True)
        with open(os.path.join(pasta, nome), "w", encoding="utf-8") as f:
            f.write(conteudo)
        self.alertas.enviar_arquivo(nome, conteudo.encode("utf-8"),
                                    relatorio.resumo_texto(self.geral["cliente"], dados, ano, mes))

    # --- status para o painel ---------------------------------------------
    def status(self):
        with self.trava:
            return [{"nome": a["nome"], "tipo": a["tipo"], "categoria": a["categoria"],
                     "ok": self.estados[a["nome"]].ok, "desde": self.estados[a["nome"]].desde,
                     "falhas": self.estados[a["nome"]].falhas, "detalhe": self.estados[a["nome"]].detalhe,
                     "latencia_ms": self.estados[a["nome"]].latencia_ms,
                     "ultima_verificacao": self.estados[a["nome"]].ultima_verificacao}
                    for a in self.alvos]

    def rodar(self):
        intervalo = self.geral["intervalo_segundos"]
        self.alertas.enviar(f"✅ Monitor iniciado · {self.geral['cliente']}: "
                            f"{len(self.alvos)} equipamento(s) vigiado(s) a cada {intervalo}s.")
        with ThreadPoolExecutor(max_workers=min(16, len(self.alvos))) as executor:
            while True:
                inicio = time.monotonic()
                try:
                    self.ciclo(executor)
                    self.relatorio_mensal_se_for_hora()
                    self.banco.limpar_antigos((agora() - timedelta(days=400)).strftime(FMT))
                except Exception as erro:  # o monitor nunca pode parar
                    log(f"[ERRO] no ciclo: {erro}")
                time.sleep(max(1, intervalo - (time.monotonic() - inicio)))


def principal():
    try:
        cfg = carregar(os.getenv("CONFIG", "/config/config.toml"))
    except ValueError as erro:
        log(f"[CONFIG] {erro}")
        time.sleep(30)   # evita reiniciar em loop rápido enquanto o arquivo é corrigido
        raise SystemExit(1)
    seg = cfg["segredos"]
    banco = Banco(os.getenv("BANCO", "/dados/monitor.db"))
    alertas = Alertas(seg["telegram_token"], seg["telegram_chat_id"], seg["webhook_url"], seg["modo_teste"], log)
    monitor = Monitor(cfg, banco, alertas)
    porta = int(os.getenv("PORTA_PAINEL", "8090"))
    iniciar_painel(monitor, porta)
    log(f"Painel em http://localhost:{porta} · modo teste: {seg['modo_teste']}")
    monitor.rodar()


if __name__ == "__main__":
    principal()
