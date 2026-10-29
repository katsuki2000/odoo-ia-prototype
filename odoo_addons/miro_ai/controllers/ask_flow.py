# -*- coding: utf-8 -*-
"""Requester API key, JWT and backend headers of the MIRO AI ask flow."""
import base64
import hashlib
import hmac
import json
import logging
import re
import time
from datetime import timedelta

from odoo import fields
from odoo.osv.expression import OR

_logger = logging.getLogger(__name__)

KEY_PREFIX = "MIRO AI - "
STALE_KEY_SECONDS = 3600
JWT_LIFETIME_SECONDS = 300
JOB_ID_RE = re.compile(r"[0-9a-f]{32}")


def generate_jwt_token(payload_dict, secret_key):
    """Build an HS256 JWT with the standard library only."""
    header = {"alg": "HS256", "typ": "JWT"}

    def b64url_encode(data_bytes):
        return base64.urlsafe_b64encode(data_bytes).rstrip(b'=').decode('ascii')

    encoded_header = b64url_encode(json.dumps(header, separators=(',', ':')).encode('utf-8'))
    encoded_payload = b64url_encode(json.dumps(payload_dict, separators=(',', ':')).encode('utf-8'))

    signing_input = f"{encoded_header}.{encoded_payload}".encode('ascii')
    signature = hmac.new(secret_key.encode('utf-8'), signing_input, hashlib.sha256).digest()
    encoded_signature = b64url_encode(signature)

    return f"{encoded_header}.{encoded_payload}.{encoded_signature}"


def is_job_id(value):
    return isinstance(value, str) and JOB_ID_RE.fullmatch(value) is not None


def requester_scope(env):
    return env.company.id, [group.id for group in env.user.groups_id]


def backend_headers(secret_key, user, company_id, groups, api_key=None):
    payload = {
        "sub": str(user.id),
        "uid": user.id,
        "login": user.login,
        "company_id": company_id,
        "db": user.env.cr.dbname,
        "groups": groups,
        "api_key": api_key,
        "is_admin": user.has_group('base.group_system'),
        "exp": int(time.time()) + JWT_LIFETIME_SECONDS,
    }
    return {
        "Authorization": f"Bearer {generate_jwt_token(payload, secret_key)}",
        "Content-Type": "application/json",
    }


def issue_requester_key(env, job_id):
    """Ephemeral API key of the current user: the backend reads Odoo under the requester's own rights."""
    try:
        api_key = env['res.users.apikeys']._generate(None, KEY_PREFIX + job_id)
        # The backend calls Odoo back with its own cursor: under READ COMMITTED it only sees a committed key.
        env.cr.commit()
        return api_key
    except Exception:
        _logger.exception("MIRO AI: API key generation failed for uid=%s", env.uid)
        return None


def revoke_requester_keys(env, job_id=None):
    """Remove the key of a finished job and every MIRO AI key older than STALE_KEY_SECONDS."""
    stale = [
        ('name', '=like', f"{KEY_PREFIX}%"),
        ('create_date', '<', fields.Datetime.now() - timedelta(seconds=STALE_KEY_SECONDS)),
    ]
    domain = OR([[('name', '=', KEY_PREFIX + job_id)], stale]) if job_id else stale
    try:
        env['res.users.apikeys'].sudo().search(domain)._remove()
        env.cr.commit()
    except Exception as error:
        _logger.warning("MIRO AI: API key revocation failed: %s", error)
        env.cr.rollback()
