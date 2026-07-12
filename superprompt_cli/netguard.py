#!/usr/bin/env python3
"""
netguard.py — сетевая безопасность для инструмента web_fetch: SSRF-гард (блок внутренних/
метадата-хостов и CGNAT), IP-пиннинг против DNS-rebinding, снятие auth на кросс-хост редиректе,
percent-encoding не-ASCII URL, TLS-верификация. Никаких внешних зависимостей — только stdlib.

Детерминированная проверка ссылок в результате LLM: каждый URL/DOI из текста
проверяется реальным запросом (HTTP-статус; DOI — через handle-API doi.org).
Любой мёртвый URL / несуществующий DOI, НЕ помеченный автором как непроверенный,
= сфабрикованное критичное утверждение => ВЕТО (REJECT) по канону GATE.md §вето.

Классы результата по ссылке:
  ALIVE      2xx — ссылка живая
  BLOCKED    401/403/405/406/429/анти-бот — существование не опровергнуто (WARN)
  TIMEOUT    таймаут/сетевая неопределённость (WARN)
  DEAD       404/410 — путь не существует (VETO)
  DEAD_HOST  DNS/connection refused — хост не существует (VETO)
  SUSPECT    прочие 4xx/5xx (WARN; в strict-режиме — VETO)
  BAD_DOI    DOI не существует в handle-системе (VETO)
  MARKED     автор честно пометил [НЕПРОВЕРЕНО]/[UNVERIFIED] (не проверяем — ABSTAIN-поведение)

Вердикт: VETO (есть сфабрикованные) | PASS (все проверяемые живые) |
         PASS_WITH_WARNINGS (нет мёртвых, есть неопределённые) | NO_CLAIMS (ссылок нет).

Дизайн-принципы (как у typed-VETO чисел): пересчёт/перепроверка ОРАКУЛОМ (сетью),
а не мнением судьи; recall по мёртвым ссылкам структурно = 1 (каждая проверяется);
precision защищена классом BLOCKED (анти-бот не считается фабрикацией).
"""
import argparse
import concurrent.futures as cf
import http.client
import ipaddress
import json
import os
import re
import socket
import ssl
import sys
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

# TTL-кэш сетевых проверок: ремонт-циклы и tool link_check перепроверяют те же
# ссылки — второй заход не должен ходить в сеть (ключ включает контекст-строку,
# т.к. MISMATCH зависит от неё)
_CACHE = {}
_CACHE_LOCK = threading.Lock()
CACHE_TTL = 900


def _cache_get(key):
    with _CACHE_LOCK:
        hit = _CACHE.get(key)
        if hit and time.time() - hit[0] < CACHE_TTL:
            return hit[1]
    return None


def _cache_put(key, value):
    with _CACHE_LOCK:
        _CACHE[key] = (time.time(), value)
    return value

UA = ("Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/126.0 Safari/537.36")

URL_RE = re.compile(r'https?://[^\s<>"«»`\)\]\}\|]+')
DOI_RE = re.compile(r'\b10\.\d{4,9}/[^\s"<>\]\)\},;]+')
MARK_RE = re.compile(r'\[\s*(НЕПРОВЕРЕНО|UNVERIFIED|не\s*проверено)\s*\]', re.I)
TRAIL = '.,;:!?…\'"”»›`*_'

# package-oracle (анти-slopsquatting): pip/npm-установки и requirements-строки
PIP_RE = re.compile(r'(?:pip3?|python3?\s+-m\s+pip)\s+install\s+([^\n|&;]+)')
NPM_RE = re.compile(r'npm\s+(?:install|i|add)\s+([^\n|&;]+)')
REQ_RE = re.compile(r'^\s*([A-Za-z0-9][A-Za-z0-9._\-]*)==([A-Za-z0-9][A-Za-z0-9.\-]*)\s*(?:#.*)?$',
                    re.M)
_PKG_SKIP = re.compile(r'^-|^\.|/|^git\+|^https?:|[<>$*{]')


def extract_pkgs(text):
    """[(manager, name, version|None, line, marked)] из pip/npm-команд и requirements."""
    out, seen = [], set()

    def add(mgr, tok, line):
        tok = tok.strip().strip('"\'')
        if not tok or _PKG_SKIP.search(tok):
            return
        if mgr == "pip":
            m = re.match(r'^([A-Za-z0-9][A-Za-z0-9._\-]*)(?:\[[^\]]*\])?(?:==([^=<>!~\s]+))?$', tok)
        else:
            m = re.match(r'^(@?[A-Za-z0-9][A-Za-z0-9._\-]*(?:/[A-Za-z0-9._\-]+)?)(?:@([^@\s]+))?$', tok)
        if not m:
            return
        name, ver = m.group(1), m.group(2)
        key = (mgr, name.lower(), ver)
        if key not in seen:
            seen.add(key)
            out.append((mgr, name, ver, line.strip(), bool(MARK_RE.search(line))))

    for line in text.splitlines():
        for m in PIP_RE.finditer(line):
            for tok in m.group(1).split():
                if tok.startswith('-'):
                    break  # флаги (-r/-e/-U …) — дальше не пакетные имена
                add("pip", tok, line)
        for m in NPM_RE.finditer(line):
            for tok in m.group(1).split():
                if tok.startswith('-'):
                    continue
                add("npm", tok, line)
    for m in REQ_RE.finditer(text):
        add("pip", "%s==%s" % (m.group(1), m.group(2)), m.group(0))
    return out


# ---- RECORD-REPLAY КАССЕТЫ (детерминированные ОФЛАЙН гейт-evals; harness-eng П.4 trace-first) ----
# Сеть — источник недетерминизма гейта (URL умер → регрессия непроизводима). Кассета записывает
# ответы оракула один раз и переигрывает их офлайн. Активация: use_cassette(path, 'record'|'replay')
# или env SPT_LINKVETO_REPLAY=<file> (авто-replay).
_CASS = None
_CASS_MODE = None       # None | 'record' | 'replay'
_CASS_PATH = None


def use_cassette(path, mode="replay"):
    """Включить кассету. replay — читать записанные ответы (сеть не трогается); record — писать."""
    global _CASS, _CASS_MODE, _CASS_PATH
    _CASS_PATH, _CASS_MODE = path, mode
    if mode == "replay":
        _CASS = json.load(open(path, encoding="utf-8")) if os.path.exists(path) else {}
    else:
        _CASS = {}


def save_cassette():
    if _CASS_MODE == "record" and _CASS_PATH:
        json.dump(_CASS, open(_CASS_PATH, "w", encoding="utf-8"), ensure_ascii=False, indent=0)


def _cass(key, compute):
    """replay → записанный ответ (нет записи → UNCHECKED, без сети); record → посчитать+сохранить."""
    if _CASS_MODE == "replay":
        v = _CASS.get(key)
        return tuple(v) if v else ("UNCHECKED", None)
    r = compute()
    if _CASS_MODE == "record":
        _CASS[key] = list(r)
    return r


if os.environ.get("SPT_LINKVETO_REPLAY"):    # env-активация авто-replay (для CI/тестов)
    use_cassette(os.environ["SPT_LINKVETO_REPLAY"], "replay")


def check_pkg(mgr, name, ver, timeout=15):
    return _cass("pkg:%s:%s:%s" % (mgr, name, ver),
                 lambda: _check_pkg_impl(mgr, name, ver, timeout))


def _check_pkg_impl(mgr, name, ver, timeout=15):
    """Оракул реестра: PyPI JSON API / npm registry. -> (status, code)."""
    try:
        if mgr == "pip":
            api = "https://pypi.org/pypi/%s/json" % urllib.parse.quote(name)
        else:
            api = "https://registry.npmjs.org/%s" % urllib.parse.quote(name, safe="@/")
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with _opener().open(req, timeout=timeout) as r:  # TLS-verify + redirect-guard
            data = json.load(r)
        if ver:
            versions = (data.get("releases", {}) if mgr == "pip"
                        else data.get("versions", {}))
            if ver not in versions:
                return "BAD_VERSION", 200
        return "ALIVE", 200
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "BAD_PACKAGE", 404
        return "SUSPECT", e.code
    except Exception:  # noqa: BLE001
        return "TIMEOUT", None


def check_wayback(url, timeout=10):
    """Второй канал: снапшот в Wayback Machine. -> (есть_снапшот, ts|None)."""
    api = ("https://archive.org/wayback/available?url=" +
           urllib.parse.quote(url, safe=""))
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with _opener().open(req, timeout=timeout) as r:  # TLS-verify + redirect-guard
            data = json.load(r)
        snap = (data.get("archived_snapshots") or {}).get("closest") or {}
        if snap.get("available"):
            return True, snap.get("timestamp")
        return False, None
    except Exception:  # noqa: BLE001
        return False, None


def extract_links(text):
    """[(kind, value, line, marked)] — уникальные URL и DOI с контекстной строкой."""
    seen, out = set(), []
    for line in text.splitlines():
        marked = bool(MARK_RE.search(line))
        for m in URL_RE.finditer(line):
            u = m.group(0).rstrip(TRAIL)
            # обрезать хвостовую ')' без парной '(' внутри URL
            while u.endswith(')') and u.count('(') < u.count(')'):
                u = u[:-1]
            if u not in seen:
                seen.add(u)
                out.append(("url", u, line.strip(), marked))
        for m in DOI_RE.finditer(line):
            d = m.group(0).rstrip(TRAIL + '/')
            key = 'doi:' + d
            # DOI, уже пойманный как URL doi.org/<d>, не проверяем дважды
            if d.lower().startswith('10.') and key not in seen and \
                    not any(u.endswith('doi.org/' + d) for u in seen):
                seen.add(key)
                out.append(("doi", d, line.strip(), marked))
    return out


_CGNAT4 = ipaddress.ip_network("100.64.0.0/10")   # RFC 6598 shared-address (CGNAT): не публичный,
#                                                    OWASP-SSRF рекомендует блокировать (Python не
#                                                    флагует его как is_private) — defense-in-depth.


def _ip_is_internal(ip):
    return (ip.is_loopback or ip.is_link_local or ip.is_private
            or ip.is_reserved or ip.is_multicast or ip.is_unspecified
            or (ip.version == 4 and ip in _CGNAT4))


def _host_is_internal(host):
    """SSRF-защита: True если хост резолвится в loopback/link-local/приватный/резерв
    (метадата облака 169.254.169.254, localhost, ::1, RFC1918). Не резолвится → False
    (обычный путь вернёт DEAD_HOST). Проверяем ВСЕ A/AAAA-записи (анти DNS-rebinding)."""
    if not host:
        return True
    try:
        infos = socket.getaddrinfo(host, None)
    except Exception:  # noqa: BLE001
        return False
    for info in infos:
        try:
            addr = ipaddress.ip_address(info[4][0].split("%")[0])
        except ValueError:
            continue
        if _ip_is_internal(addr):
            return True
    return False


def _vet_and_pin(host, port):
    """Резолвим host ОДИН раз, проверяем ВСЕ полученные IP и возвращаем ОДИН публичный IP.
    Соединяться потом будем ровно по нему (см. пиннинг-connection) — это закрывает TOCTOU/
    DNS-rebinding: между проверкой и коннектом НЕТ второго DNS-запроса (M5). Внутренний IP
    среди ответов → _InternalHost; не резолвится → socket.gaierror (выше → DEAD_HOST)."""
    infos = socket.getaddrinfo(host, port, proto=socket.IPPROTO_TCP)   # gaierror пробрасываем
    pinned = None
    for _fam, _, _, _, sa in infos:
        try:
            ip = ipaddress.ip_address(sa[0].split("%")[0])
        except ValueError:
            continue
        if _ip_is_internal(ip):
            raise _InternalHost(host)          # ЛЮБОЙ внутренний адрес среди ответов → блок
        if pinned is None:
            pinned = sa[0]
    if pinned is None:
        raise _InternalHost(host)
    return pinned


def _url_host(url):
    try:
        return urllib.parse.urlparse(url).hostname
    except Exception:  # noqa: BLE001
        return None


def _ascii_url(url):
    """Percent-encode не-ASCII в URL (кириллица в query/path и т.п.) — иначе HTTP request-line
    падает UnicodeEncodeError 'ascii' (модель ищет по-русски → web_fetch/link-veto роняло). Уже
    закодированные %XX и структура URL сохраняются (safe включает служебные символы и '%')."""
    try:
        if all(ord(c) < 128 for c in url):
            return url
        return urllib.parse.quote(url, safe="%/:?#[]@!$&'()*+,;=~-._")
    except Exception:  # noqa: BLE001
        return url


class _InternalHost(Exception):
    """URL указывает на внутренний/метадата-хост — запрос не выполняем (SSRF)."""


class _GuardedRedirect(urllib.request.HTTPRedirectHandler):
    """Перепроверять КАЖДЫЙ hop редиректа: публичная страница может 302-нуть на
    169.254.169.254/localhost. Без этого начальной проверки хоста недостаточно (SSRF)."""
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        if _host_is_internal(_url_host(newurl)):
            raise _InternalHost(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


# ---- IP-пиннинг: соединяемся с ПРОВЕРЕННЫМ IP (не даём urllib повторно резолвить хост) ----
class _PinnedHTTPConnection(http.client.HTTPConnection):
    _pin = None

    def connect(self):
        self.sock = socket.create_connection((self._pin, self.port),
                                             self.timeout, self.source_address)
        if self._tunnel_host:
            self._tunnel()


class _PinnedHTTPSConnection(http.client.HTTPSConnection):
    _pin = None

    def connect(self):
        sock = socket.create_connection((self._pin, self.port),
                                        self.timeout, self.source_address)
        if self._tunnel_host:
            self.sock = sock
            self._tunnel()
        # TLS-SNI и проверка сертификата — по ИМЕНИ хоста (self.host), коннект — по IP
        self.sock = self._context.wrap_socket(sock, server_hostname=self.host)


def _split_hostport(host, default_port):
    if host.startswith("["):                       # IPv6-литерал [::1]:443
        h, _, rest = host[1:].partition("]")
        return h, int(rest[1:]) if rest.startswith(":") else default_port
    if ":" in host:
        h, _, p = host.rpartition(":")
        return h, int(p) if p.isdigit() else default_port
    return host, default_port


def _pinned_http_factory(host, **kw):
    hn, port = _split_hostport(host, 80)
    conn = _PinnedHTTPConnection(host, **kw)       # gaierror/_InternalHost → наружу (BLOCKED/DEAD)
    conn._pin = _vet_and_pin(hn, port)
    return conn


def _pinned_https_factory(host, **kw):
    hn, port = _split_hostport(host, 443)
    conn = _PinnedHTTPSConnection(host, **kw)
    conn._pin = _vet_and_pin(hn, port)
    return conn


class _PinnedHTTPHandler(urllib.request.HTTPHandler):
    def http_open(self, req):
        return self.do_open(_pinned_http_factory, req)


class _PinnedHTTPSHandler(urllib.request.HTTPSHandler):
    def https_open(self, req):
        return self.do_open(_pinned_https_factory, req, context=self._context)


_OPENER = None


def _opener():
    """Общий opener: TLS-верификация + запрет редиректов на внутренние хосты + IP-ПИННИНГ
    (коннект по проверенному IP закрывает DNS-rebinding TOCTOU, M5)."""
    global _OPENER
    if _OPENER is None:
        _OPENER = urllib.request.build_opener(
            _GuardedRedirect, _PinnedHTTPHandler(),
            _PinnedHTTPSHandler(context=ssl.create_default_context()))
    return _OPENER


def _fetch(url, timeout=15):
    if _host_is_internal(_url_host(url)):
        raise _InternalHost(url)  # SSRF: не ходим во внутреннюю сеть/метадату
    req = urllib.request.Request(_ascii_url(url), headers={"User-Agent": UA,
                                                           "Accept": "*/*",
                                                           "Accept-Language": "ru,en;q=0.8"})
    # TLS ВЕРИФИЦИРУЕМ (иначе MITM подменяет статус ссылки и обходит анти-фабрикацию);
    # редиректы на внутренние хосты режет _GuardedRedirect. Провал серта → check_url→TIMEOUT.
    with _opener().open(req, timeout=timeout) as r:
        body = r.read(131072)
        return r.status, body


_WORD = re.compile(r"[A-Za-zА-Яа-яЁё][A-Za-zА-Яа-яЁё\-]{3,}")
_STOP = {"http", "https", "href", "html", "статья", "источник", "ссылка", "документация",
         "проверено", "unverified", "arxiv", "verification"}


def content_match(line, body):
    """Совпадает ли контекстная строка (название/автор) с содержимым страницы.
    -> (score 0..1 | None если мало данных). Токены со скриптом (кириллица/латиница),
    отсутствующим на странице, не учитываются — страница на другом языке не штрафуется."""
    try:
        page = body.decode("utf-8", errors="replace").lower()
    except Exception:  # noqa: BLE001
        return None
    page = re.sub(r"<[^>]+>", " ", page)
    line = re.sub(r"https?://\S+", " ", line)
    toks = [t.lower() for t in _WORD.findall(line) if t.lower() not in _STOP]
    has_cyr = bool(re.search(r"[а-яё]", page))
    has_lat = bool(re.search(r"[a-z]", page))
    toks = [t for t in toks
            if (re.search(r"[а-яё]", t) and has_cyr) or
               (re.search(r"[a-z]", t) and has_lat)]
    if len(toks) < 4:
        return None
    hit = sum(1 for t in toks if t in page)
    return hit / len(toks)


def check_url(url, timeout=15, line=""):
    return _cass("url:" + url, lambda: _check_url_impl(url, timeout, line))


def _check_url_impl(url, timeout=15, line=""):
    try:
        status, body = _fetch(url, timeout)
        if 200 <= status < 300:
            cm = content_match(line, body) if line else None
            if cm is not None and cm < 0.2:
                return "MISMATCH", status  # живая страница, но не тот контент
            return "ALIVE", status
        return "SUSPECT", status
    except _InternalHost:
        return "BLOCKED", None  # внутренний хост: не проверяли — WARN, не фабрикация
    except urllib.error.HTTPError as e:
        if e.code in (401, 403, 405, 406, 429, 418):
            return "BLOCKED", e.code
        if e.code in (404, 410):
            return "DEAD", e.code
        return "SUSPECT", e.code
    except (socket.gaierror, ConnectionRefusedError):
        return "DEAD_HOST", None
    except urllib.error.URLError as e:
        reason = str(getattr(e, "reason", e))
        if isinstance(getattr(e, "reason", None), ssl.SSLError):
            return "TIMEOUT", None  # провал TLS → неопределённость, НЕ «жив»
        if "getaddrinfo" in reason or "Name or service not known" in reason:
            return "DEAD_HOST", None
        if "timed out" in reason.lower():
            return "TIMEOUT", None
        return "SUSPECT", None
    except socket.timeout:
        return "TIMEOUT", None
    except Exception:  # noqa: BLE001
        return "SUSPECT", None


def check_doi(doi, timeout=15):
    return _cass("doi:" + doi, lambda: _check_doi_impl(doi, timeout))


def _check_doi_impl(doi, timeout=15):
    """Handle-API doi.org: responseCode 1 = существует, 100 = нет."""
    api = "https://doi.org/api/handles/" + urllib.parse.quote(doi, safe="/.")
    try:
        req = urllib.request.Request(api, headers={"User-Agent": UA})
        with _opener().open(req, timeout=timeout) as r:  # TLS-verify + redirect-guard
            data = json.load(r)
        if data.get("responseCode") == 1:
            return "ALIVE", 200
        return "BAD_DOI", data.get("responseCode")
    except urllib.error.HTTPError as e:
        if e.code == 404:
            return "BAD_DOI", 404
        return "SUSPECT", e.code
    except Exception:  # noqa: BLE001
        return "TIMEOUT", None


FABRICATED = {"DEAD", "DEAD_HOST", "BAD_DOI", "BAD_PACKAGE", "BAD_VERSION"}
UNCERTAIN = {"BLOCKED", "TIMEOUT", "SUSPECT", "MISMATCH", "UNCHECKED", "OVERFLOW"}
# «скептик»: неопределённое = вето. OVERFLOW (не проверено из-за лимита) в strict тоже блокирует —
# иначе фабрикацию можно спрятать в хвост длинного списка ссылок (за отсечку max_checks).
STRICT_EXTRA = {"SUSPECT", "MISMATCH", "BLOCKED", "TIMEOUT", "OVERFLOW"}


def verify_text(text, timeout=15, workers=12, strict=False, pkgs=True, wayback=True,
                max_checks=150):
    """max_checks: лимит сетевых проверок за вызов (простыня с сотнями URL не должна «вешать»
    гейт на десятки минут) — покрывает реальные библиографии целиком. Сверхлимитные помечаются
    OVERFLOW (∈ uncertain → PASS_WITH_WARNINGS; в strict → блокирует, чтобы фабрикацию нельзя
    было спрятать в хвост за отсечкой)."""
    links = extract_links(text)
    pkg_items = extract_pkgs(text) if pkgs else []
    overflow = []
    total = len(links) + len(pkg_items)
    if total > max_checks:
        keep = max_checks - min(len(pkg_items), max_checks // 4)
        overflow = [("url", v, ln, mk) for _, v, ln, mk in links[keep:]] + \
                   [("pkg", "%s:%s%s" % (m, n, "==" + v if v else ""), ln, mk)
                    for m, n, v, ln, mk in pkg_items[max_checks - keep:]]
        links = links[:keep]
        pkg_items = pkg_items[:max_checks - keep]
    results = []

    def one(item):
        kind, val, line, marked = item
        if marked:
            return {"kind": kind, "value": val, "line": line,
                    "status": "MARKED", "code": None}
        ck = (kind, val, line)
        hit = _cache_get(ck)
        if hit is not None:
            return dict(hit, line=line)
        st, code = (check_doi(val, timeout) if kind == "doi"
                    else check_url(val, timeout, line=line))
        rec = {"kind": kind, "value": val, "line": line, "status": st, "code": code}
        # второй канал: Wayback спасает от анти-ботов и подтверждает «URL существовал»
        if wayback and kind == "url" and st in ("BLOCKED", "TIMEOUT", "DEAD", "DEAD_HOST"):
            ok, ts = check_wayback(val, timeout=min(timeout, 10))
            if ok:
                rec["status"] = "ARCHIVED"
                rec["archived_ts"] = ts
        return _cache_put(ck, rec)

    def one_pkg(item):
        mgr, name, ver, line, marked = item
        val = "%s:%s%s" % (mgr, name, "==" + ver if ver else "")
        if marked:
            return {"kind": "pkg", "value": val, "line": line,
                    "status": "MARKED", "code": None}
        ck = ("pkg", val)
        hit = _cache_get(ck)
        if hit is not None:
            return dict(hit, line=line)
        st, code = check_pkg(mgr, name, ver, timeout)
        return _cache_put(ck, {"kind": "pkg", "value": val, "line": line,
                               "status": st, "code": code})

    if links or pkg_items:
        with cf.ThreadPoolExecutor(max_workers=workers) as ex:
            futs = [ex.submit(one, it) for it in links] + \
                   [ex.submit(one_pkg, it) for it in pkg_items]
            results = [f.result() for f in futs]
    results += [{"kind": k, "value": v, "line": ln,
                 "status": "MARKED" if mk else "OVERFLOW", "code": None}
                for k, v, ln, mk in overflow]

    fabricated = [r for r in results if r["status"] in FABRICATED]
    uncertain = [r for r in results if r["status"] in UNCERTAIN]
    if strict:
        fabricated += [r for r in uncertain if r["status"] in STRICT_EXTRA]
    if not results:
        verdict = "NO_CLAIMS"
    elif fabricated:
        verdict = "VETO"
    elif uncertain:
        verdict = "PASS_WITH_WARNINGS"
    else:
        verdict = "PASS"
    return {"verdict": verdict,
            "n_links": len(results),
            "n_fabricated": len(fabricated),
            "n_uncertain": len(uncertain),
            "fabricated": fabricated,
            "results": results}


def main():
    ap = argparse.ArgumentParser(description="typed-VETO выхода: url/doi")
    ap.add_argument("file", help="файл с текстом результата (- = stdin)")
    ap.add_argument("--json", action="store_true")
    ap.add_argument("--strict", action="store_true",
                    help="SUSPECT тоже считать фабрикацией")
    ap.add_argument("--timeout", type=int, default=15)
    args = ap.parse_args()
    text = sys.stdin.read() if args.file == "-" else open(args.file, encoding="utf-8").read()
    rep = verify_text(text, timeout=args.timeout, strict=args.strict)
    if args.json:
        print(json.dumps(rep, ensure_ascii=False, indent=1))
    else:
        print("ВЕРДИКТ:", rep["verdict"],
              "| ссылок:", rep["n_links"],
              "| сфабриковано:", rep["n_fabricated"],
              "| неопределённых:", rep["n_uncertain"])
        for r in rep["fabricated"]:
            print("  [VETO] %s %s (%s) — %s" % (r["kind"], r["value"], r["status"], r["line"][:90]))
    sys.exit(0 if rep["verdict"] in ("PASS", "NO_CLAIMS") else
             (2 if rep["verdict"] == "VETO" else 1))


if __name__ == "__main__":
    main()
