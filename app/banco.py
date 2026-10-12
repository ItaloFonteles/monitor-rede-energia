"""Histórico em SQLite: cada verificação (medicoes) e cada queda (eventos)."""
import sqlite3
import threading

ESQUEMA = """
CREATE TABLE IF NOT EXISTS medicoes (
  ts          TEXT NOT NULL,      -- 'AAAA-MM-DD HH:MM:SS' (horário local)
  alvo        TEXT NOT NULL,
  ok          INTEGER NOT NULL,
  latencia_ms REAL
);
CREATE INDEX IF NOT EXISTS ix_medicoes_alvo_ts ON medicoes (alvo, ts);

CREATE TABLE IF NOT EXISTS eventos (
  id         INTEGER PRIMARY KEY,
  alvo       TEXT NOT NULL,
  categoria  TEXT NOT NULL,
  inicio     TEXT NOT NULL,
  fim        TEXT,                -- NULL = ainda fora do ar
  detalhe    TEXT
);
CREATE INDEX IF NOT EXISTS ix_eventos_alvo ON eventos (alvo, inicio);

CREATE TABLE IF NOT EXISTS meta (chave TEXT PRIMARY KEY, valor TEXT);
"""


class Banco:
    def __init__(self, caminho: str):
        self.con = sqlite3.connect(caminho, check_same_thread=False)
        self.con.row_factory = sqlite3.Row
        self.trava = threading.Lock()
        with self.trava:
            self.con.executescript(ESQUEMA)

    def _exec(self, sql, params=()):
        with self.trava:
            cur = self.con.execute(sql, params)
            self.con.commit()
            return cur

    def _consulta(self, sql, params=()):
        with self.trava:
            return [dict(r) for r in self.con.execute(sql, params).fetchall()]

    # --- gravação ---------------------------------------------------------
    def medicao(self, ts, alvo, ok, latencia_ms):
        self._exec("INSERT INTO medicoes VALUES (?, ?, ?, ?)", (ts, alvo, int(ok), latencia_ms))

    def abrir_evento(self, alvo, categoria, inicio, detalhe):
        self._exec("INSERT INTO eventos (alvo, categoria, inicio, detalhe) VALUES (?, ?, ?, ?)",
                   (alvo, categoria, inicio, detalhe))

    def fechar_evento(self, alvo, fim):
        self._exec("UPDATE eventos SET fim = ? WHERE alvo = ? AND fim IS NULL", (fim, alvo))

    def limpar_antigos(self, antes_de):
        self._exec("DELETE FROM medicoes WHERE ts < ?", (antes_de,))

    def meta(self, chave, valor=None):
        if valor is None:
            r = self._consulta("SELECT valor FROM meta WHERE chave = ?", (chave,))
            return r[0]["valor"] if r else None
        self._exec("INSERT INTO meta VALUES (?, ?) ON CONFLICT(chave) DO UPDATE SET valor = excluded.valor",
                   (chave, valor))

    # --- leitura ----------------------------------------------------------
    def eventos_abertos(self):
        return self._consulta("SELECT * FROM eventos WHERE fim IS NULL")

    def eventos_no_periodo(self, inicio, fim):
        """Quedas que tocam o período [inicio, fim) — inclusive as que começaram antes."""
        return self._consulta(
            "SELECT * FROM eventos WHERE inicio < ? AND (fim IS NULL OR fim > ?) ORDER BY inicio",
            (fim, inicio))

    def eventos_recentes(self, limite=15):
        return self._consulta("SELECT * FROM eventos ORDER BY inicio DESC LIMIT ?", (limite,))

    def latencia_media(self, alvo, inicio, fim):
        r = self._consulta(
            "SELECT AVG(latencia_ms) AS media, COUNT(*) AS n FROM medicoes "
            "WHERE alvo = ? AND ts >= ? AND ts < ? AND ok = 1 AND latencia_ms IS NOT NULL",
            (alvo, inicio, fim))
        return r[0]["media"] if r and r[0]["n"] else None
