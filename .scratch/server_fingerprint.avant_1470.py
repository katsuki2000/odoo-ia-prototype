"""Empreinte du serveur d'inference : permet de comparer des mesures a serveur constant.

Les reponses de l'arbitre changent d'une session de serveur a l'autre (journal 1467) ; une
mesure n'est comparable a une autre que si l'empreinte est la meme. L'empreinte ne prouve pas
l'identite du serveur : elle detecte les changements visibles par l'API (modele servi,
metadonnees du modele, `system_fingerprint`). Ne leve jamais d'exception ; ne contient ni URL
ni cle d'API (l'hote du endpoint n'apparait que sous forme hachee).
"""

import hashlib
import json
import time
from typing import Any, Dict, Optional
from urllib.parse import urlparse

_CANARY_PROMPT = "1"
_META_KEYS = ("created", "owned_by", "max_model_len", "root")


def _short_hash(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()[:12]


def _host_hash(base_url: Optional[str]) -> Optional[str]:
    if not base_url:
        return None
    return _short_hash(urlparse(base_url).netloc or base_url)


def _model_entry(item: Any) -> Dict[str, Any]:
    data = item.model_dump() if hasattr(item, "model_dump") else dict(getattr(item, "__dict__", {}) or {})
    entry = {"id": data.get("id")}
    for key in _META_KEYS:
        if data.get(key) is not None:
            entry[key] = data[key]
    return entry


def compute_fingerprint_id(fingerprint: Dict[str, Any]) -> str:
    """Hash des seuls champs qui caracterisent le modele servi.

    Exclut l'hote du endpoint et l'horodatage : un tunnel qui redemarre change l'adresse sans
    changer le modele, et inversement un meme tag peut changer de contenu (d'ou `created`,
    `max_model_len` et `system_fingerprint` quand le serveur les fournit).
    """
    llm = fingerprint.get("llm") or {}
    stable = {
        "provider": llm.get("provider"),
        "configured_model": llm.get("configured_model"),
        "served_models": llm.get("served_models"),
        "canary_model": (llm.get("canary") or {}).get("model"),
        "canary_system_fingerprint": (llm.get("canary") or {}).get("system_fingerprint"),
        "embedding_backend": (fingerprint.get("embedding") or {}).get("backend"),
        "embedding_model": (fingerprint.get("embedding") or {}).get("configured_model"),
    }
    return _short_hash(json.dumps(stable, sort_keys=True, ensure_ascii=False, default=str))


def get_inference_fingerprint(
    *,
    provider: Optional[str] = None,
    base_url: Optional[str] = None,
    model: Optional[str] = None,
    api_key: Optional[str] = None,
    embedding_backend: Optional[str] = None,
    embedding_model: Optional[str] = None,
    client: Any = None,
    timeout: float = 20.0,
) -> Dict[str, Any]:
    """Interroge le serveur (liste des modeles + un appel d'un token) et retourne l'empreinte."""
    from config import settings

    provider = provider or settings.LLM_PROVIDER or "local"
    base_url = base_url or settings.LOCAL_LLM_BASE_URL
    model = model or settings.LOCAL_LLM_MODEL
    llm: Dict[str, Any] = {"provider": provider, "configured_model": model, "endpoint_hash": _host_hash(base_url)}
    result: Dict[str, Any] = {
        "probed_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "llm": llm,
        "embedding": {
            "backend": embedding_backend or settings.EMBEDDING_BACKEND,
            "configured_model": embedding_model or settings.LOCAL_EMBEDDING_MODEL,
            "endpoint_hash": _host_hash(getattr(settings, "LOCAL_EMBEDDING_BASE_URL", None)),
        },
    }
    stage = "client"
    try:
        if client is None:
            from openai import OpenAI
            client = OpenAI(base_url=base_url, api_key=api_key or settings.LOCAL_LLM_API_KEY, timeout=timeout, max_retries=0)
        stage = "models"
        try:  # certains serveurs d'inference n'exposent pas /models : non bloquant
            llm["served_models"] = sorted((_model_entry(m) for m in client.models.list().data), key=lambda e: str(e.get("id")))
        except Exception as error:  # noqa: BLE001
            llm["models_error"] = type(error).__name__
        stage = "canary"
        reply = client.chat.completions.create(
            model=model, messages=[{"role": "user", "content": _CANARY_PROMPT}], max_tokens=1, temperature=0)
        llm["canary"] = {"model": getattr(reply, "model", None), "system_fingerprint": getattr(reply, "system_fingerprint", None)}
    except Exception as error:  # noqa: BLE001 - l'empreinte ne doit jamais interrompre une mesure
        llm["error"] = type(error).__name__
        llm["error_stage"] = stage
    result["fingerprint_id"] = compute_fingerprint_id(result)
    result["reachable"] = "error" not in llm
    return result


def describe(fingerprint: Dict[str, Any]) -> str:
    llm = fingerprint.get("llm") or {}
    canary = llm.get("canary") or {}
    state = f"en erreur ({llm.get('error')} a l'etape {llm.get('error_stage')})" if llm.get("error") else "ok"
    return (f"serveur {fingerprint.get('fingerprint_id')} | modele configure={llm.get('configured_model')} | "
            f"modele servi={canary.get('model')} | system_fingerprint={canary.get('system_fingerprint')} | "
            f"embeddings={(fingerprint.get('embedding') or {}).get('configured_model')} | {state}")
