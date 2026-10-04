# Architecture

Agent -> quote -> authority decision -> Base USDC settlement -> service execution -> independent observation -> proof receipt.

The settlement adapter may submit only after PERMIT. The verifier treats settlement, service result, and independent observation as separate evidence domains. Frequency integration is an external boundary; proprietary Frequency internals are not copied into this repository.
