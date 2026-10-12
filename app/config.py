"""Lê o config.toml (equipamentos) e as variáveis de ambiente (segredos)."""
import os
import tomllib

TIPOS = {"ping": ["host"], "tcp": ["host", "porta"], "http": ["url"], "nut": ["host"]}
CATEGORIAS = {"rede", "energia", "servico"}


def carregar(caminho: str) -> dict:
    try:
        with open(caminho, "rb") as f:
            cfg = tomllib.load(f)
    except FileNotFoundError:
        raise ValueError(f"Não achei o arquivo de configuração: {caminho} (copie o config.exemplo.toml)") from None
    except tomllib.TOMLDecodeError as erro:
        raise ValueError(f"Erro de digitação no config.toml: {erro}.\n"
                         "Dica: confira se todo texto está entre aspas \"assim\".") from None

    geral = cfg.setdefault("geral", {})
    geral.setdefault("cliente", "Cliente")
    geral.setdefault("responsavel", "Ítalo Fonteles · italofonteles.dev")
    geral.setdefault("intervalo_segundos", 60)
    geral.setdefault("falhas_para_alerta", 3)
    geral.setdefault("timeout_segundos", 3)

    erros = []
    nomes = set()
    for i, alvo in enumerate(cfg.get("alvos", []), 1):
        tipo = alvo.get("tipo")
        if "nome" not in alvo:
            erros.append(f"alvo #{i}: falta 'nome'")
        elif alvo["nome"] in nomes:
            erros.append(f"alvo #{i}: nome repetido '{alvo['nome']}'")
        nomes.add(alvo.get("nome"))
        if tipo not in TIPOS:
            erros.append(f"alvo #{i} ({alvo.get('nome')}): tipo '{tipo}' inválido (use {', '.join(TIPOS)})")
            continue
        for campo in TIPOS[tipo]:
            if campo not in alvo:
                erros.append(f"alvo #{i} ({alvo.get('nome')}): falta '{campo}'")
        alvo.setdefault("categoria", "energia" if tipo == "nut" else "rede")
        if alvo["categoria"] not in CATEGORIAS:
            erros.append(f"alvo #{i} ({alvo.get('nome')}): categoria deve ser {', '.join(sorted(CATEGORIAS))}")
    if not cfg.get("alvos"):
        erros.append("nenhum equipamento em [[alvos]]")
    if erros:
        raise ValueError("Erro no config.toml:\n- " + "\n- ".join(erros))

    cfg["segredos"] = {
        "telegram_token": os.getenv("TELEGRAM_TOKEN", ""),
        "telegram_chat_id": os.getenv("TELEGRAM_CHAT_ID", ""),
        "webhook_url": os.getenv("WEBHOOK_URL", ""),
        "heartbeat_url": os.getenv("HEARTBEAT_URL", ""),
        "modo_teste": os.getenv("MODO_TESTE", "true").lower() == "true",
    }
    return cfg
