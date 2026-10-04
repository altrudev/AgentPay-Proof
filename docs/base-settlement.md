# Base settlement boundary

AgentPay Proof separates **transaction construction/signing** from **independent settlement observation**.

The authority layer produces an exact ERC-20 transaction request only after a PERMIT. It binds chain ID, token contract, recipient, amount, quote digest and authority digest. AgentPay Proof does not accept a transaction hash as proof.

After broadcast by an operator-controlled wallet, the observer fetches the transaction and receipt from a Base JSON-RPC endpoint and requires a successful receipt plus an ERC-20 `Transfer` log from the expected sender to the exact authorized recipient for the exact quote amount and token contract. Only then is a `FINALIZED` settlement evidence object produced.

No private-key handling is implemented in this repository at this stage. This is intentional: key custody is a separate authority boundary. The competition demo can connect a wallet/signing adapter without placing secret material in AgentPay Proof.

Mainnet Base chain ID is 8453. Token addresses are configuration/evidence values and must be verified against the intended environment before any real-value transaction.
