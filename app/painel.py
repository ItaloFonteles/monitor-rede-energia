"""Painel web simples: status ao vivo, API JSON e relatório do mês."""
import json
import threading
from datetime import datetime
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from . import relatorio
from .estado import duracao_legivel

ICONES = {"rede": "🖧", "energia": "⚡", "servico": "🌐"}


def pagina_status(monitor) -> str:
    agora = datetime.now().replace(microsecond=0).strftime("%Y-%m-%d %H:%M:%S")
    itens = monitor.status()
    fora = [i for i in itens if i["ok"] is False]

    def cartao(i):
        if i["ok"] is None:
            cls, txt = "espera", "verificando…"
        elif i["ok"]:
            cls = "ok"
            txt = f"{i['latencia_ms']:.0f} ms" if i["latencia_ms"] is not None else ("energia OK" if i["categoria"] == "energia" else "no ar")
        else:
            cls, txt = "fora", f"fora há {duracao_legivel(i['desde'], agora)}" if i["desde"] else "fora"
        if i["ok"] and i["falhas"]:
            cls, txt = "instavel", f"{i['falhas']} falha(s) seguida(s)"
        return (f"<div class='alvo {cls}'><div class='nome'>{ICONES.get(i['categoria'], '')} {escape(i['nome'])}</div>"
                f"<div class='estado'>{txt}</div><div class='det'>{escape(i['detalhe'] or '')}</div></div>")

    eventos = monitor.banco.eventos_recentes(12)
    linhas_ev = "".join(
        f"<tr><td>{escape(e['alvo'])}</td><td>{e['inicio'][8:10]}/{e['inicio'][5:7]} {e['inicio'][11:16]}</td>"
        f"<td>{(e['fim'][8:10] + '/' + e['fim'][5:7] + ' ' + e['fim'][11:16]) if e['fim'] else '<b>ainda fora</b>'}</td>"
        f"<td>{duracao_legivel(e['inicio'], e['fim'] or agora)}</td><td>{escape(e['detalhe'] or '')}</td></tr>"
        for e in eventos) or "<tr><td colspan='5'>Nenhuma queda registrada ainda.</td></tr>"

    resumo = (f"<span class='tag fora'>{len(fora)} fora do ar</span>" if fora
              else "<span class='tag ok'>Tudo funcionando</span>")
    mes = datetime.now().strftime("%Y-%m")
    return f"""<!DOCTYPE html><html lang="pt-br"><head><meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1"><meta http-equiv="refresh" content="20">
<title>Monitor · {escape(monitor.geral['cliente'])}</title>
<style>
  :root {{ --bg:#f4ecdc; --card:#fbf7ef; --borda:#e3d3b4; --txt:#24191a; --suave:#6b5d5f; }}
  * {{ box-sizing:border-box; }}
  body {{ margin:0; font-family:"Segoe UI",Arial,sans-serif; background:var(--bg); color:var(--txt); }}
  header {{ background:linear-gradient(120deg,#2e0b12,#7a1f2b); color:#fff; padding:18px 20px; border-bottom:3px solid #c9a24b;
           display:flex; justify-content:space-between; align-items:center; gap:12px; flex-wrap:wrap; }}
  h1 {{ margin:0; font-size:20px; }} header small {{ color:#e3c47a; }}
  main {{ max-width:1000px; margin:0 auto; padding:18px 16px; }}
  .tag {{ padding:6px 12px; border-radius:999px; font-weight:700; font-size:14px; }}
  .tag.ok {{ background:#d9f2e3; color:#1f7a4d; }} .tag.fora {{ background:#fde2e0; color:#b42318; }}
  .grade {{ display:grid; grid-template-columns:repeat(auto-fill,minmax(220px,1fr)); gap:12px; }}
  .alvo {{ background:var(--card); border:1px solid var(--borda); border-left:6px solid #999; border-radius:10px; padding:12px 14px; }}
  .alvo.ok {{ border-left-color:#1f9d55; }} .alvo.fora {{ border-left-color:#d92d20; background:#fff3f2; }}
  .alvo.instavel {{ border-left-color:#d69e2e; }} .alvo.espera {{ border-left-color:#999; }}
  .nome {{ font-weight:700; }} .estado {{ font-size:22px; margin:4px 0; }} .det {{ color:var(--suave); font-size:13px; }}
  h2 {{ font-size:15px; text-transform:uppercase; letter-spacing:1px; color:#7a1f2b; margin:26px 0 8px; }}
  table {{ width:100%; border-collapse:collapse; background:var(--card); font-size:14px; }}
  td,th {{ padding:7px 8px; border-bottom:1px solid var(--borda); text-align:left; }}
  th {{ background:#2e0b12; color:#fff; }}
  a {{ color:#7a1f2b; font-weight:700; }}
  .rodape {{ color:var(--suave); font-size:12px; margin-top:16px; }}
</style></head><body>
<header><div><h1>Monitor de Rede e Energia</h1><small>{escape(monitor.geral['cliente'])}</small></div>{resumo}</header>
<main>
  <div class="grade">{''.join(cartao(i) for i in itens)}</div>
  <h2>Últimas ocorrências</h2>
  <table><tr><th>Equipamento</th><th>Início</th><th>Fim</th><th>Duração</th><th>Detalhe</th></tr>{linhas_ev}</table>
  <p class="rodape">Atualiza sozinho a cada 20 s · última atualização {agora[11:]} ·
  <a href="/relatorio?mes={mes}">relatório do mês</a> · <a href="/api/status">API</a></p>
</main></body></html>"""


def iniciar_painel(monitor, porta: int):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):  # silencia o log de cada acesso
            pass

        def _responder(self, corpo: str, tipo="text/html; charset=utf-8", status=200):
            dados = corpo.encode("utf-8")
            self.send_response(status)
            self.send_header("Content-Type", tipo)
            self.send_header("Content-Length", str(len(dados)))
            self.end_headers()
            self.wfile.write(dados)

        def do_GET(self):
            url = urlparse(self.path)
            try:
                if url.path == "/":
                    self._responder(pagina_status(monitor))
                elif url.path == "/api/status":
                    self._responder(json.dumps({"cliente": monitor.geral["cliente"], "alvos": monitor.status()},
                                               ensure_ascii=False, indent=2), "application/json; charset=utf-8")
                elif url.path == "/relatorio":
                    mes = parse_qs(url.query).get("mes", [datetime.now().strftime("%Y-%m")])[0]
                    ano, m = (int(x) for x in mes.split("-"))
                    dados = relatorio.calcular(monitor.banco, monitor.alvos, ano, m, datetime.now().replace(microsecond=0))
                    self._responder(relatorio.html(monitor.geral["cliente"], monitor.geral["responsavel"], dados, ano, m))
                elif url.path == "/saude":
                    self._responder("ok", "text/plain")
                else:
                    self._responder("Não encontrado", "text/plain; charset=utf-8", 404)
            except Exception as erro:
                self._responder(f"Erro: {escape(str(erro))}", "text/plain; charset=utf-8", 500)

    servidor = ThreadingHTTPServer(("0.0.0.0", porta), Handler)
    threading.Thread(target=servidor.serve_forever, daemon=True).start()
    return servidor
