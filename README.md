# canton-devnet-lab

Minimal Canton DevNet lab tooling from the low-level Admin/Ledger API exercise.

No secrets are committed. Put the Keycloak client secret in your environment or
in a local `.env` file.

## Setup

```bash
cp .env.example .env
# edit .env and set CANTON_CLIENT_SECRET
```

Run commands with:

```bash
python3 canton_lab.py whoami
python3 canton_lab.py allocate-party codexlab
python3 canton_lab.py create-preapproval '<party-id>'
python3 canton_lab.py status '<party-id>'
```

Useful generic checks:

```bash
python3 canton_lab.py acs '<party-id>' '#splice-api-token-holding-v1:Splice.Api.Token.HoldingV1:Holding' --interface
python3 canton_lab.py acs '<party-id>' '#splice-api-token-transfer-instruction-v1:Splice.Api.Token.TransferInstructionV1:TransferInstruction' --interface
```

## Last Known Lab State

Party sent to the team:

```text
codexlab-mr42dt7h::12204e94c0e449c0efcd270dd1e68259c36471cebef132e5c7dfc2750fe8c9eed77f
```

Confirmed active preapproval contract:

```text
005e49b2ac9c67ab0e7ee676b7bfd87d8132b8d5d5ad74dc70262c5ecff70e5c2cca121220872e1794690f7ea00f064182995a950dd45685ddbfe603912e5cec262127f9a6
```

Created in update:

```text
1220cc740781dbb606ba724ebe3f2b36c96954817975252d1513ebc494a0cd007c87
```

Final observed state:

```text
TransferPreapproval: 1
TransferPreapprovalProposal: 0
Holding: 0
TransferInstruction: 1
```

The remaining funding step was to ask the team to resend CC to the same party
after the active preapproval existed.
