"""Secret redaction pass tests (issue #11, PRD §16).

Covers the pure ``masking`` module (each secret class, idempotency, both record
fields) and the CLI contract that parsing masks by default while ``--no-mask``
emits raw text verbatim.
"""

from __future__ import annotations

import io
import json
from pathlib import Path

from funcviz import cli
from funcviz.models import LogRecord
from funcviz.parser import mask_records, mask_text

ROOT = Path(__file__).resolve().parent.parent
SUCCESS_LOG = ROOT / "samples" / "success.log"
WORKER_FAIL_LOG = ROOT / "samples" / "worker-fail.log"


def test_masks_quoted_json_header_forms():
    cases = {
        '"Authorization": "Bearer eyJ.abc.def"': (
            '"Authorization": "Bearer [REDACTED:bearer-token]"'
        ),
        '"Authorization": "Basic dXNlcjpwYXNz"': '"Authorization": "Basic [REDACTED:basic-auth]"',
        '"x-functions-key": "secretkey123"': '"x-functions-key": "[REDACTED:function-key]"',
        "'Authorization': 'Bearer tok'": "'Authorization': 'Bearer [REDACTED:bearer-token]'",
    }
    for raw, expected in cases.items():
        assert mask_text(raw) == expected, raw


def test_masks_generic_authorization_scheme_with_spaces():
    cases = {
        "Authorization: ApiKey secret123": "Authorization: [REDACTED:authorization]",
        '"Authorization": "ApiKey secret123"': '"Authorization": "[REDACTED:authorization]"',
        'Authorization: Digest username="u", response="secretsig"': (
            "Authorization: [REDACTED:authorization]"
        ),
    }
    for raw, expected in cases.items():
        masked = mask_text(raw)
        assert masked == expected, raw
        assert "secret" not in masked


def test_masks_generic_connection_string_secrets():
    cases = {
        "Server=db;Password=hunter2;Db=x": "Server=db;Password=[REDACTED:password];Db=x",
        "User Id=sa;Pwd=s3cr3t;": "User Id=sa;Pwd=[REDACTED:password];",
        "ClientSecret=abc~def.ghi;Tenant=t": "ClientSecret=[REDACTED:client-secret];Tenant=t",
        "Endpoint=x;AccessKey=zzz111;": "Endpoint=x;AccessKey=[REDACTED:access-key];",
    }
    for raw, expected in cases.items():
        assert mask_text(raw) == expected, raw


def test_access_key_rule_does_not_refire_on_shared_access_key():
    text = "SharedAccessKey=abc123;Entity=q"
    assert mask_text(text) == "SharedAccessKey=[REDACTED:shared-access-key];Entity=q"


def test_masks_folded_multiline_http_block():
    block = (
        "Executing HTTP request: {\n"
        '  "requestId": "2d0db691-8e70-4335-a8a9-e127715fa678",\n'
        '  "Authorization": "Bearer eyJ.leak.sig",\n'
        '  "uri": "/api/hello?code=leakedkey123"\n'
        "}"
    )
    masked = mask_text(block)
    assert "eyJ.leak.sig" not in masked
    assert "leakedkey123" not in masked
    assert "[REDACTED:bearer-token]" in masked
    assert "[REDACTED:function-key]" in masked
    assert "2d0db691-8e70-4335-a8a9-e127715fa678" in masked


def test_masks_each_secret_class():
    cases = {
        "Authorization: Bearer abc.def.ghi": "Authorization: Bearer [REDACTED:bearer-token]",
        "Authorization: Basic dXNlcjpwYXNz": "Authorization: Basic [REDACTED:basic-auth]",
        "Authorization: abc123def456ghi": "Authorization: [REDACTED:authorization]",
        "GET /api/hello?code=secretkey123": "GET /api/hello?code=[REDACTED:function-key]",
        "x-functions-key: secretkey123": "x-functions-key: [REDACTED:function-key]",
        "AccountKey=Zm9vYmFyMTIz;EndpointSuffix=x": (
            "AccountKey=[REDACTED:storage-key];EndpointSuffix=x"
        ),
        "SharedAccessKey=abc123;Entity=q": "SharedAccessKey=[REDACTED:shared-access-key];Entity=q",
        "https://x?sig=abc%2Fdef&se=2026": "https://x?sig=[REDACTED:sas]&se=2026",
        "SharedAccessSignature=sv=2021&sig=x": "SharedAccessSignature=[REDACTED:sas]",
    }
    for raw, expected in cases.items():
        assert mask_text(raw) == expected, raw


def test_masks_master_key():
    cases = {
        "MasterKey=abc123;X=y": "MasterKey=[REDACTED:function-key];X=y",
        'MasterKey="abc123"': 'MasterKey="[REDACTED:function-key]"',
        "SystemKey=abc123;X=y": "SystemKey=[REDACTED:function-key];X=y",
        'SystemKey="abc123"': 'SystemKey="[REDACTED:function-key]"',
        '"masterKey": "Zm9v"': '"masterKey": "[REDACTED:function-key]"',
        '"systemKey": "Zm9v"': '"systemKey": "[REDACTED:function-key]"',
        "'masterKey': 'Zm9v'": "'masterKey': '[REDACTED:function-key]'",
        '"masterKey":"Zm9v"': '"masterKey":"[REDACTED:function-key]"',
        '"systemKey":Zm9v': '"systemKey":[REDACTED:function-key]',
        '"SystemKEY": "Zm9v"': '"SystemKEY": "[REDACTED:function-key]"',
    }
    for raw, expected in cases.items():
        assert mask_text(raw) == expected, raw


def test_master_key_does_not_fire_on_longer_word():
    text = "AzureWebJobsMasterKey=xyz"
    assert mask_text(text) == text


def test_masks_connection_uri_userinfo():
    cases = {
        "amqp://user:secret@host": "amqp://[REDACTED:connection-credential]@host",
        "postgresql://user:p4ssw0rd@host:5432/db": (
            "postgresql://[REDACTED:connection-credential]@host:5432/db"
        ),
    }
    for raw, expected in cases.items():
        masked = mask_text(raw)
        assert masked == expected, raw
        assert "secret" not in masked
        assert "p4ssw0rd" not in masked


def test_connection_uri_without_userinfo_is_untouched():
    cases = (
        "sb://ns/",
        "http://localhost:7071/api/hello",
        "ftp://user@host",
    )
    for raw in cases:
        assert mask_text(raw) == raw, raw


def test_shared_access_key_name_is_not_masked():
    text = "Endpoint=sb://ns/;SharedAccessKeyName=RootManageSharedAccessKey;SharedAccessKey=abc"
    masked = mask_text(text)
    assert "SharedAccessKeyName=RootManageSharedAccessKey" in masked
    assert "SharedAccessKey=[REDACTED:shared-access-key]" in masked


def test_masking_is_idempotent():
    text = SUCCESS_LOG.read_text() + WORKER_FAIL_LOG.read_text()
    once = mask_text(text)
    assert mask_text(once) == once
    assert once != text


def test_masking_preserves_extraction_tokens():
    text = (
        "Executing 'Functions.hello' (Reason='x', Id=6a8f3658-2b31-4554-aa86-1ee32a9e679b)\n"
        "Executed 'Functions.hello' (Succeeded, Id=6a8f3658, Duration=54ms)\n"
        '  "status": "200",'
    )
    masked = mask_text(text)
    assert masked == text


def test_mask_record_rewrites_message_and_content():
    record = LogRecord(
        message="[ts] Authorization: Bearer leak",
        timestamp=None,
        fields={"content": "Authorization: Bearer leak", "ts": "ts"},
    )
    masked = mask_records([record])[0]
    assert "leak" not in masked.message
    assert "leak" not in masked.fields["content"]
    assert masked.fields["ts"] == "ts"


def _run(argv, stdin_text=""):
    stdout = io.StringIO()
    code = cli.main(
        argv,
        stdin=io.StringIO(stdin_text),
        stdout=stdout,
        stderr=io.StringIO(),
        opener=lambda url: None,
    )
    return code, stdout.getvalue()


def test_cli_parse_masks_secrets_by_default():
    code, out = _run(["parse", str(SUCCESS_LOG)])
    assert code == 0
    dumped = json.dumps(json.loads(out))
    assert "[REDACTED:bearer-token]" in dumped
    assert "[REDACTED:function-key]" in dumped
    assert "Bearer eyJ" not in dumped


def test_cli_no_mask_preserves_raw_secrets():
    code, out = _run(["parse", str(SUCCESS_LOG), "--no-mask"])
    assert code == 0
    dumped = json.dumps(json.loads(out))
    assert "[REDACTED:" not in dumped
    assert "Bearer eyJ" in dumped


def test_cli_record_masks_secrets_by_default():
    code, out = _run(["record", "-o", "-"], stdin_text=SUCCESS_LOG.read_text())
    assert code == 0
    dumped = json.dumps(json.loads(out))
    assert "[REDACTED:bearer-token]" in dumped
    assert "Bearer eyJ" not in dumped


def test_cli_record_no_mask_preserves_raw_secrets():
    code, out = _run(["record", "-o", "-", "--no-mask"], stdin_text=SUCCESS_LOG.read_text())
    assert code == 0
    dumped = json.dumps(json.loads(out))
    assert "[REDACTED:" not in dumped
    assert "Bearer eyJ" in dumped
