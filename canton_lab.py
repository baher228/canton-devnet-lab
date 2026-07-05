#!/usr/bin/env python3
"""Tiny Canton JSON Ledger/Admin API helper for the DevNet lab.

Uses only the Python standard library. Secrets come from env vars or `.env`.
"""

from __future__ import annotations

import argparse
import base64
import datetime as dt
import json
import os
import random
import string
import sys
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any


TRANSFER_PREAPPROVAL = "#splice-amulet:Splice.AmuletRules:TransferPreapproval"
TRANSFER_PREAPPROVAL_PROPOSAL = "#splice-wallet:Splice.Wallet.TransferPreapproval:TransferPreapprovalProposal"
HOLDING = "#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding"
TRANSFER_INSTRUCTION = "#splice-api-token-transfer-instruction-v1:Splice.Api.Token.TransferInstructionV1:TransferInstruction"
AMULET_RULES = "#splice-amulet:Splice.AmuletRules:AmuletRules"


def load_dotenv(path: Path = Path(".env")) -> None:
    if not path.exists():
        return
    for raw in path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, value = line.split("=", 1)
        os.environ.setdefault(key.strip(), value.strip().strip("'\""))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise SystemExit(f"missing {name}; copy .env.example to .env and fill it in")
    return value.rstrip("/")


def jwt_payload(token: str) -> dict[str, Any]:
    try:
        payload = token.split(".")[1]
        payload += "=" * (-len(payload) % 4)
        return json.loads(base64.urlsafe_b64decode(payload))
    except Exception as exc:
        raise SystemExit(f"could not decode JWT payload: {exc}") from exc


def pretty(value: Any) -> None:
    print(json.dumps(value, indent=2, sort_keys=True))


class Canton:
    def __init__(self) -> None:
        load_dotenv()
        self.auth_url = require_env("CANTON_AUTH_URL")
        self.ledger_url = require_env("CANTON_LEDGER_URL")
        self.validator_url = require_env("CANTON_VALIDATOR_URL")
        self.client_id = require_env("CANTON_CLIENT_ID")
        self.client_secret = require_env("CANTON_CLIENT_SECRET")
        self._token: str | None = None

    def token(self) -> str:
        if self._token:
            return self._token
        body = urllib.parse.urlencode(
            {
                "grant_type": "client_credentials",
                "client_id": self.client_id,
                "client_secret": self.client_secret,
            }
        ).encode()
        data = self.raw("POST", self.auth_url, "/realms/master/protocol/openid-connect/token", body, auth=False)
        self._token = data["access_token"]
        return self._token

    def user_id(self) -> str:
        return str(jwt_payload(self.token())["sub"])

    def headers(self, auth: bool = True, json_body: bool = True) -> dict[str, str]:
        headers = {"Accept": "application/json"}
        if json_body:
            headers["Content-Type"] = "application/json"
        if auth:
            headers["Authorization"] = f"Bearer {self.token()}"
        return headers

    def raw(self, method: str, base: str, path: str, body: bytes | None = None, auth: bool = True) -> Any:
        url = base.rstrip("/") + path
        req = urllib.request.Request(url, data=body, method=method, headers=self.headers(auth, json_body=False))
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SystemExit(f"{method} {url} failed: HTTP {exc.code}\n{detail}") from exc
        return json.loads(text) if text else None

    def get(self, base: str, path: str) -> Any:
        return self.request("GET", base, path)

    def post(self, base: str, path: str, payload: dict[str, Any]) -> Any:
        return self.request("POST", base, path, payload)

    def request(self, method: str, base: str, path: str, payload: dict[str, Any] | None = None) -> Any:
        body = json.dumps(payload).encode() if payload is not None else None
        url = base.rstrip("/") + path
        req = urllib.request.Request(url, data=body, method=method, headers=self.headers())
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                text = resp.read().decode()
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode(errors="replace")
            raise SystemExit(f"{method} {url} failed: HTTP {exc.code}\n{detail}") from exc
        return json.loads(text) if text else None

    def connected_synchronizer_id(self) -> str:
        data = self.get(self.ledger_url, "/v2/state/connected-synchronizers")
        return data["connectedSynchronizers"][0]["synchronizerId"]

    def dso_party(self) -> str:
        explicit = os.environ.get("CANTON_DSO_PARTY")
        if explicit:
            return explicit
        synchronizer = self.connected_synchronizer_id()
        namespace = synchronizer.split("::", 1)[1]
        return f"DSO::{namespace}"

    def provider_party(self) -> str:
        try:
            return self.get(self.validator_url, "/v0/validator-user")["party_id"]
        except SystemExit:
            return self.get(self.ledger_url, "/v2/authenticated-user")["user"]["primaryParty"]

    def ledger_end(self) -> int:
        return int(self.get(self.ledger_url, "/v2/state/ledger-end")["offset"])

    def acs(self, party: str, ident: str, interface: bool = False, include_blob: bool = False) -> list[dict[str, Any]]:
        if interface:
            identifier_filter = {
                "InterfaceFilter": {
                    "value": {
                        "interfaceId": ident,
                        "includeInterfaceView": True,
                        "includeCreatedEventBlob": include_blob,
                    }
                }
            }
        else:
            identifier_filter = {
                "TemplateFilter": {"value": {"templateId": ident, "includeCreatedEventBlob": include_blob}}
            }
        payload = {
            "eventFormat": {
                "filtersByParty": {party: {"cumulative": [{"identifierFilter": identifier_filter}]}},
                "verbose": True,
            },
            "activeAtOffset": self.ledger_end(),
        }
        return self.post(self.ledger_url, "/v2/state/active-contracts", payload)

    def disclose(self, wrapper: dict[str, Any]) -> dict[str, Any]:
        contract = wrapper.get("contract", wrapper)
        data = {
            "templateId": contract["template_id"],
            "contractId": contract["contract_id"],
            "createdEventBlob": contract["created_event_blob"],
        }
        sid = wrapper.get("domain_id") or wrapper.get("synchronizer_id")
        if sid:
            data["synchronizerId"] = sid
        return data


def random_hint(prefix: str) -> str:
    suffix = "".join(random.choice(string.ascii_lowercase + string.digits) for _ in range(8))
    return f"{prefix}-{suffix}"


def cmd_whoami(c: Canton, _args: argparse.Namespace) -> None:
    pretty(
        {
            "user_id": c.user_id(),
            "ledger_user": c.get(c.ledger_url, "/v2/authenticated-user"),
            "validator_user": c.get(c.validator_url, "/v0/validator-user"),
            "synchronizer": c.connected_synchronizer_id(),
            "dso_party": c.dso_party(),
        }
    )


def cmd_allocate_party(c: Canton, args: argparse.Namespace) -> None:
    hint = args.hint or random_hint("codexlab")
    payload = {"partyIdHint": hint, "synchronizerId": c.connected_synchronizer_id(), "userId": c.user_id()}
    pretty(c.post(c.ledger_url, "/v2/parties", payload))


def cmd_create_proposal(c: Canton, args: argparse.Namespace) -> None:
    provider = args.provider or c.provider_party()
    payload = {
        "commands": [
            {
                "CreateCommand": {
                    "templateId": TRANSFER_PREAPPROVAL_PROPOSAL,
                    "createArguments": {"receiver": args.party, "provider": provider},
                }
            }
        ],
        "userId": c.user_id(),
        "commandId": f"preapproval-proposal-{random_hint('cmd')}",
        "actAs": [args.party],
        "readAs": [],
    }
    pretty(c.post(c.ledger_url, "/v2/commands/submit-and-wait", payload))


def cmd_create_preapproval(c: Canton, args: argparse.Namespace) -> None:
    provider = args.provider or c.provider_party()
    amulet_wrapper = c.get(c.validator_url, "/v0/scan-proxy/amulet-rules")["amulet_rules"]
    rounds = c.get(c.validator_url, "/v0/scan-proxy/open-and-issuing-mining-rounds")
    open_round_wrapper = rounds["open_mining_rounds"][-1]
    featured_wrapper = c.get(c.validator_url, "/v0/scan-proxy/featured-apps/" + urllib.parse.quote(provider, safe=""))[
        "featured_app_right"
    ]
    amulet = amulet_wrapper["contract"]["contract_id"]
    open_round = open_round_wrapper["contract"]["contract_id"]
    featured = featured_wrapper["contract_id"]
    expires = (
        dt.datetime.now(dt.timezone.utc) + dt.timedelta(days=args.days)
    ).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    choice_argument = {
        "context": {
            "amuletRules": amulet,
            "context": {
                "openMiningRound": open_round,
                "issuingMiningRounds": [],
                "validatorRights": [],
                "featuredAppRight": featured,
            },
        },
        "inputs": [],
        "receiver": args.party,
        "provider": provider,
        "expiresAt": expires,
        "expectedDso": args.expected_dso or c.dso_party(),
    }
    payload = {
        "commands": [
            {
                "ExerciseCommand": {
                    "templateId": AMULET_RULES,
                    "contractId": amulet,
                    "choice": "AmuletRules_CreateTransferPreapproval",
                    "choiceArgument": choice_argument,
                }
            }
        ],
        "commandId": f"direct-preapproval-{random_hint('cmd')}",
        "actAs": [provider, args.party],
        "userId": c.user_id(),
        "disclosedContracts": [c.disclose(amulet_wrapper), c.disclose(open_round_wrapper), c.disclose(featured_wrapper)],
    }
    pretty(c.post(c.ledger_url, "/v2/commands/submit-and-wait", payload))


def cmd_status(c: Canton, args: argparse.Namespace) -> None:
    encoded = urllib.parse.quote(args.party, safe="")
    status: dict[str, Any] = {}
    try:
        status["admin_preapproval"] = c.get(c.validator_url, f"/v0/admin/transfer-preapprovals/by-party/{encoded}")
    except SystemExit as exc:
        status["admin_preapproval_error"] = str(exc)
    for name, ident, interface in [
        ("preapproval", TRANSFER_PREAPPROVAL, False),
        ("proposal", TRANSFER_PREAPPROVAL_PROPOSAL, False),
        ("holding", HOLDING, True),
        ("transfer_instruction", TRANSFER_INSTRUCTION, True),
    ]:
        status[name] = len(c.acs(args.party, ident, interface=interface))
    pretty(status)


def cmd_acs(c: Canton, args: argparse.Namespace) -> None:
    pretty(c.acs(args.party, args.identifier, interface=args.interface, include_blob=args.include_blob))


def cmd_archive_proposal(c: Canton, args: argparse.Namespace) -> None:
    payload = {
        "commands": [
            {
                "ExerciseCommand": {
                    "templateId": TRANSFER_PREAPPROVAL_PROPOSAL,
                    "contractId": args.contract_id,
                    "choice": "Archive",
                    "choiceArgument": {},
                }
            }
        ],
        "commandId": f"archive-proposal-{random_hint('cmd')}",
        "actAs": [args.party],
        "userId": c.user_id(),
    }
    pretty(c.post(c.ledger_url, "/v2/commands/submit-and-wait", payload))


def main() -> None:
    parser = argparse.ArgumentParser(description="Canton DevNet low-level lab helper")
    sub = parser.add_subparsers(dest="command", required=True)

    p = sub.add_parser("whoami")
    p.set_defaults(fn=cmd_whoami)

    p = sub.add_parser("allocate-party")
    p.add_argument("hint", nargs="?")
    p.set_defaults(fn=cmd_allocate_party)

    p = sub.add_parser("create-proposal")
    p.add_argument("party")
    p.add_argument("--provider")
    p.set_defaults(fn=cmd_create_proposal)

    p = sub.add_parser("create-preapproval")
    p.add_argument("party")
    p.add_argument("--provider")
    p.add_argument("--expected-dso")
    p.add_argument("--days", type=int, default=30)
    p.set_defaults(fn=cmd_create_preapproval)

    p = sub.add_parser("status")
    p.add_argument("party")
    p.set_defaults(fn=cmd_status)

    p = sub.add_parser("acs")
    p.add_argument("party")
    p.add_argument("identifier")
    p.add_argument("--interface", action="store_true")
    p.add_argument("--include-blob", action="store_true")
    p.set_defaults(fn=cmd_acs)

    p = sub.add_parser("archive-proposal")
    p.add_argument("party")
    p.add_argument("contract_id")
    p.set_defaults(fn=cmd_archive_proposal)

    args = parser.parse_args()
    args.fn(Canton(), args)


if __name__ == "__main__":
    try:
        main()
    except KeyboardInterrupt:
        sys.exit(130)
