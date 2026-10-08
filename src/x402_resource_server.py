from __future__ import annotations

import base64
from contextlib import closing
from dataclasses import asdict
import json
from pathlib import Path
import sqlite3
from typing import Any

from src.facilitator_admission import FacilitatorRegistry
from src.model import canonical_hash
from src.provider_admission import ProviderRegistry
from src.service import SERVICE_SPECS, ServiceRequest, create_quote, execute
from src.settlement import JsonRpcClient, SettlementError
from src.x402 import (
    EIP3009Authorization,
    X402Error,
    X402Requirement,
    find_eip3009_settlement_transaction,
    observe_eip3009_settlement,
    select_exact_eip3009_requirement,
    settlement_transaction,
)
from src.x402_local_verify import local_verify_response


class X402ResourceError(RuntimeError):
    pass


def _b64_json(value: dict[str, Any]) -> str:
    raw = json.dumps(value, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return base64.b64encode(raw).decode("ascii")


def _decode_b64_json(value: str, code: str) -> dict[str, Any]:
    raw = str(value or "").strip()
    if not raw:
        raise X402ResourceError(code)
    raw += "=" * (-len(raw) % 4)
    try:
        result = json.loads(base64.b64decode(raw, validate=True).decode("utf-8"))
    except Exception as exc:
        raise X402ResourceError(code) from exc
    if not isinstance(result, dict):
        raise X402ResourceError(code)
    return result


def payment_required_header(document: str, *, provider_binding, amount_atomic: int) -> tuple[dict, X402Requirement]:
    request = ServiceRequest(document, "code-analysis-v1")
    resource_url = (
        provider_binding.adapter_id
        + "?request="
        + request.digest
    )
    payment_required = {
        "x402Version": 2,
        "error": "PAYMENT-SIGNATURE header is required",
        "resource": {
            "url": resource_url,
            "description": SERVICE_SPECS["code-analysis-v1"]["description"],
            "mimeType": "application/json",
            "serviceName": "AgentPay Proof",
            "tags": ["analysis", "security", "verifiable"],
        },
        "accepts": [
            {
                "scheme": "exact",
                "network": "eip155:8453",
                "amount": str(amount_atomic),
                "asset": "0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
                "payTo": provider_binding.payment_recipient,
                "maxTimeoutSeconds": 60,
                "extra": {
                    "assetTransferMethod": "eip3009",
                    "paymentFlow": "authorization",
                    "name": "USD Coin",
                    "version": "2",
                },
            }
        ],
        "extensions": {},
    }
    requirement = select_exact_eip3009_requirement(
        payment_required,
        resource_url=resource_url,
        chain_id=8453,
        asset="0x833589fcd6edb6e08f4c7c32d4f71b54bda02913",
        pay_to=provider_binding.payment_recipient,
        amount=amount_atomic,
    )
    return payment_required, requirement


def decode_payment_signature(
    header_value: str,
    *,
    expected_payment_required: dict[str, Any],
    requirement: X402Requirement,
) -> tuple[dict[str, Any], EIP3009Authorization, str]:
    payload = _decode_b64_json(header_value, "x402-payment-signature-invalid")
    if payload.get("x402Version") != 2:
        raise X402ResourceError("x402-payment-payload-version-invalid")
    if payload.get("accepted") != requirement.wire():
        raise X402ResourceError("x402-payment-payload-requirement-mismatch")
    resource = payload.get("resource")
    if resource is not None and resource != expected_payment_required["resource"]:
        raise X402ResourceError("x402-payment-payload-resource-mismatch")
    if payload.get("extensions", {}) != expected_payment_required.get("extensions", {}):
        raise X402ResourceError("x402-payment-payload-extensions-mismatch")
    scheme_payload = payload.get("payload")
    if not isinstance(scheme_payload, dict):
        raise X402ResourceError("x402-payment-payload-scheme-missing")
    raw_auth = scheme_payload.get("authorization")
    signature = str(scheme_payload.get("signature", ""))
    if not isinstance(raw_auth, dict):
        raise X402ResourceError("x402-payment-authorization-missing")
    try:
        authorization = EIP3009Authorization(
            from_address=str(raw_auth["from"]),
            to=str(raw_auth["to"]),
            value=int(str(raw_auth["value"])),
            valid_after=int(str(raw_auth["validAfter"])),
            valid_before=int(str(raw_auth["validBefore"])),
            nonce=str(raw_auth["nonce"]),
        )
    except (KeyError, TypeError, ValueError, X402Error) as exc:
        raise X402ResourceError("x402-payment-authorization-invalid") from exc
    if authorization.to != requirement.pay_to or authorization.value != requirement.amount:
        raise X402ResourceError("x402-payment-authorization-requirement-mismatch")
    return payload, authorization, signature


class X402ResourceJournal:
    def __init__(self, path: str | Path):
        self.path = str(path)
        Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS x402_resource_execution (
                    execution_id TEXT PRIMARY KEY,
                    state TEXT NOT NULL,
                    request_digest TEXT NOT NULL,
                    authorization_digest TEXT NOT NULL,
                    payment_payload_digest TEXT NOT NULL,
                    verification_digest TEXT NOT NULL,
                    artifact_json TEXT,
                    result_json TEXT,
                    resource_result_digest TEXT,
                    transaction_hash TEXT,
                    settlement_json TEXT,
                    receipt_json TEXT,
                    updated_at INTEGER NOT NULL
                )
                """
            )

    def get(self, execution_id: str) -> dict | None:
        with closing(sqlite3.connect(self.path)) as conn:
            conn.row_factory = sqlite3.Row
            row = conn.execute(
                "SELECT * FROM x402_resource_execution WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
        return dict(row) if row else None

    def begin(
        self,
        *,
        execution_id: str,
        request_digest: str,
        authorization_digest: str,
        payment_payload_digest: str,
        verification_digest: str,
        now: int,
    ) -> dict:
        existing = self.get(execution_id)
        if existing is not None:
            expected = (
                request_digest,
                authorization_digest,
                payment_payload_digest,
                verification_digest,
            )
            actual = (
                existing["request_digest"],
                existing["authorization_digest"],
                existing["payment_payload_digest"],
                existing["verification_digest"],
            )
            if actual != expected:
                raise X402ResourceError("x402-resource-idempotency-binding-mismatch")
            return existing
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                INSERT INTO x402_resource_execution(
                    execution_id,state,request_digest,authorization_digest,
                    payment_payload_digest,verification_digest,updated_at
                ) VALUES (?,?,?,?,?,?,?)
                """,
                (
                    execution_id,
                    "VERIFIED",
                    request_digest,
                    authorization_digest,
                    payment_payload_digest,
                    verification_digest,
                    now,
                ),
            )
        return self.get(execution_id)

    def bind_resource(self, execution_id: str, *, artifact: dict, result: dict, digest: str, now: int) -> None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute(
                "SELECT state,resource_result_digest FROM x402_resource_execution WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise X402ResourceError("x402-resource-execution-not-found")
            if row[1] is not None:
                if row[1] != digest:
                    raise X402ResourceError("x402-resource-result-write-once-mismatch")
                return
            if row[0] != "VERIFIED":
                raise X402ResourceError("x402-resource-bind-state-invalid")
            conn.execute(
                """
                UPDATE x402_resource_execution
                SET state='RESOURCE_EXECUTED',artifact_json=?,result_json=?,
                    resource_result_digest=?,updated_at=?
                WHERE execution_id=?
                """,
                (
                    json.dumps(artifact, sort_keys=True, separators=(",", ":")),
                    json.dumps(result, sort_keys=True, separators=(",", ":")),
                    digest,
                    now,
                    execution_id,
                ),
            )

    def bind_settlement(self, execution_id: str, *, tx_hash: str, settlement: dict, receipt: dict, now: int) -> None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            row = conn.execute(
                "SELECT state,transaction_hash,receipt_json FROM x402_resource_execution WHERE execution_id=?",
                (execution_id,),
            ).fetchone()
            if row is None:
                raise X402ResourceError("x402-resource-execution-not-found")
            if row[2] is not None:
                if row[1] != tx_hash:
                    raise X402ResourceError("x402-settlement-write-once-mismatch")
                return
            if row[0] not in {"RESOURCE_EXECUTED", "SETTLEMENT_PENDING", "IN_DOUBT"}:
                raise X402ResourceError("x402-settlement-bind-state-invalid")
            conn.execute(
                """
                UPDATE x402_resource_execution
                SET state='CONSUMED',transaction_hash=?,settlement_json=?,
                    receipt_json=?,updated_at=?
                WHERE execution_id=?
                """,
                (
                    tx_hash,
                    json.dumps(settlement, sort_keys=True, separators=(",", ":")),
                    json.dumps(receipt, sort_keys=True, separators=(",", ":")),
                    now,
                    execution_id,
                ),
            )

    def mark_settlement_pending(self, execution_id: str, *, tx_hash: str | None, now: int) -> None:
        with closing(sqlite3.connect(self.path)) as conn, conn:
            conn.execute(
                """
                UPDATE x402_resource_execution
                SET state='SETTLEMENT_PENDING',transaction_hash=COALESCE(transaction_hash,?),updated_at=?
                WHERE execution_id=? AND state='RESOURCE_EXECUTED'
                """,
                (tx_hash, now, execution_id),
            )


class X402CodeAnalysisResource:
    def __init__(
        self,
        *,
        provider_registry: ProviderRegistry,
        provider_id: str,
        facilitator_registry: FacilitatorRegistry,
        facilitator,
        facilitator_id: str,
        rpc: JsonRpcClient,
        journal: X402ResourceJournal,
        authorization_verifier=local_verify_response,
    ):
        self.provider_registry = provider_registry
        self.provider_id = provider_id
        self.facilitator_registry = facilitator_registry
        self.facilitator = facilitator
        self.facilitator_id = facilitator_id
        self.rpc = rpc
        self.journal = journal
        self.authorization_verifier = authorization_verifier

    def _reconcile_existing(
        self,
        *,
        record: dict,
        requirement: X402Requirement,
        authorization: EIP3009Authorization,
        binding,
        provider_admission,
        fac_binding,
        fac_admission,
        now: int,
    ) -> dict:
        tx_hash = record.get("transaction_hash")
        if not tx_hash:
            try:
                tx_hash = find_eip3009_settlement_transaction(
                    self.rpc, requirement, authorization
                )
            except SettlementError as exc:
                raise X402ResourceError("x402-resource-reconcile-observation-failed") from exc
        if not tx_hash:
            raise X402ResourceError("x402-resource-settlement-still-pending")
        try:
            settlement = observe_eip3009_settlement(
                self.rpc, tx_hash, requirement, authorization
            )
        except SettlementError as exc:
            raise X402ResourceError("x402-resource-settlement-not-observed") from exc
        settlement_wire = {
            "success": True,
            "transaction": tx_hash,
            "network": requirement.network,
            "payer": authorization.from_address,
        }
        resource_result_digest = str(record.get("resource_result_digest") or "")
        if not resource_result_digest:
            raise X402ResourceError("x402-resource-result-missing-for-reconcile")
        receipt = {
            "schema": "agentpay-x402-resource-receipt/1",
            "execution_id": record["execution_id"],
            "provider_binding_digest": binding.digest,
            "provider_admission_digest": provider_admission.digest,
            "facilitator_binding_digest": fac_binding.digest,
            "facilitator_admission_digest": fac_admission.digest,
            "request_digest": record["request_digest"],
            "authorization_digest": record["authorization_digest"],
            "payment_payload_digest": record["payment_payload_digest"],
            "local_verification_digest": record["verification_digest"],
            "resource_result_digest": resource_result_digest,
            "settlement": asdict(settlement),
            "settlement_digest": canonical_hash(asdict(settlement)),
            "state": "CONSUMED",
        }
        receipt["digest"] = canonical_hash(receipt)
        self.journal.bind_settlement(
            record["execution_id"],
            tx_hash=tx_hash,
            settlement=settlement_wire,
            receipt=receipt,
            now=now,
        )
        return {
            "status": "VERIFIED",
            "artifact": json.loads(record["artifact_json"]),
            "service_result": json.loads(record["result_json"]),
            "receipt": receipt,
            "payment_response_header": _b64_json(settlement_wire),
        }

    def challenge(self, document: str, *, now: int) -> dict:
        binding, admission = self.provider_registry.require(
            self.provider_id, "agentpay.code-analysis-v1", now=now
        )
        required, requirement = payment_required_header(
            document, provider_binding=binding, amount_atomic=250000
        )
        return {
            "payment_required": required,
            "payment_required_header": _b64_json(required),
            "requirement": requirement,
            "provider_binding_digest": binding.digest,
            "provider_admission_digest": admission.digest,
        }

    def execute(self, document: str, *, payment_signature_header: str, now: int) -> dict:
        binding, provider_admission = self.provider_registry.require(
            self.provider_id, "agentpay.code-analysis-v1", now=now
        )
        required, requirement = payment_required_header(
            document, provider_binding=binding, amount_atomic=250000
        )
        fac_binding, fac_proof, fac_admission = self.facilitator_registry.require(
            self.facilitator_id,
            scheme=requirement.scheme,
            network=requirement.network,
            asset_contract=requirement.asset,
            now=now,
        )
        if fac_proof.verify_behavior != "not-used-local-independent":
            raise X402ResourceError("x402-resource-facilitator-local-verify-required")
        runtime = (
            getattr(self.facilitator, "facilitator_id", None),
            getattr(self.facilitator, "verify_url", None),
            getattr(self.facilitator, "settle_url", None),
            str(getattr(self.facilitator, "tls_spki_sha256", "")).lower(),
        )
        expected_runtime = (
            fac_binding.facilitator_id,
            fac_binding.verify_url,
            fac_binding.settle_url,
            fac_proof.tls_spki_sha256,
        )
        if runtime != expected_runtime:
            raise X402ResourceError("x402-resource-facilitator-runtime-mismatch")

        payload, authorization, signature = decode_payment_signature(
            payment_signature_header,
            expected_payment_required=required,
            requirement=requirement,
        )
        verification = self.authorization_verifier(
            self.rpc, requirement, authorization, signature, now=now
        )
        if verification.get("isValid") is not True:
            raise X402ResourceError(
                "x402-resource-local-verification-failed:"
                + str(verification.get("invalidReason", "invalid"))
            )

        request = ServiceRequest(document, "code-analysis-v1")
        execution_id = "x402-resource:" + canonical_hash(
            {
                "request": request.digest,
                "authorization": authorization.digest,
                "provider": provider_admission.digest,
                "facilitator": fac_admission.digest,
            }
        )[:32]
        payload_digest = canonical_hash(payload)
        verification_digest = canonical_hash(verification)
        record = self.journal.begin(
            execution_id=execution_id,
            request_digest=request.digest,
            authorization_digest=authorization.digest,
            payment_payload_digest=payload_digest,
            verification_digest=verification_digest,
            now=now,
        )
        if record["state"] == "CONSUMED":
            return {
                "status": "VERIFIED",
                "artifact": json.loads(record["artifact_json"]),
                "service_result": json.loads(record["result_json"]),
                "receipt": json.loads(record["receipt_json"]),
                "payment_response_header": _b64_json(json.loads(record["settlement_json"])),
            }
        if record["state"] in {"SETTLEMENT_PENDING", "IN_DOUBT"}:
            return self._reconcile_existing(
                record=record,
                requirement=requirement,
                authorization=authorization,
                binding=binding,
                provider_admission=provider_admission,
                fac_binding=fac_binding,
                fac_admission=fac_admission,
                now=now,
            )
        if record["state"] != "VERIFIED":
            raise X402ResourceError("x402-resource-reconcile-only:" + record["state"])

        quote = create_quote(
            request,
            now=now,
            amount_atomic=requirement.amount,
            recipient=requirement.pay_to,
            chain_id=requirement.chain_id,
            asset_contract=requirement.asset,
        )
        artifact, service_result = execute(request, quote, now=now)
        result_wire = asdict(service_result)
        resource_result_digest = canonical_hash(
            {
                "request_digest": request.digest,
                "artifact": artifact,
                "service_result": result_wire,
            }
        )
        self.journal.bind_resource(
            execution_id,
            artifact=artifact,
            result=result_wire,
            digest=resource_result_digest,
            now=now,
        )
        self.journal.mark_settlement_pending(execution_id, tx_hash=None, now=now)

        try:
            settled = self.facilitator.settle(payload, requirement.wire())
            tx_hash = settlement_transaction(
                settled,
                payer=authorization.from_address,
                network=requirement.network,
            )
        except X402Error as exc:
            raise X402ResourceError(str(exc)) from exc
        except Exception as exc:
            raise X402ResourceError("x402-resource-settlement-unavailable") from exc

        self.journal.mark_settlement_pending(execution_id, tx_hash=tx_hash, now=now)
        try:
            settlement = observe_eip3009_settlement(
                self.rpc, tx_hash, requirement, authorization
            )
        except SettlementError as exc:
            raise X402ResourceError("x402-resource-settlement-not-observed") from exc

        settlement_wire = {
            "success": True,
            "transaction": tx_hash,
            "network": requirement.network,
            "payer": authorization.from_address,
        }
        receipt = {
            "schema": "agentpay-x402-resource-receipt/1",
            "execution_id": execution_id,
            "provider_binding_digest": binding.digest,
            "provider_admission_digest": provider_admission.digest,
            "facilitator_binding_digest": fac_binding.digest,
            "facilitator_admission_digest": fac_admission.digest,
            "request_digest": request.digest,
            "authorization_digest": authorization.digest,
            "payment_payload_digest": payload_digest,
            "local_verification_digest": verification_digest,
            "resource_result_digest": resource_result_digest,
            "settlement": asdict(settlement),
            "settlement_digest": canonical_hash(asdict(settlement)),
            "state": "CONSUMED",
        }
        receipt["digest"] = canonical_hash(receipt)
        self.journal.bind_settlement(
            execution_id,
            tx_hash=tx_hash,
            settlement=settlement_wire,
            receipt=receipt,
            now=now,
        )
        return {
            "status": "VERIFIED",
            "artifact": artifact,
            "service_result": result_wire,
            "receipt": receipt,
            "payment_response_header": _b64_json(settlement_wire),
        }
