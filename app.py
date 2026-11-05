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
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parent
WEB = ROOT / "web"
KITE_API = "https://api.kite.trade"
SESSIONS: dict[str, dict[str, Any]] = {}
LOCK = threading.RLock()


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
from trader_suite import TOOLS, dispatch
from automation import Coordinator
AUTOMATION = Coordinator(Path(os.environ.get("TRADELAB_AUTOMATION_DB", str(Path(os.environ.get("LOCALAPPDATA", str(ROOT / "data" / "private"))) / "TradeLabIndia" / "automation.sqlite"))))
from market_data import MarketData, synthetic_research
DATA_ROOT = Path(os.environ.get('TRADELAB_DATA_DIR', str(Path(os.environ.get('LOCALAPPDATA', str(ROOT / 'data' / 'private'))) / 'TradeLabIndia' / 'market-data')))
MARKET = MarketData(API_KEY, DATA_ROOT)


class KiteError(Exception):
    pass

class KiteSessionExpired(KiteError):
    pass


def kite_request(path: str, token: str, *, method: str = "GET", form: dict[str, Any] | None = None) -> dict[str, Any]:
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
        with urllib.request.urlopen(request, timeout=15) as response:
            payload = json.loads(response.read(2_000_000).decode("utf-8"))
    except urllib.error.HTTPError as exc:
        try:
            payload = json.loads(exc.read(64_000).decode("utf-8"))
            message = payload.get("message") or payload.get("error_type") or "Broker request failed"
        except Exception:
            message = f"Broker request failed with HTTP {exc.code}"
        if exc.code == 403:
            raise KiteSessionExpired("Broker session expired. Reconnect Zerodha.") from None
        raise KiteError(message) from None
    except (urllib.error.URLError, TimeoutError, json.JSONDecodeError) as exc:
        raise KiteError(f"Could not reach Kite Connect: {type(exc).__name__}") from None
    if not isinstance(payload, dict) or payload.get("status") != "success":
        message = payload.get("message", "Broker returned an unsuccessful response") if isinstance(payload, dict) else "Invalid broker response"
        raise KiteError(str(message))
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
            if session_id not in SESSIONS:
                session_id = secrets.token_urlsafe(32)
                SESSIONS[session_id] = {"csrf": secrets.token_urlsafe(32), "submitted": set()}
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
        if not supplied or not hmac.compare_digest(supplied, session["csrf"]):
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
        if route in {"/", "/index.html", "/trader-evaluate"} or route.removeprefix("/trader-") in TOOLS:
            session_id, session = self.session()
            template = "evaluation.html" if route == "/trader-evaluate" else ("trader.html" if route.startswith("/trader-") else "index.html")
            page = (WEB / template).read_text(encoding="utf-8").replace("__CSRF_TOKEN__", session["csrf"])
            cookie = f"tradelab_session={session_id}; HttpOnly; SameSite=Lax; Path=/"
            self.send_bytes(200, page.encode(), "text/html; charset=utf-8", extra_headers=[("Set-Cookie", cookie)])
            return
        if route == "/auth/kite/callback":
            self.kite_callback(urllib.parse.parse_qs(parsed.query))
            return
        if route in {"/app.js", "/market.js", "/automation.js", "/account.js", "/trader.js", "/trader.css", "/evaluation.js", "/evaluation.css", "/styles.css"}:
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
        session_id, session = self.session()
        if route == "/api/status":
            self.json_response(200, {
                "connected": bool(session.get("access_token")),
                "profile": session.get("profile"),
                "liveOrdersEnabled": LIVE_ORDERS_ENABLED,
                "credentialsConfigured": bool(API_KEY and API_SECRET),
                "csrf": session["csrf"],
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
        if route.startswith('/api/trader/'):
            action=route.rsplit('/',1)[-1]
            try:
                if route == '/api/trader/evaluate':
                    from evaluation import demo_request, evaluate
                    if 'demo' in values and (len(values) != 1 or values['demo'] is not True):
                        raise ValueError('The demo takes only {"demo": true}. Use the import form for other inputs.')
                    report = evaluate(demo_request() if 'demo' in values else values)
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
            return
        if route == "/api/connect":
            self.begin_kite_login(session)
        elif route == "/api/disconnect":
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
                reviews[confirmation_id]={'order':normalized,'created':time.monotonic()}
            self.json_response(200, {"order": normalized, "confirmationId":confirmation_id, "live": LIVE_ORDERS_ENABLED, "requiresConfirmation": True})
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
        params = urllib.parse.urlencode({
            "v": "3",
            "api_key": API_KEY,
            "redirect_params": urllib.parse.urlencode({"state": state}),
        })
        self.json_response(200, {"url": "https://kite.zerodha.com/connect/login?" + params})

    def kite_callback(self, query: dict[str, list[str]]) -> None:
        _, session = self.session()
        state = (query.get("state") or [""])[0]
        expected = session.pop("oauth_state", "")
        request_token = (query.get("request_token") or [""])[0]
        status = (query.get("status") or [""])[0]
        if not expected or not state or not hmac.compare_digest(str(expected), state):
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
            with urllib.request.urlopen(request, timeout=15) as response:
                payload = json.loads(response.read(256_000).decode("utf-8"))
            if payload.get("status") != "success" or not payload.get("data", {}).get("access_token"):
                raise KiteError("Kite Connect did not return an access token.")
            session["access_token"] = payload["data"]["access_token"]
            profile = payload["data"]
            session["profile"] = {key: profile.get(key) for key in ("user_id", "user_name", "user_shortname", "email", "broker", "login_time")}
            self.redirect("/?notice=connected")
        except Exception:
            # Never put request tokens, access tokens, or API secrets in the page or logs.
            self.redirect("/?notice=login_failed")

    def place_order(self, session: dict[str, Any], values: dict[str, Any]) -> None:
        if not LIVE_ORDERS_ENABLED:
            self.error(403, "Live orders are disabled. Set TRADELAB_ENABLE_LIVE_ORDERS=true in .env and restart only after reviewing broker requirements.")
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
            if not review or time.monotonic()-review['created']>120 or review['order']!=order:
                self.error(409,'Order review expired or changed. Review the exact order again.'); return
            if len(submitted)>=500:
                self.error(409,'Session order limit reached. Check broker orders and reconnect.'); return
            submitted.add(confirmation_id)
            session['reviews'].pop(confirmation_id,None)
        try:
            result = kite_request("/orders/regular", token, method="POST", form=order)
        except KiteError:
            self.error(502, "Submission outcome is uncertain. Do not retry until you check the Zerodha order book and trades. This review cannot be reused.")
            return
        order_id = result.get("data", {}).get("order_id")
        self.json_response(200, {"ok": True, "orderId": order_id, "message": "The broker accepted the order request. Check the order book for its current status."})


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
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    serve()
