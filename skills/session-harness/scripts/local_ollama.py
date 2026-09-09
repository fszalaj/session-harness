"""Bounded text with installed local Ollama models and durable task receipts."""
import argparse
import hashlib
import http.client
import json
import os
from pathlib import Path
import queue
import re
import sys
import threading
import time

from api_transport import APIError, decode_json
from quota import Ledger

ID = re.compile(r'[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z')
MODEL = re.compile(r'[A-Za-z0-9][A-Za-z0-9_./:-]{0,199}\Z')


def request(path, body=None, *, deadline):
    remaining = deadline - time.monotonic()
    if remaining <= 0:
        raise APIError('local_timeout')
    connection = http.client.HTTPConnection('127.0.0.1', 11434, timeout=remaining)
    result = queue.Queue(maxsize=1)

    def read():
        try:
            encoded = json.dumps(body).encode() if body is not None else None
            connection.request('POST' if body is not None else 'GET', path, encoded,
                               {'Content-Type': 'application/json'})
            response = connection.getresponse()
            if response.status != 200:
                raise APIError('local_http_error', response.status)
            chunks, size = [], 0
            while True:
                left = deadline - time.monotonic()
                if left <= 0:
                    raise APIError('local_timeout')
                if connection.sock is not None:
                    connection.sock.settimeout(left)
                chunk = response.read1(min(65536, 2_000_001 - size))
                size += len(chunk)
                if size > 2_000_000:
                    raise APIError('local_response_too_large')
                if not chunk:
                    break
                chunks.append(chunk)
            result.put((True, decode_json(b''.join(chunks))))
        except Exception as exc:
            result.put((False, exc if isinstance(exc, APIError) else APIError('local_transport_error')))
        finally:
            connection.close()

    threading.Thread(target=read, daemon=True).start()
    try:
        ok, value = result.get(timeout=max(.001, deadline - time.monotonic()))
        if not ok:
            raise value
        return value
    except queue.Empty:
        raise APIError('local_timeout') from None
    finally:
        connection.close()


def local_record(row, name):
    if not isinstance(row, dict) or not isinstance(name, str) or not MODEL.fullmatch(name):
        return False
    if name.endswith((':cloud', '-cloud')):
        return False
    details = row.get('details', {})
    return (isinstance(details, dict) and not any(
        key in value for value in (row, details) for key in ('remote_host', 'remote_model')))


def models(deadline):
    rows = request('/api/tags', deadline=deadline).get('models')
    if not isinstance(rows, list):
        raise APIError('local_catalog_invalid')
    result = []
    for row in rows:
        name = row.get('name') if isinstance(row, dict) else None
        if (local_record(row, name) and type(row.get('size')) is int and row['size'] > 0
                and isinstance(row.get('digest'), str)
                and re.fullmatch(r'(?:sha256:)?[0-9a-f]{64}', row['digest'])):
            result.append({'id': name, 'digest': row['digest'], 'size': row['size']})
    if len({m['id'] for m in result}) != len(result):
        raise APIError('local_catalog_invalid')
    return result


def execute(identifier, model, prompt, *, max_output_tokens=256, timeout=180, ledger=None):
    if os.environ.get('SESSION_HARNESS_LEAF'):
        raise APIError('recursion_blocked')
    if (not isinstance(identifier, str) or not ID.fullmatch(identifier)
            or not isinstance(model, str) or not MODEL.fullmatch(model)
            or not isinstance(prompt, str) or not prompt.strip() or len(prompt.encode()) > 16384
            or type(timeout) not in (int, float) or not 1 <= timeout <= 180
            or type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 4096):
        raise APIError('local_request_invalid')
    ledger = ledger or Ledger(Path.home() / '.local/state/session-harness/local-jobs.sqlite3')
    body = {'model': model, 'messages': [{'role': 'user', 'content': prompt}], 'stream': False,
            'keep_alive': 0, 'options': {'num_predict': max_output_tokens}}
    fingerprint = hashlib.sha256(json.dumps(body, sort_keys=True).encode()).hexdigest()
    with ledger._connect() as db:
        db.execute('CREATE TABLE IF NOT EXISTS local_jobs (id TEXT PRIMARY KEY, fingerprint TEXT NOT NULL, receipt TEXT)')
        previous = db.execute('SELECT fingerprint,receipt FROM local_jobs WHERE id=?', (identifier,)).fetchone()
        if previous:
            if previous[0] != fingerprint:
                raise APIError('local_request_id_conflict')
            return {'status': 'duplicate_accounting_only', 'receipt': json.loads(previous[1]) if previous[1] else None}
    start = time.monotonic()
    deadline = start + timeout
    available = models(deadline)
    if not any(row['id'] == model for row in available):
        raise APIError('local_model_not_installed')
    inspected = request('/api/show', {'model': model}, deadline=deadline)
    info = inspected.get('model_info', {})
    if (not local_record(inspected, model) or not isinstance(info, dict)
            or not isinstance(info.get('general.architecture'), str)
            or type(info.get('general.parameter_count')) is not int or info['general.parameter_count'] <= 0):
        raise APIError('local_model_residency_unverified')
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('SELECT 1 FROM local_jobs WHERE id=?', (identifier,)).fetchone():
            raise APIError('local_request_already_claimed')
        if db.execute('SELECT 1 FROM local_jobs WHERE receipt IS NULL').fetchone():
            raise APIError('local_request_unresolved')
        db.execute('INSERT INTO local_jobs VALUES (?,?,NULL)', (identifier, fingerprint))
    data = request('/api/chat', body, deadline=deadline)
    message = data.get('message')
    if (data.get('model') != model or data.get('done') is not True
            or data.get('done_reason') not in {'stop', 'length'} or not local_record(data, model)
            or not isinstance(message, dict) or message.get('role') != 'assistant'
            or message.get('tool_calls') or not isinstance(message.get('content'), str)
            or not message['content'].strip()
            or type(data.get('prompt_eval_count')) is not int or data['prompt_eval_count'] < 0
            or type(data.get('eval_count')) is not int or not 0 <= data['eval_count'] <= max_output_tokens):
        raise APIError('local_response_unverified')
    receipt = {'status': 'completed', 'request_id': identifier, 'billing_scope': 'local:ollama',
               'actual_model': model, 'prompt_tokens': data['prompt_eval_count'],
               'completion_tokens': data['eval_count'], 'elapsed_seconds': time.monotonic() - start,
               'automatic_retry': False, 'requires_manager_inspection': True, 'independent_judgment': False}
    with ledger._connect() as db:
        db.execute('UPDATE local_jobs SET receipt=? WHERE id=? AND receipt IS NULL', (json.dumps(receipt), identifier))
    return {**receipt, 'text': message['content']}


def reconcile(identifier, *, confirmed, ledger=None):
    if confirmed is not True or not isinstance(identifier, str) or not ID.fullmatch(identifier):
        raise APIError('local_stop_confirmation_required')
    ledger = ledger or Ledger(Path.home() / '.local/state/session-harness/local-jobs.sqlite3')
    receipt = {'status': 'reconciled', 'request_id': identifier, 'billing_scope': 'local:ollama',
               'usage': 'unknown', 'stopped_confirmation': 'user', 'automatic_retry': False}
    with ledger._connect() as db:
        db.execute('BEGIN IMMEDIATE')
        if db.execute('UPDATE local_jobs SET receipt=? WHERE id=? AND receipt IS NULL',
                      (json.dumps(receipt), identifier)).rowcount != 1:
            raise APIError('local_request_not_unresolved')
    return receipt


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest='command', required=True)
    sub.add_parser('models')
    recover = sub.add_parser('reconcile', help='Record that the timed-out local generation has stopped')
    recover.add_argument('--id', required=True)
    recover.add_argument('--confirm-stopped', action='store_true')
    run = sub.add_parser('run')
    run.add_argument('--id', required=True)
    run.add_argument('--model', required=True)
    run.add_argument('--max-output-tokens', type=int, default=256)
    run.add_argument('--timeout', type=float, default=180)
    args = parser.parse_args(argv)
    try:
        if args.command == 'models':
            result = {'status': 'local_catalog', 'models': models(time.monotonic() + 15)}
        elif args.command == 'reconcile':
            result = reconcile(args.id, confirmed=args.confirm_stopped)
        else:
            result = execute(args.id, args.model, sys.stdin.buffer.read(16385).decode('utf-8'),
                             max_output_tokens=args.max_output_tokens, timeout=args.timeout)
        print(json.dumps(result))
        return 0
    except (APIError, ValueError, OSError) as exc:
        print(json.dumps({'status': getattr(exc, 'status', 'local_execution_blocked'), 'automatic_retry': False}))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
