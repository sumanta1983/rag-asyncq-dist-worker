from fastapi import APIRouter

from .. import circuit
from ..deps import get_valkey

router = APIRouter(prefix="/circuit", tags=["ops"])


@router.get("")
def circuit_status():
    """Inspect the current state of the OpenAI breaker."""
    return circuit.snapshot(get_valkey())


@router.post("/disable")
def disable_circuit():
    """Force the breaker open. Stops all OpenAI calls until /circuit/enable is hit."""
    get_valkey().set(circuit.DISABLED_KEY, "1")
    return {"manual_disabled": True}


@router.post("/enable")
def enable_circuit():
    """Clear the manual override. Auto-breaker still applies."""
    r = get_valkey()
    r.delete(circuit.DISABLED_KEY)
    r.delete(circuit.OPEN_KEY)
    r.delete(circuit.FAIL_KEY)
    return circuit.snapshot(r)
