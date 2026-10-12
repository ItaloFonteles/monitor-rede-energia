"""Testes do monitor. Rodar com:
   docker run --rm -v "${PWD}:/m" -w /m python:3.12-slim python -m unittest -v
"""
import os
import tempfile
import unittest
from datetime import datetime

from app import checks, relatorio
from app.alertas import Alertas
from app.banco import Banco
from app.estado import EstadoAlvo, atualizar, duracao_legivel, formatar_segundos
from app.main import Monitor


class TestEstado(unittest.TestCase):
    def test_so_avisa_depois_de_n_falhas(self):
        e = EstadoAlvo()
        self.assertIsNone(atualizar(e, True, "2026-10-12 08:00:00", "ok", 3))
        self.assertIsNone(atualizar(e, False, "2026-10-12 08:01:00", "sem resposta", 3))
        self.assertIsNone(atualizar(e, False, "2026-10-12 08:02:00", "sem resposta", 3))
        ev = atualizar(e, False, "2026-10-12 08:03:00", "sem resposta", 3)
        self.assertEqual(ev, ("caiu", "2026-10-12 08:01:00", "sem resposta"))  # início = 1ª falha
        self.assertIsNone(atualizar(e, False, "2026-10-12 08:04:00", "sem resposta", 3))  # não repete
        ev = atualizar(e, True, "2026-10-12 08:31:00", "ok", 3)
        self.assertEqual(ev, ("voltou", "2026-10-12 08:01:00", "2026-10-12 08:31:00"))

    def test_falha_isolada_nao_gera_alerta(self):
        e = EstadoAlvo()
        atualizar(e, True, "2026-10-12 08:00:00", "ok", 3)
        atualizar(e, False, "2026-10-12 08:01:00", "x", 3)
        self.assertIsNone(atualizar(e, True, "2026-10-12 08:02:00", "ok", 3))
        self.assertEqual(e.falhas, 0)

    def test_duracoes(self):
        self.assertEqual(formatar_segundos(30), "menos de 1 min")
        self.assertEqual(formatar_segundos(45 * 60), "45 min")
        self.assertEqual(formatar_segundos(75 * 60), "1 h 15 min")
        self.assertEqual(formatar_segundos(26 * 3600), "1 d 2 h")
        self.assertEqual(duracao_legivel("2026-10-12 08:00:00", "2026-10-12 10:00:00"), "2 h")


class TestChecks(unittest.TestCase):
    def test_ler_tempo_do_ping(self):
        saida = "64 bytes from 1.1.1.1: icmp_seq=1 ttl=57 time=12.4 ms"
        self.assertEqual(checks.interpretar_ping(saida), 12.4)

    def test_nobreak(self):
        texto = ('BEGIN LIST VAR ups\nVAR ups ups.status "OB"\nVAR ups battery.charge "80"\n'
                 'VAR ups battery.runtime "1200"\nEND LIST VAR ups\n')
        r = checks.descrever_nobreak(checks.interpretar_nut(texto))
        self.assertFalse(r.ok)
        self.assertIn("na bateria", r.detalhe)
        self.assertIn("80%", r.detalhe)
        self.assertIn("~20 min", r.detalhe)
        self.assertTrue(checks.descrever_nobreak({"ups.status": "OL CHRG"}).ok)
        self.assertIn("FRACA", checks.descrever_nobreak({"ups.status": "OB LB"}).detalhe)

    def test_tipo_invalido_nao_explode(self):
        self.assertFalse(checks.checar({"tipo": "xyz"}).ok)

    def test_porta_fechada(self):
        r = checks.tcp("127.0.0.1", 1, 1)
        self.assertFalse(r.ok)


class TestRelatorio(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp()
        self.banco = Banco(os.path.join(self.tmp, "t.db"))

    def test_disponibilidade_corta_nas_bordas_do_mes(self):
        # queda de 30/09 23:00 até 01/10 01:00 → só 1 h conta em outubro
        self.banco.abrir_evento("Internet", "rede", "2026-09-30 23:00:00", "x")
        self.banco.fechar_evento("Internet", "2026-10-01 01:00:00")
        # queda de 2 h no meio do mês
        self.banco.abrir_evento("Internet", "rede", "2026-10-10 10:00:00", "x")
        self.banco.fechar_evento("Internet", "2026-10-10 12:00:00")
        alvos = [{"nome": "Internet", "categoria": "rede"}, {"nome": "Roteador", "categoria": "rede"}]
        dados = relatorio.calcular(self.banco, alvos, 2026, 10, datetime(2026, 11, 5))
        internet, roteador = dados["linhas"]
        self.assertEqual(internet["quedas"], 2)
        self.assertEqual(internet["tempo_fora"], 3 * 3600)
        self.assertEqual(internet["maior_queda"], 2 * 3600)
        self.assertAlmostEqual(internet["disponibilidade"], 100 * (1 - 3 / (31 * 24)), places=4)
        self.assertEqual(roteador["disponibilidade"], 100)

        pagina = relatorio.html("Clínica Teste", "Ítalo", dados, 2026, 10)
        self.assertIn("Clínica Teste", pagina)
        self.assertIn("outubro", pagina.lower())
        self.assertIn("Internet", relatorio.resumo_texto("Clínica Teste", dados, 2026, 10))

    def test_queda_ainda_aberta_conta_ate_agora(self):
        self.banco.abrir_evento("Câmera", "rede", "2026-10-12 08:00:00", "x")
        dados = relatorio.calcular(self.banco, [{"nome": "Câmera"}], 2026, 10, datetime(2026, 10, 12, 9, 0))
        self.assertEqual(dados["linhas"][0]["tempo_fora"], 3600)


class TestConfig(unittest.TestCase):
    def test_aspas_faltando_vira_mensagem_clara(self):
        from app.config import carregar
        caminho = os.path.join(tempfile.mkdtemp(), "c.toml")
        with open(caminho, "w", encoding="utf-8") as f:
            f.write('[[alvos]]\nnome = "Celular"\ntipo = "ping"\nhost = "192.168.1.15\n')
        with self.assertRaises(ValueError) as ctx:
            carregar(caminho)
        self.assertIn("aspas", str(ctx.exception))


class TestMonitor(unittest.TestCase):
    def test_ciclo_gera_alertas_e_grava_eventos(self):
        tmp = tempfile.mkdtemp()
        banco = Banco(os.path.join(tmp, "m.db"))
        mensagens = []
        alertas = Alertas(modo_teste=True, log=mensagens.append)
        cfg = {"geral": {"cliente": "Teste", "responsavel": "Í", "intervalo_segundos": 1,
                         "falhas_para_alerta": 2, "timeout_segundos": 1},
               "alvos": [{"nome": "Porta fechada", "tipo": "tcp", "host": "127.0.0.1", "porta": 1, "categoria": "rede"}],
               "segredos": {"heartbeat_url": ""}}
        mon = Monitor(cfg, banco, alertas)

        class Exec:
            def map(self, f, itens):
                return map(f, itens)

        mon.ciclo(Exec())
        mon.ciclo(Exec())
        self.assertTrue(any("🔴 Teste: Porta fechada está fora do ar" in m for m in mensagens))
        self.assertEqual(len(banco.eventos_abertos()), 1)

        # monitor reiniciado: a queda aberta continua sendo "fora do ar"
        mon2 = Monitor(cfg, banco, alertas)
        self.assertFalse(mon2.estados["Porta fechada"].ok)


if __name__ == "__main__":
    unittest.main()
