"""Explicit channel-account partitions of the shared SQLite ledger."""
from dataclasses import asdict
from decimal import Decimal
import json
import re

DEFAULT_CHANNEL_ACCOUNT = "futu-cn-default"


class ChannelAccountStore:
    @property
    def _atomic_decision_depth(self):
        return self._transaction_state[0]

    @_atomic_decision_depth.setter
    def _atomic_decision_depth(self, value):
        if not hasattr(self, "_transaction_state"):
            self._transaction_state = [value]
        else:
            self._transaction_state[0] = value

    def _initialize_channel_accounts(self):
        self._connection.execute("CREATE TABLE IF NOT EXISTS equity_strategy_state (account_id TEXT PRIMARY KEY,payload TEXT NOT NULL)")
        self._connection.execute("CREATE TABLE IF NOT EXISTS channel_accounts ("
            "channel_account_id TEXT PRIMARY KEY,channel_id TEXT NOT NULL,market TEXT NOT NULL,"
            "currency TEXT NOT NULL,broker_account_id INTEGER,config_json TEXT)")
        self._connection.execute("INSERT OR IGNORE INTO channel_accounts VALUES(?,?,?,?,NULL,NULL)",
            (DEFAULT_CHANNEL_ACCOUNT, "futu_simulate_cn", "CN", "CNY"))
        for table in ("virtual_accounts", "events", "snapshots"):
            self._ensure_column(table, "channel_account_id", f"TEXT NOT NULL DEFAULT '{DEFAULT_CHANNEL_ACCOUNT}'")
        self._connection.execute("CREATE INDEX IF NOT EXISTS virtual_accounts_channel_scope ON virtual_accounts(channel_account_id)")
        self._connection.execute("CREATE INDEX IF NOT EXISTS events_channel_scope ON events(channel_account_id,id)")

    @property
    def channel_account_id(self):
        return getattr(self, "_channel_account_id", None)

    @property
    def execution_channel_id(self):
        return getattr(self, "_execution_channel_id", "futu_simulate_cn")

    def register_channel_account(self, config, *, capital: Decimal):
        from .channel import ChannelAccountConfig
        if type(config) is not ChannelAccountConfig:
            raise TypeError("channel registration requires ChannelAccountConfig")
        if self.channel_account_id is not None and self.channel_account_id != config.channel_account_id:
            raise ValueError("a scoped store cannot register another channel account")
        if type(capital) is not Decimal or not capital.is_finite() or capital <= 0:
            raise ValueError("channel capital must be a positive Decimal")
        encoded = json.dumps(asdict(config), sort_keys=True)
        with self._lock, self._write_context(False):
            old = self._connection.execute("SELECT * FROM channel_accounts WHERE channel_account_id=?", (config.channel_account_id,)).fetchone()
            if old is not None and old['config_json'] is not None:
                if old['config_json'] != encoded:
                    raise ValueError("registered external account binding is immutable")
                scoped = self.scope(config.channel_account_id)
                if scoped.capital_pool_balance().registered_capital != capital:
                    raise ValueError("registered capital requires an explicit capital transfer")
                return scoped
            duplicate = self._connection.execute("SELECT channel_account_id FROM channel_accounts WHERE channel_id=? AND broker_account_id=?",
                (config.channel_id, config.broker_account_id)).fetchone()
            if duplicate is not None:
                raise ValueError("external channel account is already registered")
            if old is not None and (old['channel_id'] != config.channel_id or old['currency'] != config.currency):
                raise ValueError("legacy channel account identity cannot change")
            if old is not None and self.scope(DEFAULT_CHANNEL_ACCOUNT).capital_pool_balance().registered_capital != capital:
                raise ValueError("legacy capital cannot change while binding the external account")
            self._connection.execute("INSERT INTO channel_accounts VALUES(?,?,?,?,?,?) ON CONFLICT(channel_account_id) DO UPDATE SET broker_account_id=excluded.broker_account_id,config_json=excluded.config_json",
                (config.channel_account_id, config.channel_id, config.market, config.currency, config.broker_account_id, encoded))
            scoped = self.scope(config.channel_account_id)
            scoped.set_setting("futu_capital_pool", str(capital))
        return scoped

    def channel_accounts(self):
        with self._lock:
            return [dict(r) for r in self._connection.execute("SELECT * FROM channel_accounts ORDER BY channel_account_id")]

    def scope(self, channel_account_id: str):
        with self._lock:
            row = self._connection.execute("SELECT * FROM channel_accounts WHERE channel_account_id=?", (channel_account_id,)).fetchone()
        if row is None:
            raise KeyError(channel_account_id)
        if self.channel_account_id is not None and self.channel_account_id != channel_account_id:
            raise ValueError("a scoped store cannot cross channel accounts")
        scoped = type(self).__new__(type(self))
        scoped.__dict__.update(self.__dict__)
        scoped._channel_account_id = channel_account_id
        scoped._execution_channel_id = row['channel_id']
        scoped._scope_currency = row['currency']
        scoped._scope_market = row['market']
        scoped._scope_parent = self
        return scoped

    def _setting_key(self, key):
        scope = self.channel_account_id
        if scope is not None and str(key).startswith("channel:"):
            raise ValueError("channel settings prefix is reserved for the root store")
        return key if scope in (None, DEFAULT_CHANNEL_ACCOUNT) else f"channel:{scope}:{key}"

    def _scope_clause(self, column="account_id"):
        scope = self.channel_account_id
        if scope is None:
            return "1=1", ()
        if re.fullmatch(r"[a-z_]+(?:\.[a-z_]+)?", column) is None:
            raise ValueError("invalid scope column")
        return f"{column} IN (SELECT account_id FROM virtual_accounts WHERE channel_account_id=?)", (scope,)

    def _check_owned(self, kind, identity):
        if self.channel_account_id is None or identity is None:
            return
        table, key = {"account": ("virtual_accounts", "account_id"), "intent": ("intents", "intent_id"),
                      "order": ("orders", "channel_order_id"), "fill": ("fills", "fill_id")}[kind]
        with self._lock:
            row = self._connection.execute(f"SELECT account_id FROM {table} WHERE {key}=?", (identity,)).fetchone()
            if row is not None:
                owner = self._connection.execute("SELECT channel_account_id FROM virtual_accounts WHERE account_id=?", (row[0],)).fetchone()
                if owner is None or owner[0] != self.channel_account_id:
                    raise ValueError("resource belongs to another channel account")

    def _scoped_rows(self, rows):
        if self.channel_account_id is None:
            return rows
        clause, values = self._scope_clause()
        owners = {r[0] for r in self._connection.execute(f"SELECT account_id FROM virtual_accounts WHERE {clause}", values)}
        return [r for r in rows if r['account_id'] in owners]
