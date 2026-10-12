"""Cálculo de disponibilidade e relatório mensal em HTML (pronto para imprimir/enviar)."""
from datetime import datetime
from html import escape

from .estado import formatar_segundos

MESES = ["janeiro", "fevereiro", "março", "abril", "maio", "junho", "julho",
         "agosto", "setembro", "outubro", "novembro", "dezembro"]
FMT = "%Y-%m-%d %H:%M:%S"


def limites_do_mes(ano: int, mes: int):
    inicio = datetime(ano, mes, 1)
    fim = datetime(ano + (mes == 12), mes % 12 + 1, 1)
    return inicio, fim


def segundos_fora(eventos, inicio: datetime, fim: datetime) -> float:
    """Soma o tempo fora do ar dentro do período (cortando o que passa das bordas)."""
    total = 0.0
    for ev in eventos:
        ini = max(datetime.strptime(ev["inicio"], FMT), inicio)
        fe = min(datetime.strptime(ev["fim"], FMT) if ev["fim"] else fim, fim)
        if fe > ini:
            total += (fe - ini).total_seconds()
    return total


def calcular(banco, alvos, ano, mes, agora: datetime):
    """Resumo por equipamento para o mês. Se o mês ainda não acabou, conta até agora."""
    inicio, fim = limites_do_mes(ano, mes)
    fim_efetivo = min(fim, agora)
    duracao = max((fim_efetivo - inicio).total_seconds(), 1)
    eventos = banco.eventos_no_periodo(inicio.strftime(FMT), fim_efetivo.strftime(FMT))

    linhas = []
    for alvo in alvos:
        evs = [e for e in eventos if e["alvo"] == alvo["nome"]]
        fora = segundos_fora(evs, inicio, fim_efetivo)
        maior = max((segundos_fora([e], inicio, fim_efetivo) for e in evs), default=0)
        linhas.append({
            "nome": alvo["nome"],
            "categoria": alvo.get("categoria", "rede"),
            "disponibilidade": 100 * (1 - fora / duracao),
            "quedas": len(evs),
            "tempo_fora": fora,
            "maior_queda": maior,
            "latencia": banco.latencia_media(alvo["nome"], inicio.strftime(FMT), fim_efetivo.strftime(FMT)),
        })
    return {"inicio": inicio, "fim": fim_efetivo, "linhas": linhas, "eventos": eventos}


def pct(valor: float) -> str:
    """99.987 → "99,99%" (formato brasileiro)."""
    return f"{valor:.2f}%".replace(".", ",")


def cor(disp: float) -> str:
    return "#1f7a4d" if disp >= 99.9 else "#b7791f" if disp >= 99 else "#b42318"


def resumo_texto(cliente, dados, ano, mes) -> str:
    """Resumo curto para mandar no Telegram/WhatsApp junto com o arquivo."""
    linhas = [f"📊 Relatório de {MESES[mes - 1]}/{ano} · {cliente}", ""]
    for l in dados["linhas"]:
        icone = "🟢" if l["disponibilidade"] >= 99.9 else "🟡" if l["disponibilidade"] >= 99 else "🔴"
        quedas = f"{l['quedas']} queda(s), {formatar_segundos(l['tempo_fora'])} fora" if l["quedas"] else "sem quedas"
        linhas.append(f"{icone} {l['nome']}: {pct(l['disponibilidade'])} ({quedas})")
    return "\n".join(linhas)


def html(cliente, responsavel, dados, ano, mes) -> str:
    linhas = dados["linhas"]
    media = sum(l["disponibilidade"] for l in linhas) / len(linhas) if linhas else 100
    total_quedas = sum(l["quedas"] for l in linhas)
    energia = [e for e in dados["eventos"] if e["categoria"] == "energia"]

    def linha_alvo(l):
        fora = formatar_segundos(l["tempo_fora"]) if l["quedas"] else "—"
        maior = formatar_segundos(l["maior_queda"]) if l["quedas"] else "—"
        latencia = f"{l['latencia']:.0f} ms" if l["latencia"] else "—"
        return (f"<tr><td>{escape(l['nome'])}</td>"
                f"<td style='color:{cor(l['disponibilidade'])};font-weight:700'>{pct(l['disponibilidade'])}</td>"
                f"<td>{l['quedas']}</td><td>{fora}</td><td>{maior}</td><td>{latencia}</td></tr>")

    tabela = "".join(linha_alvo(l) for l in linhas)

    def linha_evento(e):
        ini = datetime.strptime(e["inicio"], FMT)
        fim = datetime.strptime(e["fim"], FMT) if e["fim"] else None
        dur = formatar_segundos(((fim or dados["fim"]) - ini).total_seconds())
        return (f"<tr><td>{escape(e['alvo'])}</td><td>{ini:%d/%m %H:%M}</td>"
                f"<td>{f'{fim:%d/%m %H:%M}' if fim else 'ainda fora'}</td><td>{dur}</td>"
                f"<td>{escape(e['detalhe'] or '')}</td></tr>")

    incidentes = "".join(linha_evento(e) for e in dados["eventos"]) or \
        "<tr><td colspan='5' class='vazio'>Nenhuma queda registrada no período. 🎉</td></tr>"

    periodo = f"{dados['inicio']:%d/%m/%Y} a {dados['fim']:%d/%m/%Y %H:%M}"
    return f"""<!DOCTYPE html>
<html lang="pt-br"><head><meta charset="UTF-8">
<title>Relatório de disponibilidade · {escape(cliente)} · {MESES[mes - 1]}/{ano}</title>
<style>
  @page {{ size: A4; margin: 14mm; }}
  body {{ font-family: "Segoe UI", Arial, sans-serif; color: #24191a; margin: 0 auto; max-width: 860px; padding: 24px; }}
  header {{ display: flex; justify-content: space-between; align-items: flex-end; border-bottom: 3px solid #c9a24b; padding-bottom: 12px; }}
  h1 {{ margin: 0; font-size: 24px; color: #7a1f2b; }}
  .sub {{ color: #6b5d5f; margin-top: 4px; }}
  .cards {{ display: grid; grid-template-columns: repeat(3, 1fr); gap: 12px; margin: 20px 0; }}
  .card {{ background: #f6efe2; border-radius: 10px; padding: 14px 16px; }}
  .card b {{ display: block; font-size: 26px; }}
  .card span {{ color: #6b5d5f; font-size: 13px; }}
  h2 {{ font-size: 16px; color: #7a1f2b; text-transform: uppercase; letter-spacing: 1px; margin: 26px 0 8px; }}
  table {{ width: 100%; border-collapse: collapse; font-size: 13.5px; }}
  th {{ text-align: left; background: #2e0b12; color: #fff; padding: 8px; font-weight: 600; }}
  td {{ padding: 7px 8px; border-bottom: 1px solid #e3d3b4; vertical-align: top; }}
  .vazio {{ text-align: center; color: #6b5d5f; padding: 16px; }}
  .nota {{ font-size: 12.5px; color: #6b5d5f; margin-top: 10px; }}
  footer {{ margin-top: 30px; padding-top: 10px; border-top: 1px solid #e3d3b4; font-size: 12px; color: #6b5d5f; display: flex; justify-content: space-between; }}
</style></head><body>
<header>
  <div><h1>Relatório de disponibilidade</h1>
  <div class="sub">{escape(cliente)} · {MESES[mes - 1].capitalize()} de {ano} · período: {periodo}</div></div>
  <div class="sub">Preparado por<br><b>{escape(responsavel)}</b></div>
</header>

<div class="cards">
  <div class="card"><b style="color:{cor(media)}">{pct(media)}</b><span>disponibilidade média</span></div>
  <div class="card"><b>{total_quedas}</b><span>quedas registradas</span></div>
  <div class="card"><b>{len(energia)}</b><span>faltas de energia (nobreak)</span></div>
</div>

<h2>Equipamentos e serviços</h2>
<table><tr><th>Equipamento</th><th>Disponível</th><th>Quedas</th><th>Tempo fora</th><th>Maior queda</th><th>Resposta média</th></tr>
{tabela}</table>
<p class="nota">Disponibilidade = tempo no ar ÷ tempo total do período. 99,9% equivale a cerca de 43 minutos fora do ar em um mês.</p>

<h2>Ocorrências</h2>
<table><tr><th>Equipamento</th><th>Início</th><th>Fim</th><th>Duração</th><th>Detalhe</th></tr>
{incidentes}</table>

<footer><span>Gerado automaticamente pelo Monitor de Rede e Energia</span><span>{escape(responsavel)}</span></footer>
</body></html>"""
