"""
Aerodrome Finance integration for Base network swaps.
Aerodrome is the primary DEX on Base with deep liquidity.
"""

from typing import Optional, Tuple
from web3 import Web3
from web3.contract import Contract
from web3.exceptions import ContractLogicError

from .config import AERODROME_ROUTER_ADDRESS
from .web3_utils import to_checksum


# Aerodrome Router ABI (simplified, includes main swap functions)
AERODROME_ROUTER_ABI = [
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {"name": "amountOutMin", "type": "uint256"},
            {
                "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ],
                "name": "routes",
                "type": "tuple[]"
            },
            {"name": "to", "type": "address"},
            {"name": "deadline", "type": "uint256"}
        ],
        "name": "swapExactTokensForTokens",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "nonpayable",
        "type": "function"
    },
    {
        "inputs": [
            {"name": "amountIn", "type": "uint256"},
            {
                "components": [
                    {"name": "from", "type": "address"},
                    {"name": "to", "type": "address"},
                    {"name": "stable", "type": "bool"},
                    {"name": "factory", "type": "address"}
                ],
                "name": "routes",
                "type": "tuple[]"
            }
        ],
        "name": "getAmountsOut",
        "outputs": [{"name": "amounts", "type": "uint256[]"}],
        "stateMutability": "view",
        "type": "function"
    }
]

# Aerodrome factory addresses (for different pool types)
AERODROME_FACTORY_V2 = "0x420DD381b31aEf6683db6B902084cB0FFECe40Da"  # Volatile & Stable pools
AERODROME_FACTORY_CL = "0x5e7BB104d84c7CB9B682AaC2F3d509f5F406809A"  # Concentrated Liquidity pools


def get_aerodrome_router(w3: Web3) -> Contract:
    """Get Aerodrome router contract instance"""
    router_address = to_checksum(w3, AERODROME_ROUTER_ADDRESS)
    return w3.eth.contract(address=router_address, abi=AERODROME_ROUTER_ABI)


def try_aerodrome_swap_simulation(
    w3: Web3,
    token_in: str,
    token_out: str,
    amount_in: int,
    wallet: str
) -> Optional[Tuple[int, list]]:
    """
    Try to simulate a swap on Aerodrome.
    Returns (output_amount, route) if successful, None otherwise.
    """
    router = get_aerodrome_router(w3)
    token_in = to_checksum(w3, token_in)
    token_out = to_checksum(w3, token_out)
    wallet = to_checksum(w3, wallet)
    
    # Try different route configurations
    # Aerodrome has both stable and volatile pools
    # Only use direct routes - no multi-hop through USDbC
    route_configs = [
        # Direct routes only
        ([(token_in, token_out, False, AERODROME_FACTORY_V2)], "volatile direct"),  # Volatile pool
        ([(token_in, token_out, True, AERODROME_FACTORY_V2)], "stable direct"),     # Stable pool  
        ([(token_in, token_out, False, AERODROME_FACTORY_CL)], "CL direct"),        # Concentrated liquidity
    ]
    
    for routes, route_desc in route_configs:
        try:
            # Format routes for the contract call
            formatted_routes = [
                {
                    "from": r[0],
                    "to": r[1],
                    "stable": r[2],
                    "factory": r[3]
                }
                for r in routes
            ]
            
            # Try to get output amounts
            amounts = router.functions.getAmountsOut(amount_in, formatted_routes).call()
            
            if amounts and len(amounts) > 0:
                output_amount = amounts[-1]  # Last element is final output
                if output_amount > 0:
                    return output_amount, formatted_routes
                    
        except ContractLogicError:
            continue
        except Exception:  # noqa: BLE001
            continue
    
    return None


def build_aerodrome_swap_tx(
    w3: Web3,
    wallet: str,
    private_key: str,
    amount_in: int,
    amount_out_min: int,
    routes: list,
    deadline: int,
    nonce: int,
    gas_price: int,
    chain_id: int
) -> dict:
    """Build Aerodrome swap transaction"""
    router = get_aerodrome_router(w3)
    wallet = to_checksum(w3, wallet)
    
    return router.functions.swapExactTokensForTokens(
        amount_in,
        amount_out_min,
        routes,
        wallet,
        deadline
    ).build_transaction({
        "from": wallet,
        "nonce": nonce,
        "gas": 400_000,
        "gasPrice": gas_price,
        "chainId": chain_id,
    })
