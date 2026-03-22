"""
Token filters and transaction classification for Wallet Auto Trade Detection.

Transaction types:
  DEX_SWAP         – Interaction with a known DEX router → auto trade detection.
  WALLET_TRANSFER  – Wallet-to-wallet send, no router → ignore.
  UNKNOWN_SOURCE   – Tokens received, no router (exchange withdrawal / bridge / OTC) → ask user.
  TOKEN_AIRDROP    – Tokens received with no input value and no swap → ignore.
"""

STABLECOINS = {
    "USDT",
    "USDC",
    "BUSD",
    "DAI",
    "FDUSD",
    "TUSD",
    "USDD",
}

NATIVE_TOKENS = {"SOL", "BNB", "ETH"}

# Well-known DEX router contracts (lowercase) for EVM chains.
KNOWN_DEX_ROUTERS: set[str] = {
    # PancakeSwap v2/v3 (BSC) — critical for BNB → token detection
    "0x10ed43c718714eb63d5aa57b78b54704e256024e",  # PancakeSwap v2 Router
    "0x13f4ea83d0bd40e75c8222255bc855a974568dd4",  # PancakeSwap v3 Router
    "0x05ff2b0db69458a0750badebc4f9e13add608c7f",  # PancakeSwap v1
    "0x325e343f1de602396e256b67efd1b61c3a6b38bd",  # PancakeSwap v2 (alt)
    # Uniswap Universal Router + V2/V3 (Ethereum/Base)
    "0x3fc91a3afd70395cd496c647d5a6cc9d4b2b7fad",
    "0x7a250d5630b4cf539739df2c5dacb4c659f2488d",
    "0xe592427a0aece92de3edee1f18e0157c05861564",
    "0x68b3465833fb72a70ecdf485e0e4c7bd8665fc45",
    # SushiSwap
    "0xd9e1ce17f2641f24ae83637ab66a2cca9c378b9f",
    # 1inch v5/v6
    "0x1111111254eeb25477b68fb85ed929f73a960582",
    "0x111111125421ca6dc452d289314280a0f8842a65",
    # BaseSwap
    "0x327df1e6de05895d2ab08513aadd9313fe505d86",
    # Aerodrome (Base)
    "0xcf77a3ba9a5ca399b7c97c74d54e5b1beb874e43",
}

# First 4 bytes (function selector) of common DEX swap methods.
SWAP_SELECTORS: set[str] = {
    "7ff36ab5",  # swapExactETHForTokens
    "18cbafe5",  # swapExactTokensForETH
    "38ed1739",  # swapExactTokensForTokens
    "8803dbee",  # swapTokensForExactTokens
    "fb3bdb41",  # swapETHForExactTokens
    "5c11d795",  # swapExactTokensForTokensSupportingFeeOnTransferTokens
    "791ac947",  # swapExactTokensForETHSupportingFeeOnTransferTokens
    "b6f9de95",  # swapExactETHForTokensSupportingFeeOnTransferTokens
    "3593564c",  # execute (Uniswap Universal Router)
    "24856bc3",  # multicall (Uniswap V3 Router)
    "ac9650d8",  # multicall (alternate)
    "04e45aaf",  # exactInputSingle (Uniswap V3)
    "b858183f",  # exactInput (Uniswap V3)
    "414bf389",  # exactInputSingle (older)
    "c04b8d59",  # exactInput (older)
    "472b43f3",  # swapExactTokensForTokens (Uniswap V2 Router02)
    "42712a67",  # swapTokensForExactTokens (Uniswap V2 Router02)
}

# Solana DEX program IDs (base58)
KNOWN_SOLANA_DEX_PROGRAMS: set[str] = {
    # Jupiter v6
    "JUP6LkbZbjS1jKKwapdHNy74zcZ3tLUZoi5QNyVTaV4",
    # Jupiter v4
    "JUP4Fb2cqiRUcaTHdrPC8h2gNsA2ETXiPDD33WcGuJB",
    # Raydium AMM v4
    "675kPX9MHTjS2zt1qfr1NYHuzeLXfQM9H24wFSUt1Mp8",
    # Raydium CLMM
    "CAMMCzo5YL8w4VFF8KVHrK22GGUsp5VTaW7grrKgrWqK",
    # Orca Whirlpool
    "whirLbMiicVdio4qvUfM5KAg6Ct8VwpYzGff3uctyCc",
    # Meteora
    "LBUZKhRxPF3XUpBCjp4YzTKgLccjZhTSDM9YuVaPwxo",
}

# Transaction classification labels
TX_DEX_SWAP = "DEX_SWAP"
TX_WALLET_TRANSFER = "WALLET_TRANSFER"
TX_UNKNOWN_SOURCE = "UNKNOWN_SOURCE"
TX_TOKEN_AIRDROP = "TOKEN_AIRDROP"


def is_stablecoin(symbol: str) -> bool:
    if not symbol:
        return False
    return symbol.strip().upper() in STABLECOINS


def is_native_token(symbol: str) -> bool:
    if not symbol:
        return False
    return symbol.strip().upper() in NATIVE_TOKENS


def is_dex_router(address: str) -> bool:
    if not address:
        return False
    return address.strip().lower() in KNOWN_DEX_ROUTERS


def has_swap_selector(input_data: str) -> bool:
    """Return True if the tx input data starts with a known swap function selector."""
    if not input_data or len(input_data) < 10:
        return False
    raw = input_data[2:] if input_data.startswith("0x") else input_data
    selector = raw[:8].lower()
    return selector in SWAP_SELECTORS


def is_solana_dex_program(program_id: str) -> bool:
    if not program_id:
        return False
    return program_id.strip() in KNOWN_SOLANA_DEX_PROGRAMS


def classify_evm_tx(*, to_address: str, input_data: str, direction: str) -> str:
    """
    Classify an EVM transaction into one of the four types.

    Args:
        to_address: The 'to' field of the transaction (what contract was called).
        input_data: The raw input/calldata hex string of the transaction.
        direction: "in" (wallet received tokens) or "out" (wallet sent tokens).

    Returns one of TX_DEX_SWAP, TX_WALLET_TRANSFER, TX_UNKNOWN_SOURCE, TX_TOKEN_AIRDROP.
    """
    if is_dex_router(to_address) or has_swap_selector(input_data):
        return TX_DEX_SWAP

    if direction == "out":
        return TX_WALLET_TRANSFER

    # direction == "in": wallet received tokens but no DEX router involved.
    # Distinguish airdrop from unknown source by checking input data.
    # Empty input = native transfer side-effect or contract-initiated distribution.
    inp = (input_data or "").strip()
    if not inp or inp == "0x" or inp == "0x00":
        return TX_TOKEN_AIRDROP

    return TX_UNKNOWN_SOURCE
