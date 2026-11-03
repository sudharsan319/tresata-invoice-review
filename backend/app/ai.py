"""Task-specific OpenRouter calls, private local settings, and usage records.

This module proposes structured interpretations. It has no approval/payment tools.
"""
from __future__ import annotations

import hashlib
import json
import os
import re
import tempfile
import threading
import time
from datetime import datetime
from pathlib import Path

import httpx
from pydantic import BaseModel, ConfigDict, Field, SecretStr

from . import store, progress

TASKS = ('extraction', 'vision', 'matching', 'policy', 'review')
BASE_URL = 'https://openrouter.ai/api/v1'
DEFAULT_MODELS = {
    'extraction': 'mistralai/mistral-nemo',
    'vision': 'google/gemma-3-12b-it',
    'matching': 'mistralai/mistral-small-24b-instruct-2501',
    'policy': 'mistralai/mistral-small-24b-instruct-2501',
    'review': 'mistralai/mistral-nemo',
}
_settings_lock = threading.RLock()
_catalog = {'at': 0.0, 'models': []}


class AISettingsUpdate(BaseModel):
    model_config = ConfigDict(extra='forbid')
    enabled: bool
    api_key: SecretStr | None = None
    remove_api_key: bool = False
    models: dict[str, str] = Field(default_factory=lambda: dict(DEFAULT_MODELS))
    vision_enabled: bool = True
    matching_enabled: bool = True
    max_vision_pages: int = Field(default=6, ge=1, le=15)
    max_output_tokens: int = Field(default=6000, ge=512, le=16000)
    timeout_seconds: int = Field(default=90, ge=15, le=180)


class AIError(ValueError):
    """A deliberately sanitized provider error safe for UI/audit records."""


def settings_path() -> Path:
    return store.DATA / 'ai-settings.json'


def settings() -> dict:
    # File settings take precedence over environment defaults, including disabling
    # AI even when an environment key exists. No keys enter workspace state.
    legacy = bool(os.getenv('AI_BASE_URL') and os.getenv('AI_MODEL'))
    key = os.getenv('OPENROUTER_API_KEY') or os.getenv('AI_API_KEY', '')
    result = {
        'enabled': bool(key or legacy), 'api_key': key,
        'base_url': os.getenv('AI_BASE_URL', BASE_URL),
        'models': {task: os.getenv('AI_' + task.upper() + '_MODEL') or os.getenv('AI_MODEL') or default for task, default in DEFAULT_MODELS.items()},
        'vision_enabled': True, 'matching_enabled': True, 'max_vision_pages': 6,
        'max_output_tokens': 6000, 'timeout_seconds': 90,
    }
    with _settings_lock:
        try:
            saved = json.loads(settings_path().read_text())
        except FileNotFoundError:
            return result
        except (ValueError, OSError):
            return {**result, 'enabled': False}
        result.update({k: v for k, v in saved.items() if k != 'models'})
        result['models'].update(saved.get('models', {}))
    return result


def enabled() -> bool:
    config = settings()
    return bool(config['enabled'] and (config['api_key'] or config['base_url'] != BASE_URL))


def public_settings() -> dict:
    config = settings()
    return {k: v for k, v in config.items() if k not in ('api_key', 'base_url')} | {
        'key_configured': bool(config['api_key']), 'ready': enabled(),
        'provider': 'OpenRouter' if 'openrouter.ai' in config['base_url'] else 'Configured compatible provider',
        'defaults': DEFAULT_MODELS,
    }


def save_settings(update: AISettingsUpdate) -> dict:
    if set(update.models) != set(TASKS):
        raise AIError('Select a model for every AI task.')
    if any(not re.fullmatch(r'[A-Za-z0-9~][A-Za-z0-9_./:+~\-]{1,180}', model) for model in update.models.values()):
        raise AIError('Use model IDs from the OpenRouter model catalogue.')
    with _settings_lock:
        previous = settings()
        key = '' if update.remove_api_key else previous['api_key']
        if update.api_key and update.api_key.get_secret_value().strip():
            key = update.api_key.get_secret_value().strip()
            if len(key) > 512 or re.search(r'\s', key):
                raise AIError('The API key must be a single value without spaces.')
        if update.enabled and not key:
            raise AIError('Enter your OpenRouter API key before enabling AI.')
        payload = update.model_dump(exclude={'api_key', 'remove_api_key'}) | {'api_key': key, 'base_url': BASE_URL}
        store.DATA.mkdir(parents=True, exist_ok=True)
        descriptor, temporary = tempfile.mkstemp(prefix='.ai-settings-', dir=store.DATA)
        try:
            os.fchmod(descriptor, 0o600)
            with os.fdopen(descriptor, 'w') as file:
                json.dump(payload, file)
            os.replace(temporary, settings_path())
        finally:
            if Path(temporary).exists():
                Path(temporary).unlink()
    return public_settings()


def config_fingerprint(task: str) -> str:
    config = settings()
    # Never include or expose the API key in prompts, fingerprints, or logs.
    return hashlib.sha256(json.dumps({'task': task, 'model': config['models'][task], 'enabled': enabled(),
                                     'vision_enabled': config['vision_enabled'], 'matching_enabled': config['matching_enabled'],
                                     'prompt_version': 2}, sort_keys=True).encode()).hexdigest()


def object_schema(properties: dict) -> dict:
    return {'type': 'object', 'properties': properties, 'required': list(properties), 'additionalProperties': False}


def catalog() -> list[dict]:
    if _catalog['models'] and time.monotonic() - _catalog['at'] < 900:
        return _catalog['models']
    try:
        response = httpx.get(BASE_URL + '/models', timeout=20)
        response.raise_for_status()
        models = []
        for model in response.json()['data']:
            modalities = model.get('architecture', {}).get('input_modalities', [])
            params = model.get('supported_parameters', [])
            if 'text' not in modalities or 'response_format' not in params or 'structured_outputs' not in params:
                continue
            models.append({'id': model['id'], 'name': model['name'], 'vision': 'image' in modalities,
                           'structured_outputs': 'structured_outputs' in params,
                           'supported_parameters': params,
                           'context_length': model.get('context_length'),
                           'input_per_million': str(float(model.get('pricing', {}).get('prompt', '0')) * 1_000_000),
                           'output_per_million': str(float(model.get('pricing', {}).get('completion', '0')) * 1_000_000)})
        _catalog.update(at=time.monotonic(), models=sorted(models, key=lambda item: item['name']))
        return _catalog['models']
    except (httpx.HTTPError, ValueError, KeyError, TypeError) as exc:
        raise AIError('Could not load the OpenRouter model catalogue. You can still enter an exact model ID.') from exc


def test_connection() -> dict:
    config = settings()
    if not config['api_key']:
        raise AIError('Save an OpenRouter API key first.')
    try:
        response = httpx.get(BASE_URL + '/key', headers={'Authorization': 'Bearer ' + config['api_key']}, timeout=20)
        response.raise_for_status()
        data = response.json()['data']
        return {'ok': True, 'message': 'OpenRouter key verified. No paid model call was made.',
                'limit_remaining': data.get('limit_remaining'), 'is_free_tier': data.get('is_free_tier')}
    except AIError:
        raise
    except httpx.HTTPStatusError as exc:
        raise AIError('OpenRouter rejected the key. Check that it is active and has the required access.') from exc
    except (httpx.HTTPError, ValueError, KeyError) as exc:
        raise AIError('OpenRouter connection could not be verified. Check your connection and try again.') from exc


def complete(task: str, system: str, content, schema: dict | None = None, *, max_tokens: int | None = None) -> tuple[dict, dict]:
    config = settings()
    if not enabled():
        raise AIError('AI is not enabled. Add your OpenRouter key in AI models settings.')
    model = config['models'][task]
    body = {'model': model, 'temperature': 0, 'max_tokens': max_tokens or config['max_output_tokens'],
            'messages': [{'role': 'system', 'content': system}, {'role': 'user', 'content': content}]}
    known_model = next((item for item in _catalog['models'] if item['id'] == model), None)
    if known_model and 'temperature' not in known_model.get('supported_parameters', ['temperature']):
        body.pop('temperature', None)
    if schema is not None:
        body['response_format'] = {'type': 'json_schema', 'json_schema': {'name': 'invoices_' + task, 'strict': True, 'schema': schema}}
    else:
        body['response_format'] = {'type': 'json_object'}
    if 'openrouter.ai' in config['base_url']:
        body['provider'] = {'require_parameters': True}
    headers = {'Content-Type': 'application/json', 'X-OpenRouter-Title': 'Invoices Local AP Review'}
    if config['api_key']:
        headers['Authorization'] = 'Bearer ' + config['api_key']
    progress.emit('ai', 'running', f'AI {task}', f'Calling {model}. Waiting for the provider response.', task=task, model=model)
    started = time.monotonic()
    try:
        response = httpx.post(config['base_url'].rstrip('/') + '/chat/completions', headers=headers, json=body, timeout=config['timeout_seconds'])
        response.raise_for_status()
        payload = response.json()
        choice = payload['choices'][0]
        if choice.get('finish_reason') == 'length':
            raise AIError(f'{task.capitalize()} response reached its token limit; use a larger output limit or smaller document.')
        raw = choice['message']['content']
        if not isinstance(raw, str):
            raise AIError('The model returned no usable JSON content.')
        raw = re.sub(r'^```(?:json)?\s*|\s*```$', '', raw.strip())
        parsed = json.loads(raw)
        if not isinstance(parsed, dict):
            raise AIError('The model response was not a JSON object.')
        usage = payload.get('usage') or {}
        record = {'task': task, 'model': payload.get('model', model), 'status': 'completed',
                  'timestamp': datetime.now().astimezone().isoformat(), 'duration_ms': round((time.monotonic() - started) * 1000),
                  'prompt_tokens': usage.get('prompt_tokens', 0), 'completion_tokens': usage.get('completion_tokens', 0),
                  'cost_usd': usage.get('cost'), 'request_id': payload.get('id', '')}
        progress.emit('ai', 'completed', f'AI {task} response received', 'Structured response received; application validation follows.', task=task, model=record['model'], duration_ms=record['duration_ms'], prompt_tokens=record['prompt_tokens'], completion_tokens=record['completion_tokens'])
        return parsed, record
    except AIError:
        raise
    except httpx.HTTPStatusError as exc:
        code = exc.response.status_code
        explanation = {401: 'API key was rejected', 402: 'insufficient credits or key spending limit',
                       429: 'rate limit reached', 400: 'model or structured-output settings are unsupported',
                       404: 'model or endpoint was not found'}.get(code, 'provider could not complete the request')
        raise AIError(f'OpenRouter {task}: {explanation} (HTTP {code}).') from exc
    except httpx.TimeoutException as exc:
        raise AIError(f'OpenRouter {task} timed out; local checks remain available.') from exc
    except httpx.HTTPError as exc:
        raise AIError(f'OpenRouter {task} connection failed; local checks remain available.') from exc
    except (ValueError, KeyError, IndexError, TypeError) as exc:
        raise AIError(f'OpenRouter {task} returned invalid structured data; its response was not used.') from exc


def failure_record(task: str, message: str) -> dict:
    progress.emit('ai', 'warning', f'AI {task} unavailable or rejected', message, task=task, model=settings()['models'][task])
    return {'task': task, 'model': settings()['models'][task], 'status': 'failed',
            'timestamp': datetime.now().astimezone().isoformat(), 'message': message}
