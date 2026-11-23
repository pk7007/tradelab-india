#!/usr/bin/env python3
"""Local-first TradeLab India dashboard with a server-side Kite Connect adapter."""

from __future__ import annotations

import hashlib
import hmac
import http.server
import json
import math
import os
import secrets
import socket
import sqlite3
import threading
import time
import subprocess
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
PAPER_BUILD_FILES = ("app.py", "paper.py", "paper_worker.py", "worker_runtime.py",
                     "market_contract.py", "market_data.py", "intraday_contract.py", "auto_selector.py",
                     "intraday_session.py", "session_evidence.py", "desk_coordinator.py", "entry_review.py",
                     "strategy_contract.py", "research.py", "research_context.py",
                     "integrated_news.py", "syndication.py", "syndication_transport.py",
                     "trade_workflow.py", "agent_handlers.py", "agent_catalog.py", "news_agent.py", "dashboard_news.py", "announcements.py", "nse_filings.py")
PAPER_BUILD = hashlib.sha256(b"".join(hashlib.sha256((ROOT / name).read_bytes()).digest()
                                     for name in PAPER_BUILD_FILES)).hexdigest()
KITE_API = "https://api.kite.trade"
SESSIONS: dict[str, dict[str, Any]] = {}
LOCK = threading.RLock()
SESSION_IDLE_SECONDS = 1800
MAX_SESSIONS = 128


def load_dotenv() -> None:
    """Load simple KEY=VALUE pairs without overriding the process environment."""
    env_file = ROOT / ".env"
    if not env_file.is_file():
        return
    for raw in env_file.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("\"'"))


load_dotenv()
API_KEY = os.environ.get("KITE_API_KEY", "").strip()
API_SECRET = os.environ.get("KITE_API_SECRET", "").strip()
REDIRECT_URL = os.environ.get("KITE_REDIRECT_URL", "http://127.0.0.1:8765/auth/kite/callback").strip()
LIVE_ORDERS_ENABLED = os.environ.get("TRADELAB_ENABLE_LIVE_ORDERS", "false").strip().lower() == "true"
LIVE_EXECUTION_READY = False  # Shared broker cash/inventory and exit reconciliation are not integrated.
LIVE_READINESS_REASON = "Live execution is blocked pending shared broker cash/inventory, approved risk limits, and exit reconciliation integration."
from trader_suite import TOOLS, dispatch
from portal import Portal


from dashboard_news import DashboardNews
from integrated_news import IntegratedNews, LicensedNews
import news_assessor
NEWS_ASSESSOR = news_assessor.from_environment(os.environ, Path(os.environ.get('TRADELAB_NEWS_AI_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'news-assessments.sqlite'))))
NEWS_AGENT = IntegratedNews(
    DashboardNews(Path(os.environ.get('TRADELAB_NEWS_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'news-agent.sqlite')))),
    LicensedNews(os.environ, Path(os.environ.get('TRADELAB_SYNDICATION_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'licensed-news.sqlite')))),
    assessor=NEWS_ASSESSOR)
# Read-only source of current items; the assessor thread only starts when explicitly enabled.
NEWS_ASSESSOR.source = lambda: NEWS_AGENT.rss.status(getattr(MARKET, 'master', []))['items']
PORTAL = Portal(Path(os.environ.get('TRADELAB_PORTAL_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'portal.sqlite'))))
from paper import PaperEngine
PAPER = PaperEngine(Path(os.environ.get('TRADELAB_PAPER_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'paper.sqlite'))))
from execution_journal import ExecutionJournal
from experiment_registry import ExperimentRegistry
EXPERIMENTS = ExperimentRegistry(Path(os.environ.get('TRADELAB_RESEARCH_DB', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'research.sqlite'))))
EXECUTION = ExecutionJournal(Path(os.environ.get("TRADELAB_EXECUTION_DB", str(Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data" / "private"))) / "TradeLabIndia" / "execution.sqlite"))))
from automation import Coordinator
AUTOMATION = Coordinator(Path(os.environ.get("TRADELAB_AUTOMATION_DB", str(Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data" / "private"))) / "TradeLabIndia" / "automation.sqlite"))))
from market_data import MarketData, synthetic_research
DATA_ROOT = Path(os.environ.get('TRADELAB_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'market-data')))
MARKET = MarketData(API_KEY, DATA_ROOT)
from worker_runtime import WorkerRuntime
PAPER_WORKER = WorkerRuntime(PAPER, MARKET, NEWS_AGENT)
from auto_selector import AutoSelector, rank_candidates
from intraday_session import session_snapshot
AUTO_SELECTOR = AutoSelector(PAPER, MARKET, announcements=NEWS_AGENT)


def automatic_selection_status():
    result = AUTO_SELECTOR.status()
    calendar = json.loads((ROOT / 'docs/infy-paper-calendar-2026-11-20.json').read_text())
    calendar.pop('symbol', None)
    calendar.update(version='nse-eq-conservative-1515-window-20261120-v1',
                    scope='Conservative regular cash-equity research window ending 15:15. Auctions excluded.')
    result['calendar'] = calendar
    return result


from agent_service import AgentService
AGENTS = AgentService(PORTAL.path.parent / 'agents.sqlite')
from desk_coordinator import DeskCoordinator
from session_evidence import SessionEvidence
SESSION_EVIDENCE = SessionEvidence(PAPER)
DESK = DeskCoordinator(NEWS_AGENT, MARKET, PAPER, PAPER_WORKER, AGENTS, AUTO_SELECTOR, SESSION_EVIDENCE)
from strategy_lab import StrategyLab
STRATEGY_LAB = StrategyLab(PORTAL.path.parent / 'strategy-lab.sqlite', paper_engine=PAPER)
from operations import Operations
from operational_alerts import OperationalAlerts
ALERTS = OperationalAlerts(PORTAL.path.parent / 'operational-alerts.sqlite')
OPERATIONS = Operations([PORTAL.path, PAPER.path, EXPERIMENTS.path, EXECUTION.path, AGENTS.path, STRATEGY_LAB.path, ALERTS.path], PORTAL.path.parent,
                        paper_engine=PAPER, alerts=ALERTS)


class KiteError(Exception):
    pass

class KiteSessionExpired(KiteError):
    pass


def kite_request(path: str, token: str, *, method: str = "GET", form: dict[str, Any] | None = None) -> dict[str, Any]:
    from broker_transport import fetch_json
    data = urllib.parse.urlencode(form).encode("utf-8") if form is not None else None
    headers = {
        "Authorization": f"token {API_KEY}:{token}",
        "X-Kite-Version": "3",
        "Accept": "application/json",
        "User-Agent": "TradeLabIndia/0.1 (local single-user client)",
    }
    if data is not None:
        headers["Content-Type"] = "application/x-www-form-urlencoded"
    request = urllib.request.Request(f"{KITE_API}{path}", data=data, headers=headers, method=method)
    try:
        payload = fetch_json(request)
    except urllib.error.HTTPError as exc:
        # Provider bodies may echo account details, request URLs, or credentials.
        if exc.code == 403:
            raise KiteSessionExpired("Broker session expired. Reconnect Zerodha.") from None
        raise KiteError(f"Broker request failed with HTTP {exc.code}. Check connection and broker status.") from None
    except (urllib.error.URLError, TimeoutError, ValueError, UnicodeError) as exc:
        raise KiteError(f"Could not reach Kite Connect: {type(exc).__name__}") from None
    if not isinstance(payload, dict) or payload.get("status") != "success":
        raise KiteError("Broker returned an unsuccessful or invalid response. Check the broker account directly.")
    return payload


def validate_order(values: dict[str, Any]) -> dict[str, Any]:
    exchanges = {"NSE", "BSE", "NFO", "CDS", "BCD", "MCX"}
    products = {"CNC", "MIS", "NRML"}
    order_types = {"MARKET", "LIMIT", "SL", "SL-M"}
    transaction_types = {"BUY", "SELL"}
    validity_types = {"DAY", "IOC"}
    exchange = str(values.get("exchange", "")).upper()
    symbol = str(values.get("tradingsymbol", "")).strip().upper()
    transaction_type = str(values.get("transaction_type", "")).upper()
    product = str(values.get("product", "")).upper()
    order_type = str(values.get("order_type", "")).upper()
    validity = str(values.get("validity", "DAY")).upper()
    if exchange not in exchanges:
        raise ValueError("Choose a supported exchange.")
    if not symbol or len(symbol) > 40 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789&-_" for char in symbol):
        raise ValueError("Enter a valid trading symbol using letters, numbers, &, hyphen, or underscore.")
    if transaction_type not in transaction_types or product not in products or order_type not in order_types or validity not in validity_types:
        raise ValueError("One or more order selections are invalid.")
    try:
        raw_quantity = values.get("quantity", 0)
        if isinstance(raw_quantity, bool) or not str(raw_quantity).isdigit():
            raise ValueError("Quantity must be a positive whole number.")
        quantity = int(raw_quantity)
    except (TypeError, ValueError):
        raise ValueError("Quantity must be a positive whole number.") from None
    if quantity < 1 or quantity > 1_000_000:
        raise ValueError("Quantity must be between 1 and 1,000,000.")
    try:
        price = float(values.get("price") or 0)
        trigger_price = float(values.get("trigger_price") or 0)
    except (TypeError, ValueError):
        raise ValueError("Prices must be valid numbers.") from None
    if not math.isfinite(price) or not math.isfinite(trigger_price) or price < 0 or trigger_price < 0 or price > 10_000_000 or trigger_price > 10_000_000:
        raise ValueError("Price is outside the accepted range.")
    if order_type in {"LIMIT", "SL"} and price <= 0:
        raise ValueError("This order type requires a limit price greater than zero.")
    if order_type in {"SL", "SL-M"} and trigger_price <= 0:
        raise ValueError("Stop-loss orders require a trigger price greater than zero.")
    if order_type == "SL" and ((transaction_type == "BUY" and price < trigger_price) or (transaction_type == "SELL" and price > trigger_price)):
        raise ValueError("BUY stop-limit price must be at least the trigger; SELL limit must be at most the trigger.")
    order: dict[str, Any] = {
        "variety": "regular",
        "exchange": exchange,
        "tradingsymbol": symbol,
        "transaction_type": transaction_type,
        "quantity": quantity,
        "product": product,
        "order_type": order_type,
        "validity": validity,
    }
    if order_type != "MARKET":
        order["price"] = price
    if order_type in {"SL", "SL-M"}:
        order["trigger_price"] = trigger_price
    if order_type in {"MARKET", "SL-M"}:
        order["market_protection"] = -1
    return order


class Handler(http.server.BaseHTTPRequestHandler):
    server_version = "TradeLabLocal/0.1"

    def log_message(self, _format: str, *args: Any) -> None:
        # OAuth callback URLs can contain one-time request tokens. Do not log requests.
        return

    def session(self) -> tuple[str, dict[str, Any]]:
        cookie = self.headers.get("Cookie", "")
        session_id = ""
        for part in cookie.split(";"):
            name, separator, value = part.strip().partition("=")
            if separator and name == "tradelab_session":
                session_id = value
                break
        with LOCK:
            now = time.monotonic()
            for identity, existing in list(SESSIONS.items()):
                if now - existing.get("last_seen", 0) >= SESSION_IDLE_SECONDS:
                    existing.clear()  # Revoke credentials held by in-flight references too.
                    del SESSIONS[identity]
            if session_id not in SESSIONS:
                while len(SESSIONS) >= MAX_SESSIONS:
                    oldest = min(SESSIONS, key=lambda identity: SESSIONS[identity].get("last_seen", 0))
                    SESSIONS.pop(oldest).clear()
                session_id = secrets.token_urlsafe(32)
                SESSIONS[session_id] = {"csrf": secrets.token_urlsafe(32), "submitted": set()}
            SESSIONS[session_id]["last_seen"] = now
            return session_id, SESSIONS[session_id]

    def send_bytes(self, status: int, content: bytes, content_type: str, *, extra_headers: list[tuple[str, str]] | None = None) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(content)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; img-src 'self' data:; style-src 'self'; script-src 'self'; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'")
        if extra_headers:
            for name, value in extra_headers:
                self.send_header(name, value)
        self.end_headers()
        self.wfile.write(content)

    def json_response(self, status: int, payload: dict[str, Any], *, cookie: str | None = None) -> None:
        headers = [("Set-Cookie", cookie)] if cookie else None
        self.send_bytes(status, json.dumps(payload, separators=(",", ":")).encode(), "application/json; charset=utf-8", extra_headers=headers)

    def error(self, status: int, message: str) -> None:
        self.json_response(status, {"error": message})

    def redirect(self, location: str, cookie: str | None = None) -> None:
        self.send_response(303)
        self.send_header("Location", location)
        self.send_header("Cache-Control", "no-store")
        self.send_header("Referrer-Policy", "no-referrer")
        if cookie:
            self.send_header("Set-Cookie", cookie)
        self.end_headers()

    def body_json(self) -> dict[str, Any]:
        try:
            length = int(self.headers.get("Content-Length", "0"))
        except ValueError:
            raise ValueError("Invalid request length.") from None
        if length < 1 or length > (8_000_000 if self.path.startswith("/api/trader/") else 64_000):
            raise ValueError("Request body is empty or too large.")
        try:
            value = json.loads(self.rfile.read(length).decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError):
            raise ValueError("Request must contain valid JSON.") from None
        if not isinstance(value, dict):
            raise ValueError("Request JSON must be an object.")
        return value

    def authenticated_session(self) -> tuple[str, dict[str, Any]]:
        session_id, session = self.session()
        expected_origin = f"http://{self.headers.get('Host', '')}"
        origin = self.headers.get("Origin")
        if origin and origin != expected_origin:
            raise PermissionError("Request origin was rejected.")
        supplied = self.headers.get("X-CSRF-Token", "")
        if not supplied or not hmac.compare_digest(supplied, session.get("csrf", "")):
            raise PermissionError("Session check failed. Refresh the page and try again.")
        return session_id, session

    def connected_token(self, session: dict[str, Any]) -> str:
        token = session.get("access_token")
        if not token:
            raise PermissionError("Connect your Zerodha account first.")
        return str(token)

    def valid_host(self):
        host=self.headers.get('Host','')
        allowed={f'127.0.0.1:{self.server.server_port}',f'localhost:{self.server.server_port}',f'[::1]:{self.server.server_port}'}
        if host not in allowed:
            self.error(403,'Local host header required.'); return False
        return True

    def do_GET(self) -> None:
        if not self.valid_host(): return
        parsed = urllib.parse.urlparse(self.path)
        route = parsed.path
        if route in {"/", "/index.html", "/intraday", "/long-term", "/auto-trading", "/advanced", "/trader-evaluate", "/trader-paper"} or route.removeprefix("/trader-") in TOOLS:
            session_id, session = self.session()
            template = "evaluation.html" if route == "/trader-evaluate" else ("trader.html" if route.startswith("/trader-") else "index.html")
            if route == '/trader-paper': template = 'paper.html'
            if route in {'/', '/index.html', '/intraday', '/long-term', '/auto-trading'}: template = 'portal.html'
            page = (WEB / template).read_text(encoding="utf-8").replace("__CSRF_TOKEN__", session["csrf"])
            cookie = f"tradelab_session={session_id}; HttpOnly; SameSite=Lax; Path=/"
            self.send_bytes(200, page.encode(), "text/html; charset=utf-8", extra_headers=[("Set-Cookie", cookie)])
            return
        if route == "/auth/kite/callback":
            self.kite_callback(urllib.parse.parse_qs(parsed.query))
            return
        if route in {"/workspace-tools.js", "/platform.js", "/portal.js", "/portal.css", "/app.js", "/market.js", "/automation.js", "/account.js", "/trader.js", "/trader.css", "/evaluation.js", "/evaluation.css", "/paper.js", "/styles.css"}:
            file_name = route[1:]
            mime = "text/javascript; charset=utf-8" if file_name.endswith(".js") else "text/css; charset=utf-8"
            try:
                self.send_bytes(200, (WEB / file_name).read_bytes(), mime)
            except OSError:
                self.error(404, "File not found.")
            return
        if route.startswith("/api/"):
            self.api_get(route, urllib.parse.parse_qs(parsed.query))
            return
        self.error(404, "Not found.")

    def api_get(self, route: str, query: dict[str, list[str]]) -> None:
        if route == '/api/alerts':
            self.json_response(200, ALERTS.status()); return
        if route == '/api/service-health':
            selected = AUTO_SELECTOR.status()
            sources = NEWS_AGENT.status(getattr(MARKET, 'master', [])).get('sources', [])
            self.json_response(200, dict(service='tradelab-local',
                selection={key:selected.get(key) for key in ('state','enabled')},
                sources=[{key:row.get(key) for key in ('source','status','stale')} for row in sources])); return
        if route == '/api/auto-selection':
            try:
                self.json_response(200, automatic_selection_status())
            except (sqlite3.Error, OSError):
                self.error(503, 'Automatic session status unavailable. Review exposure before retrying.')
            return
        if route == '/api/desk':
            self.json_response(200, DESK.status()); return
        if route == '/api/news-agent':
            self.json_response(200, NEWS_AGENT.status(getattr(MARKET,'master',[]))); return
        if route == '/api/announcements':
            self.json_response(200, NEWS_AGENT.status(getattr(MARKET,'master',[]),source='nse')); return
        session_id, session = self.session()
        if route == '/api/intraday-session':
            try:
                settings = PORTAL.status()['settings']
                template = (query.get('templateAccount') or [None])[0]
                if template:
                    with PAPER.db() as db:
                        settings = PAPER.load(db, template)['config']
                try:
                    news = NEWS_AGENT.status(getattr(MARKET, 'master', []))
                except Exception:
                    news = dict(status='unavailable', stale=True, sources=[])
                result = session_snapshot(PAPER, automatic_selection_status(), settings,
                    connected=bool(session.get('access_token')),
                    storage_approved=os.environ.get('KITE_DATA_STORAGE_APPROVED','false').lower() == 'true',
                    news=news, desk=DESK.status())
                self.json_response(200, result)
            except (ValueError, TypeError):
                self.error(400, 'Unknown or invalid paper assumptions account.')
            except (sqlite3.Error, OSError):
                self.error(503, 'Session ledger unavailable. Review exposure before retrying.')
            return
        if route == '/api/strategy-lab':
            self.json_response(200, STRATEGY_LAB.status()); return
        if route == '/api/operations':
            self.json_response(200, dict(storage=OPERATIONS.status(), paper=PAPER_WORKER.status(), agents=AGENTS.status(), liveExecutionReady=False)); return
        if route == '/api/agents':
            self.json_response(200, AGENTS.status()); return
        if route == '/api/paper-worker':
            try: self.json_response(200, dict(PAPER_WORKER.status(), paperBuild=PAPER_BUILD))
            except (sqlite3.Error,OSError): self.error(503,'Paper worker storage unavailable.')
            return
        if route == '/api/portal':
            try:
                result=PORTAL.status()
                cached=NEWS_AGENT.status()
                result['newsConfigured']=True
                result['newsConnected']=not cached['stale']
                result['newsHealth']=dict(status=cached.get('status','unchecked'),sources=cached.get('sources',[]))
                self.json_response(200,result)
            except (sqlite3.Error, OSError): self.error(503, 'Portal storage is unavailable.')
            return
        if route == "/api/status":
            self.json_response(200, {
                "connected": bool(session.get("access_token")),
                "profile": session.get("profile"),
                "liveOrdersEnabled": LIVE_ORDERS_ENABLED and LIVE_EXECUTION_READY,
                "liveOrdersConfigured": LIVE_ORDERS_ENABLED,
                "liveExecutionReady": LIVE_EXECUTION_READY,
                "liveReadinessReason": LIVE_READINESS_REASON,
                "credentialsConfigured": bool(API_KEY and API_SECRET),
                "csrf": session.get("csrf", ""),
                "dataStorageEnabled": os.environ.get('KITE_DATA_STORAGE_APPROVED','false').lower() == 'true',
            })
            return
        if route == "/api/automation":
            self.json_response(200, AUTOMATION.status()); return
        try:
            token = self.connected_token(session)
            if route == '/api/market/instruments':
                self.json_response(200, {'instruments':MARKET.instruments(token,(query.get('q') or [''])[0])}); return
            elif route == '/api/market/history':
                self.json_response(200, MARKET.job(session_id,(query.get('id') or [''])[0],(query.get('symbol') or [None])[0])); return
            elif route == '/api/market/stream':
                self.json_response(200, MARKET.stream_status(session_id)); return
            elif route == "/api/holdings":
                payload = kite_request("/portfolio/holdings", token)
            elif route == "/api/positions":
                payload = kite_request("/portfolio/positions", token)
            elif route == "/api/orders":
                payload = kite_request("/orders", token)
            elif route == "/api/orders/execution":
                account = EXECUTION.account(session.get("profile"))
                self.json_response(200, {"intents": EXECUTION.list(account), "scope": "manual", "automatedLiveEnabled": False}); return
            elif route == "/api/quote":
                instrument = (query.get("i") or [""])[0].strip().upper()
                if ":" not in instrument or len(instrument) > 60 or any(char not in "ABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789:&-_" for char in instrument):
                    self.error(400, "Use an instrument in EXCHANGE:SYMBOL format.")
                    return
                payload = kite_request("/quote/ltp?" + urllib.parse.urlencode({"i": instrument}), token)
            else:
                self.error(404, "Not found.")
                return
            self.json_response(200, payload)
        except PermissionError as exc:
            self.error(401, str(exc))
        except KiteSessionExpired as exc:
            session.pop("access_token", None)
            session.pop("profile", None)
            self.error(401, str(exc))
        except KiteError as exc:
            self.error(502, str(exc))
        except ValueError as exc:
            self.error(400, str(exc))
        except ImportError:
            self.error(503, 'Install requirements.txt into the app virtual environment and restart.')
        except Exception as exc:
            self.error(502, 'Market request failed ('+type(exc).__name__+'). Check broker login and subscription.')

    def do_POST(self) -> None:
        if not self.valid_host(): return
        route = urllib.parse.urlparse(self.path).path
        try:
            session_id, session = self.authenticated_session()
        except PermissionError as exc:
            self.error(403, str(exc))
            return
        try:
            values = self.body_json()
        except ValueError as exc:
            self.error(400, str(exc))
            return
        if route.startswith('/api/auto-selection/'):
            try:
                action=route.rsplit('/',1)[-1]
                if action == 'control':
                    if values.get('action') == 'resume_entries' and (
                        not AUTO_SELECTOR.enabled or self.connected_token(session) != AUTO_SELECTOR.token
                        or (session.get('profile') or {}).get('user_id') != AUTO_SELECTOR.profile
                    ):
                        raise PermissionError('Reconnect the owning broker session before resuming entries.')
                    result=AUTO_SELECTOR.control(values.get('action'))
                elif action == 'stop':
                    result=AUTO_SELECTOR.control('end_session')
                elif action in ('preview','start'):
                    template=values.get('templateAccount')
                    with PAPER.db() as db:
                        config=dict(PAPER.load(db,template)['config'])
                    if config.get('strategy')!='intraday-v1' or config.get('source')!='imported':
                        raise ValueError('Choose an imported Intraday v1 account as the assumptions template.')
                    calendar=values.get('calendar')
                    if action == 'preview':
                        if values.get('permitted') is not True:
                            raise ValueError('Confirm local data use permission.')
                        ranked,excluded=rank_candidates(values.get('candles',{}),config,calendar,values.get('asOf'))
                        result=dict(candidates=ranked,excluded=excluded,mode='offline-preview',live=False)
                    else:
                        if os.environ.get('KITE_DATA_STORAGE_APPROVED','false').lower()!='true':
                            raise ValueError('Provider retention approval required.')
                        if calendar is None:
                            calendar=automatic_selection_status()['calendar']
                        elif values.get('permitted') is not True:
                            raise ValueError('Confirm the supplied custom calendar or use the reviewed calendar.')
                        self.connected_token(session)
                        if PAPER_WORKER.status().get('enabled'):
                            raise ValueError('Stop the fixed-symbol worker first.')
                        result=AUTO_SELECTOR.start(session,config,calendar)
                else:
                    raise ValueError('Unknown automatic selection action.')
                self.json_response(200,result)
            except (ValueError,TypeError,KeyError,PermissionError) as exc:
                self.error(400,str(exc))
            except Exception:
                self.error(503,'Automatic selection unavailable. Review its state before retrying.')
            return
        if route == '/api/alerts/acknowledge':
            try:
                ALERTS.acknowledge(values.get('id'))
                self.json_response(200, ALERTS.status())
            except ValueError as exc: self.error(400, str(exc))
            return
        if route in ('/api/operations/backup','/api/operations/restore-drill'):
            try: self.json_response(200, OPERATIONS.backup() if route.endswith('/backup') else OPERATIONS.restore_drill())
            except Exception: self.error(503, 'Private storage backup failed; review operations health.')
            return
        if route.startswith('/api/strategy-lab/'):
            try:
                action = route.rsplit('/',1)[-1]
                if action == 'register': result=STRATEGY_LAB.register(values)
                elif action == 'candidate': result=STRATEGY_LAB.add_candidate(values.get('id'),values.get('config'))
                elif action == 'evaluate': result=STRATEGY_LAB.evaluate(values.get('id'),values.get('candidateId'),values.get('bars'),permitted=values.get('permitted'))
                elif action == 'promote': result=STRATEGY_LAB.promote(values.get('id'),values.get('candidateId'))
                elif action == 'rollback': result=STRATEGY_LAB.rollback(values.get('accountId'),values.get('reason'))
                else: raise ValueError('Unknown strategy lab action.')
                self.json_response(200,result)
            except (ValueError,TypeError,KeyError) as exc: self.error(400,str(exc))
            except Exception: self.error(503,'Strategy lab unavailable. Review its history before retrying.')
            return
        if route.startswith('/api/agents/'):
            try:
                if route == '/api/agents/enqueue':
                    result=dict(id=AGENTS.enqueue(values))
                    AGENTS.start()
                elif route == '/api/agents/run': result=dict(id=AGENTS.run_once())
                elif route == '/api/agents/cancel': AGENTS.cancel(values.get('id')); result=dict(cancelled=True)
                elif route == '/api/agents/lifecycle':
                    AGENTS.lifecycle(values.get('id'),values.get('state'),values.get('reason'));result=dict(updated=True)
                elif route == '/api/agents/review':
                    AGENTS.review(values.get('id'),'human:local-operator',values.get('checks'),values.get('critical',False))
                    result=dict(reviewed=True)
                else: raise ValueError('Unknown agent action.')
                self.json_response(200,result)
            except (ValueError,TypeError,KeyError) as exc:self.error(400,str(exc))
            except Exception:self.error(503,'Agent service unavailable.')
            return
        if route.startswith('/api/paper-worker/'):
            try:
                if route == '/api/paper-worker/start':
                    if AUTO_SELECTOR.status().get('enabled'):
                        raise ValueError('Stop automatic selection before starting the fixed-symbol worker.')
                    with PAPER.db() as db:
                        if db.execute('SELECT 1 FROM auto_selection WHERE account=?',(values.get('id'),)).fetchone():
                            raise ValueError('Resume this account through automatic selection to preserve its funding history.')
                    if os.environ.get('KITE_DATA_STORAGE_APPROVED','false').lower()!='true':
                        raise ValueError('Confirm permitted provider candle retention in local configuration before starting.')
                    self.connected_token(session)
                    result=PAPER_WORKER.start(session_id,session,values)
                elif route == '/api/paper-worker/stop': result=PAPER_WORKER.stop()
                else: raise ValueError('Unsupported paper worker action.')
                self.json_response(200,result)
            except (PermissionError,ValueError,TypeError,KeyError) as exc: self.error(400,str(exc))
            except Exception: self.error(503,'Paper worker unavailable. No broker order was sent; inspect worker status.')
            return
        if route == '/api/broker/snapshot':
            try:
                from broker_snapshot import build_snapshot
                import datetime as dt
                with LOCK:
                    token=self.connected_token(session)
                    account=(session.get('profile') or {}).get('user_id')
                collection_started=time.monotonic()
                started_at=dt.datetime.now(dt.timezone.utc).isoformat()
                payloads={key:kite_request(path,token) for key,path in (
                    ('profile','/user/profile'),('funds','/user/margins'),('orders','/orders'),
                    ('trades','/trades'),('positions','/portfolio/positions'),('holdings','/portfolio/holdings'))}
                if time.monotonic()-collection_started>30:
                    raise ValueError('Broker read collection exceeded 30 seconds; repeat snapshot.')
                received=dt.datetime.now(dt.timezone.utc).isoformat()
                with LOCK:
                    if session.get('access_token')!=token or (session.get('profile') or {}).get('user_id')!=account:
                        raise ValueError('Broker identity changed during read snapshot.')
                    result=build_snapshot(account,payloads,expected=values.get('expected'),as_of=received,received_at=received)
                result['collectionStartedAt']=started_at
                result['collectionFinishedAt']=received
                result['atomic']=False
                self.json_response(200,result)
            except (ValueError,PermissionError,TypeError,KeyError) as exc:self.error(409,str(exc))
            except KiteSessionExpired:
                self.error(401,'Broker session expired; reconnect before another snapshot.')
            except Exception:self.error(503,'Broker read snapshot failed. No execution authority was granted.')
            return
        if route.startswith('/api/portal/'):
            try:
                if route == '/api/portal/settings': result = PORTAL.update(values)
                elif route == '/api/portal/research':
                    if values.get('horizon')=='intraday':
                        from research_context import attach_announcements
                        values,context=attach_announcements(values,NEWS_AGENT.status(getattr(MARKET,'master',[])))
                        result=PORTAL.research(values)
                        result['automaticNewsCheck']=context
                    else: result=PORTAL.research(values)
                else: raise ValueError('Unknown portal action.')
                self.json_response(200, result)
            except (ValueError,TypeError,KeyError,OverflowError) as exc: self.error(400,str(exc))
            except (sqlite3.Error,OSError): self.error(503,'Portal storage is unavailable.')
            return
        if route.startswith('/api/trader/'):
            action=route.rsplit('/',1)[-1]
            try:
                if action.startswith('paper-'):
                    if action in ('paper-control', 'paper-bars', 'paper-fixture-bars',
                                  'paper-fixture-connect', 'paper-fixture-disconnect'):
                        with PAPER.db() as db:
                            managed = db.execute('SELECT 1 FROM auto_selection WHERE account=?',
                                                 (values.get('id'),)).fetchone()
                        if managed:
                            raise ValueError('Manage automatic accounts through Auto Trading session controls.')
                    if action=='paper-state': result=PAPER.status()
                    elif action=='paper-reconcile': result=PAPER.reconcile(values.get('id'))
                    elif action=='paper-fixture-connect': result=PAPER.fixture_link(values.get('id'),True)
                    elif action=='paper-fixture-disconnect': result=PAPER.fixture_link(values.get('id'),False)
                    elif action=='paper-fixture-bars': result=PAPER.fixture_batch(values.get('id'),values.get('instrument'),values.get('bars'),values.get('permitted'))
                    elif action=='paper-create': result=PAPER.create(values)
                    elif action=='paper-control':
                        with PAPER.db() as db:
                            managed=db.execute('SELECT 1 FROM auto_selection WHERE account=?',(values.get('id'),)).fetchone()
                        if managed and values.get('action') in ('start','resume_entries'):
                            raise ValueError('Resume managed accounts through automatic selection.')
                        result=PAPER.control(values.get('id'),values.get('action'))
                    elif action=='paper-bars': result=PAPER.ingest(values.get('id'),values.get('bars'),values.get('permitted'))
                    else: raise ValueError('Unknown paper action.')
                    self.json_response(200,result); return
                if action == 'evaluate-intraday':
                    from intraday_evaluation import evaluate_intraday
                    self.json_response(200, evaluate_intraday(values)); return
                if route == '/api/trader/evaluate':
                    from evaluation import demo_request, evaluate
                    if 'demo' in values and (len(values) != 1 or values['demo'] is not True):
                        raise ValueError('The demo takes only {"demo": true}. Use the import form for other inputs.')
                    report = evaluate(demo_request() if 'demo' in values else values)
                    report['researchReview'] = EXPERIMENTS.record(report)
                    self.json_response(200, report); return
                if action=='approve':
                    with LOCK:
                        draft=session.get('paper_draft')
                        if not draft or values.get('draftId')!=draft['id'] or time.monotonic()-draft['at']>120:
                            raise ValueError('Paper draft expired or already consumed. Review again.')
                        if values.get('confirm')!='APPROVE PAPER ORDER':raise ValueError('Explicit paper approval required.')
                        book=session.setdefault('paper_book',[])
                        if len(book)>=100:raise ValueError('Paper session limit reached.')
                        total=sum(item.get('estimatedCapital',0) for item in book)
                        if total+draft['baseExposure']+draft['pendingExposure']+draft['plan']['estimatedCapital']>draft['maxExposure']:
                            raise ValueError('Paper book exposure changed; review the risk limits again.')
                        reserved_loss=sum(item['estimatedStopLoss'] for item in book)
                        if reserved_loss+draft['dailyLoss']+draft['plan']['estimatedStopLoss']>draft['dailyLossLimit']:
                            raise ValueError('Open paper plans exceed the remaining daily loss allowance.')
                        record={'estimatedCapital':draft['plan']['estimatedCapital'],'estimatedStopLoss':draft['plan']['estimatedStopLoss'],'id':draft['id'],'symbol':draft['symbol'],'quantity':draft['plan']['quantity'],
                            'assumedEntry':draft['plan']['entry'],'status':'PAPER ONLY — hypothetical fill at user-entered entry; no broker order'}
                        book.append(record);session.pop('paper_draft',None)
                    self.json_response(200,{'paperOrder':record,'book':book});return
                if action=='broker':
                    with LOCK: session.pop('paper_draft',None)
                result=dispatch(action,values)
                if action=='broker' and result['allowed']:
                    symbol=str(values.get('symbol','')).strip().upper()
                    if not symbol or len(symbol)>40:raise ValueError('Enter a trading symbol for paper review.')
                    identity=secrets.token_urlsafe(24)
                    with LOCK:
                        booked=session.get('paper_book',[])
                        if sum(p['estimatedStopLoss'] for p in booked)+float(values['dailyLoss'])+result['estimatedStopLoss']>float(values['dailyLossLimit']):
                            raise ValueError('Open paper plans exceed the remaining daily loss allowance.')
                        if sum(p['estimatedCapital'] for p in booked)+float(values['exposure'])+float(values['pendingExposure'])+result['estimatedCapital']>float(values['maxExposure']):
                            raise ValueError('Open paper plans exceed the exposure limit.')
                        session['paper_draft']={'id':identity,'at':time.monotonic(),'plan':result,'symbol':symbol,'baseExposure':float(values['exposure']),'pendingExposure':float(values['pendingExposure']),'maxExposure':float(values['maxExposure']),'dailyLoss':float(values['dailyLoss']),'dailyLossLimit':float(values['dailyLossLimit'])}
                    result.update(draftId=identity,symbol=symbol,mode='PAPER ONLY',expiresInSeconds=120)
                self.json_response(200,result)
            except (ValueError,TypeError,KeyError,OverflowError) as exc:
                self.error(400,str(exc))
            except (sqlite3.Error, OSError):
                self.error(503, "Local data storage is unavailable. Processing stopped; inspect storage and reconcile before retrying.")
            return
        if route.startswith('/api/automation/'):
            try:
                action=route.rsplit('/',1)[-1]
                if action=='config': result=AUTOMATION.save(values)
                elif action in ('start','pause','stop'): result=AUTOMATION.control(action)
                else: raise ValueError('Unsupported automation action.')
                self.json_response(200,result)
            except (ValueError,TypeError,OverflowError) as exc:
                self.error(400,str(exc))
            except (sqlite3.Error, OSError):
                self.error(503, "Automation storage is unavailable. No execution was started.")
            return
        if route == "/api/connect":
            self.begin_kite_login(session)
        elif route == "/api/disconnect":
            if AUTO_SELECTOR.enabled:
                # Explicit disconnect revokes the standing local paper grant
                # even if the browser that originally started it has expired.
                AUTO_SELECTOR.revoke()
            PAPER_WORKER.stop_owner(session_id)
            MARKET.stop_stream(session_id)
            MARKET.cancel_owner(session_id)
            session.pop("access_token", None)
            session.pop("profile", None)
            session.pop("oauth_state", None)
            session.pop("reviews", None)
            self.json_response(200, {"ok": True})
        elif route.startswith('/api/market/'):
            try:
                if route == '/api/market/stress':
                    from validation_lab import stress_suite
                    self.json_response(200,stress_suite()); return
                if route == '/api/market/research':
                    self.json_response(200,synthetic_research(values)); return
                token=self.connected_token(session)
                if route == '/api/market/history':
                    self.json_response(202,MARKET.start_history(session_id,token,values))
                elif route == '/api/market/rank':
                    self.json_response(200,MARKET.rank(session_id,str(values.get('id','')),str(values.get('horizon','')),str(values.get('asOf',''))))
                elif route == '/api/market/cancel':
                    MARKET.cancel(session_id,values.get('id','')); self.json_response(200,{'ok':True})
                elif route == '/api/market/stream/start':
                    self.json_response(200,MARKET.start_stream(session_id,token,str(values.get('symbol','')).strip().upper()))
                elif route == '/api/market/stream/stop':
                    MARKET.stop_stream(session_id); self.json_response(200,{'ok':True})
                else:
                    self.error(404,'Not found.')
            except PermissionError as exc:
                self.error(401,str(exc))
            except ValueError as exc:
                self.error(400,str(exc))
            except Exception as exc:
                self.error(502,'Market request failed ('+type(exc).__name__+'). Check login, dependency installation, and subscription.')
        elif route == "/api/orders/reconcile":
            try:
                with LOCK:
                    token = self.connected_token(session)
                    account = EXECUTION.account(session.get("profile"))
                orders = kite_request("/orders", token).get("data")
                trades = kite_request("/trades", token).get("data")
                with LOCK:
                    if session.get("access_token") != token or EXECUTION.account(session.get('profile')) != account:
                        raise ValueError("Broker session changed during reconciliation.")
                    intents = EXECUTION.reconcile(account, orders, trades)
                self.json_response(200, {"intents": intents, "positionsReconciled": False})
            except (ValueError, PermissionError) as exc:
                self.error(409, str(exc))
            except KiteSessionExpired:
                session.pop("access_token", None)
                session.pop("profile", None)
                self.error(401, "Broker session expired. Reconnect; unresolved intents are preserved.")
            except KiteError:
                self.error(502, "Broker reconciliation failed. Existing intents remain unresolved.")
            except Exception:
                self.error(503, "Reconciliation journal unavailable. Do not submit new orders.")
        elif route == "/api/orders/preview":
            try:
                normalized = validate_order(values)
            except ValueError as exc:
                self.error(400, str(exc))
                return
            confirmation_id=secrets.token_urlsafe(24)
            with LOCK:
                reviews=session.setdefault('reviews',{})
                reviews.clear()
                login = session.get('access_token') or ''
                reviews[confirmation_id]={'order':normalized,'created':time.monotonic(),
                                          'loginDigest':hashlib.sha256(login.encode()).digest()}
            self.json_response(200, {"order": normalized, "confirmationId":confirmation_id, "live": LIVE_ORDERS_ENABLED and LIVE_EXECUTION_READY, "requiresConfirmation": True})
        elif route == "/api/orders/place":
            self.place_order(session, values)
        else:
            self.error(404, "Not found.")

    def begin_kite_login(self, session: dict[str, Any]) -> None:
        if not API_KEY or not API_SECRET:
            self.error(503, "Add your Kite developer API key and secret to the local .env file, then restart TradeLab.")
            return
        state = secrets.token_urlsafe(24)
        session["oauth_state"] = state
        session["oauth_created"] = time.monotonic()
        params = urllib.parse.urlencode({
            "v": "3",
            "api_key": API_KEY,
            "redirect_params": urllib.parse.urlencode({"state": state}),
        })
        self.json_response(200, {"url": "https://kite.zerodha.com/connect/login?" + params})

    def kite_callback(self, query: dict[str, list[str]]) -> None:
        _, session = self.session()
        state = (query.get("state") or [""])[0]
        with LOCK:
            expected = session.pop("oauth_state", "")
            created = session.pop("oauth_created", None)
        request_token = (query.get("request_token") or [""])[0]
        status = (query.get("status") or [""])[0]
        if created is None or not 0 <= time.monotonic()-created <= 600 or not expected or not state or not hmac.compare_digest(str(expected), state):
            self.redirect("/?notice=login_state_error")
            return
        if status != "success" or not request_token or not API_KEY or not API_SECRET:
            self.redirect("/?notice=login_cancelled")
            return
        checksum = hashlib.sha256((API_KEY + request_token + API_SECRET).encode()).hexdigest()
        data = urllib.parse.urlencode({"api_key": API_KEY, "request_token": request_token, "checksum": checksum}).encode()
        request = urllib.request.Request(
            f"{KITE_API}/session/token",
            data=data,
            headers={"Content-Type": "application/x-www-form-urlencoded", "X-Kite-Version": "3", "Accept": "application/json"},
            method="POST",
        )
        try:
            from broker_transport import fetch_json
            payload = fetch_json(request)
            if payload.get("status") != "success" or not payload.get("data", {}).get("access_token"):
                raise KiteError("Kite Connect did not return an access token.")
            profile = payload["data"]
            if AUTO_SELECTOR.enabled and AUTO_SELECTOR.profile != profile.get("user_id"):
                AUTO_SELECTOR.revoke()
            with LOCK:
                session["access_token"] = profile["access_token"]
                session["profile"] = {key: profile.get(key) for key in ("user_id", "user_name", "user_shortname", "email", "broker", "login_time")}
            self.redirect("/?notice=connected")
        except Exception:
            # Never put request tokens, access tokens, or API secrets in the page or logs.
            self.redirect("/?notice=login_failed")

    def place_order(self, session: dict[str, Any], values: dict[str, Any]) -> None:
        if not LIVE_ORDERS_ENABLED:
            self.error(403, "Live orders are disabled. Set TRADELAB_ENABLE_LIVE_ORDERS=true in .env and restart only after reviewing broker requirements.")
            return
        if not LIVE_EXECUTION_READY:
            self.error(403, LIVE_READINESS_REASON)
            return
        try:
            token = self.connected_token(session)
            order = validate_order(values)
        except (PermissionError, ValueError) as exc:
            self.error(400, str(exc))
            return
        if values.get("confirm_text") != "PLACE LIVE ORDER":
            self.error(400, "Type PLACE LIVE ORDER to confirm this broker order.")
            return
        confirmation_id = str(values.get("confirmation_id", ""))
        if len(confirmation_id) < 20 or len(confirmation_id) > 100:
            self.error(400, "Refresh the order confirmation and try again.")
            return
        with LOCK:
            submitted: set[str] = session.setdefault("submitted", set())
            if confirmation_id in submitted:
                self.error(409, "This confirmation was already submitted. Refresh the order book before creating another order.")
                return
            review=session.setdefault('reviews',{}).get(confirmation_id)
            if (not review or time.monotonic()-review['created']>120 or review['order']!=order
                    or session.get('access_token') != token
                    or review.get('loginDigest') != hashlib.sha256(token.encode()).digest()):
                self.error(409,'Order review expired or changed. Review the exact order again.'); return
            if len(submitted)>=500:
                self.error(409,'Session order limit reached. Check broker orders and reconnect.'); return
            try:
                account = EXECUTION.account(session.get("profile"))
                intent = EXECUTION.prepare(account, confirmation_id, order, hashlib.sha256(token.encode()).digest())
            except ValueError as exc:
                self.error(409, str(exc)); return
            except Exception:
                self.error(503, "Execution journal unavailable. No order was sent."); return
            submitted.add(confirmation_id)
            session['reviews'].pop(confirmation_id,None)
        try:
            result = kite_request("/orders/regular", token, method="POST", form=dict(order, tag=intent["tag"]))
        except KiteError:
            try:
                EXECUTION.acknowledgement(intent["id"])
            except Exception:
                pass  # Durable SUBMITTING still blocks re-submission after a write failure.
            self.error(502, "Submission outcome is uncertain. Do not retry until you check the Zerodha order book and trades. This review cannot be reused.")
            return
        response_data = result.get("data")
        order_id = response_data.get("order_id") if isinstance(response_data, dict) else None
        if not isinstance(order_id, str) or not order_id.strip():
            try:
                EXECUTION.acknowledgement(intent["id"])
            except Exception:
                pass  # Durable SUBMITTING still blocks re-submission after a write failure.
            self.error(502, "Broker acknowledgement has no order ID. Outcome unknown. Check the order book and trades before submitting again.")
            return
        try:
            EXECUTION.acknowledgement(intent["id"], order_id)
        except Exception:
            self.error(503, "Broker replied but journal update failed. Do not retry; reconcile the durable submission."); return
        self.json_response(200, {"ok": True, "intentId": intent["id"], "orderId": order_id, "message": "The broker accepted the order request. Check the order book for its current status."})


class LocalServer(http.server.ThreadingHTTPServer):
    # Windows SO_REUSEADDR can let a second TradeLab start on an occupied
    # port, with requests split between processes holding different sessions.
    allow_reuse_address = os.name != "nt"
    allow_reuse_port = False

    def server_bind(self):
        if os.name == "nt":
            self.socket.setsockopt(socket.SOL_SOCKET, socket.SO_EXCLUSIVEADDRUSE, 1)
        super().server_bind()


def serve() -> None:
    host = os.environ.get("APP_HOST", "127.0.0.1").strip()
    if host not in {"127.0.0.1", "localhost", "::1"}:
        raise SystemExit("TradeLab local server only accepts loopback APP_HOST values.")
    try:
        port = int(os.environ.get("APP_PORT", "8765"))
    except ValueError:
        raise SystemExit("APP_PORT must be an integer.") from None
    if not 1024 <= port <= 65535:
        raise SystemExit("APP_PORT must be between 1024 and 65535.")
    try:
        server = LocalServer((host, port), Handler)
    except OSError as exc:
        raise SystemExit(f"Could not bind TradeLab to {host}:{port}: {exc}") from None
    server.daemon_threads = True
    print(f"TradeLab is available at http://{host}:{port} (local machine only). Press Ctrl+C to stop.")
    try:
        NEWS_AGENT.start()
        DESK.start()
        def ensure_watcher():
            if (ALERTS.status().get('watcherExpires') or 0) > time.time():
                return
            try:
                subprocess.Popen([sys.executable, str(ROOT / 'scripts/watch_service.py'),
                    '--url', f'http://127.0.0.1:{port}/api/service-health', '--database', str(ALERTS.path)],
                    cwd=ROOT, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                    creationflags=subprocess.CREATE_NO_WINDOW if os.name == 'nt' else 0)
                ALERTS.observe('watcher:startup', 'Independent service watcher could not start.', False)
            except OSError:
                ALERTS.observe('watcher:startup', 'Independent service watcher could not start.', True)
        OPERATIONS.ensure_watcher = ensure_watcher
        OPERATIONS.start()
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        AUTO_SELECTOR.stop()
        DESK.stop()
        NEWS_AGENT.stop()
        OPERATIONS.stop()
        MARKET.close()
        server.server_close()


if __name__ == "__main__":
    serve()
