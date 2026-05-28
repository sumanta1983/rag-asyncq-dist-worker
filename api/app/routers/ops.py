from fastapi import APIRouter, Depends

from .. import circuit
from ..auth.deps import require_admin
from ..deps import get_valkey
from ..models import User

router = APIRouter(prefix="/circuit", tags=["ops"])


@router.get("")
def circuit_status(_admin: User = Depends(require_admin)):
    return circuit.snapshot(get_valkey())


@router.post("/disable")
def disable_circuit(_admin: User = Depends(require_admin)):
    get_valkey().set(circuit.DISABLED_KEY, "1")
    return {"manual_disabled": True}


@router.post("/enable")
def enable_circuit(_admin: User = Depends(require_admin)):
    r = get_valkey()
    r.delete(circuit.DISABLED_KEY)
    r.delete(circuit.OPEN_KEY)
    r.delete(circuit.FAIL_KEY)
    return circuit.snapshot(r)
