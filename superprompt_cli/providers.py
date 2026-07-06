"""Единый chat()-вызов для любого провайдера. model_spec = 'провайдер/модель'
(модель может содержать '/'). Поддержка tool-calling: OpenAI-стиль и Anthropic."""
import json
import re
import time
import urllib.error
import urllib.parse
import urllib.request

from . import config


class ProviderError(RuntimeError):
    pass


class _StripAuthRedirect(urllib.request.HTTPRedirectHandler):
    """SSRF/утечка ключа: при редиректе на ДРУГОЙ хост убрать заголовки авторизации, иначе
    скомпрометированный/злонамеренный эндпоинт 302-нёт на attacker.tld и получит API-ключ
    (Authorization/x-api-key). Находка анализа [high/security]."""
    _AUTH = ("authorization", "x-api-key")

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        new = super().redirect_request(req, fp, code, msg, headers, newurl)
        if new is not None:
            same = urllib.parse.urlparse(newurl).hostname == urllib.parse.urlparse(req.full_url).hostname
            if not same:
                for h in list(new.headers) + list(getattr(new, "unredirected_hdrs", {})):
                    if h.lower() in self._AUTH:
                        new.headers.pop(h, None)
                        getattr(new, "unredirected_hdrs", {}).pop(h, None)
        return new


_OPENER = urllib.request.build_opener(_StripAuthRedirect)


def split_spec(spec, cfg):
    prov, _, model = spec.partition("/")
    if prov not in cfg["providers"]:
        raise ProviderError("неизвестный провайдер %r (есть: %s)" %
                            (prov, ", ".join(cfg["providers"])))
    return prov, model


def _post(url, body, headers, timeout=300, retries=3):
    last = None
    for attempt in range(retries):
        try:
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers=headers)
            with _OPENER.open(req, timeout=timeout) as r:   # opener срезает auth при смене хоста
                return json.load(r)
        except urllib.error.HTTPError as e:
            last = "HTTP %s: %s" % (e.code, e.read().decode()[:400])
            if e.code in (429, 500, 502, 503, 529):
                retry_after = e.headers.get("Retry-After")
                try:
                    wait = min(60, float(retry_after)) if retry_after else 4 * (attempt + 1)
                except ValueError:
                    wait = 4 * (attempt + 1)
                time.sleep(wait)
                continue
            raise ProviderError(last)
        except urllib.error.URLError as e:
            # мёртвый провайдер (refused/DNS) — fail-fast, ретраи бессмысленны
            reason = getattr(e, "reason", e)
            if isinstance(reason, (ConnectionRefusedError, OSError)) and \
                    ("refused" in str(reason).lower() or "getaddrinfo" in str(reason)
                     or "Name or service not known" in str(reason)):
                raise ProviderError("провайдер недоступен: %s" % str(reason)[:200])
            last = str(e)[:400]
            time.sleep(2 * (attempt + 1))
        except Exception as e:  # noqa: BLE001
            last = str(e)[:400]
            time.sleep(2 * (attempt + 1))
    raise ProviderError(last or "нет ответа")


def chat(spec, messages, tools=None, max_tokens=4096, temperature=0.2, cfg=None,
         timeout=300, json_mode=False):
    """Возвращает {'text', 'tool_calls':[{id,name,args}], 'usage', 'raw'}.
    json_mode=True — попросить провайдера СТРУКТУРИРОВАННЫЙ JSON (harness-eng П.10: убрать
    хрупкий парсинг «сырого» текста у судей). Не поддержано провайдером → тихий фолбэк на
    обычный вывод (парсинг через parse_json остаётся устойчивым)."""
    cfg = cfg or config.load()
    prov_name, model = split_spec(spec, cfg)
    prov = cfg["providers"][prov_name]
    key = config.resolve_key(prov)
    if not key:
        raise ProviderError("нет ключа для %s: задайте %s или api_key_file" %
                            (prov_name, prov.get("api_key_env")))
    if prov.get("style") == "anthropic":
        return _chat_anthropic(prov, key, model, messages, tools, max_tokens,
                               temperature, timeout)
    return _chat_openai(prov, key, model, messages, tools, max_tokens,
                        temperature, timeout, json_mode)


def parse_json(text, default=None):
    """Устойчиво извлечь JSON-объект из ответа судьи. Порядок: чистый json.loads → извлечение
    первого {...} → default. Не бросает (fail-closed на стороне вызывающего)."""
    if not text:
        return default
    s = text.strip()
    if s.startswith("```"):                       # ```json ... ``` обёртка
        s = re.sub(r"^```(?:json)?\s*|\s*```$", "", s)
    try:
        return json.loads(s)
    except ValueError:
        pass
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        try:
            return json.loads(m.group(0))
        except ValueError:
            pass
    return default


def _safe_args(s):
    """Модели порой выдают битый JSON в аргументах — не роняем цикл."""
    try:
        return json.loads(s or "{}")
    except ValueError as e:
        return {"__parse_error": "аргументы не распарсились как JSON: %s" % e,
                "__raw": (s or "")[:2000]}


def _chat_openai(prov, key, model, messages, tools, max_tokens, temperature,
                 timeout=300, json_mode=False):
    body = {"model": model, "messages": messages,
            "max_tokens": max_tokens, "temperature": temperature}
    if tools:
        body["tools"] = [{"type": "function", "function": t} for t in tools]
    if json_mode and not tools:                   # структурный JSON у судьи (П.10)
        body["response_format"] = {"type": "json_object"}
    url = prov["base_url"].rstrip("/") + "/chat/completions"
    headers = {"Authorization": "Bearer " + key, "Content-Type": "application/json"}
    try:
        data = _post(url, body, headers, timeout=timeout)
    except ProviderError:
        if "response_format" in body:             # эндпоинт не принял json-mode → без него
            body.pop("response_format")
            data = _post(url, body, headers, timeout=timeout)
        else:
            raise
    # многие OpenAI-совместимые шлюзы отдают ОШИБКУ телом с кодом 200 → без "choices".
    # Валидируем структуру и бросаем ProviderError (её ловят вызывающие), а не роняем CLI.
    if not isinstance(data, dict) or not data.get("choices"):
        raise ProviderError("некорректный ответ провайдера: %.200s"
                            % str(data.get("error") if isinstance(data, dict) else data))
    msg = data["choices"][0].get("message")
    if not isinstance(msg, dict):
        raise ProviderError("ответ провайдера без message: %.200s" % str(data))
    text = msg.get("content") or ""
    calls = [{"id": tc.get("id", "call_%d" % i),
              "name": tc["function"]["name"],
              "args": _safe_args(tc["function"].get("arguments"))}
             for i, tc in enumerate(msg.get("tool_calls") or [])]
    return {"text": text, "tool_calls": calls, "usage": data.get("usage", {}),
            "raw": msg}


def _chat_anthropic(prov, key, model, messages, tools, max_tokens, temperature,
                    timeout=300):
    sys_txt = "\n".join(m["content"] for m in messages if m["role"] == "system")
    conv = []
    for m in messages:
        if m["role"] == "system":
            continue
        if m["role"] == "tool":
            conv.append({"role": "user", "content": [{
                "type": "tool_result", "tool_use_id": m["tool_call_id"],
                "content": str(m["content"])[:30000]}]})
        elif m["role"] == "assistant" and m.get("tool_calls"):
            blocks = [{"type": "text", "text": m.get("content") or ""}] if m.get("content") else []
            for tc in m["tool_calls"]:
                blocks.append({"type": "tool_use", "id": tc["id"],
                               "name": tc["function"]["name"],
                               "input": _safe_args(tc["function"].get("arguments"))})
            conv.append({"role": "assistant", "content": blocks})
        else:
            conv.append({"role": m["role"], "content": m["content"]})
    body = {"model": model, "max_tokens": max_tokens, "temperature": temperature,
            "messages": conv}
    if sys_txt:
        body["system"] = sys_txt
    if tools:
        body["tools"] = [{"name": t["name"], "description": t["description"],
                          "input_schema": t["parameters"]} for t in tools]
    data = _post(prov["base_url"].rstrip("/") + "/v1/messages", body,
                 {"x-api-key": key, "anthropic-version": "2023-06-01",
                  "Content-Type": "application/json"}, timeout=timeout)
    if isinstance(data, dict) and data.get("error") and not data.get("content"):
        raise ProviderError("некорректный ответ провайдера: %.200s" % str(data.get("error")))
    text, calls = "", []
    for block in data.get("content", []):
        if block["type"] == "text":
            text += block["text"]
        elif block["type"] == "tool_use":
            calls.append({"id": block["id"], "name": block["name"],
                          "args": block["input"]})
    return {"text": text, "tool_calls": calls, "usage": data.get("usage", {}),
            "raw": data}
