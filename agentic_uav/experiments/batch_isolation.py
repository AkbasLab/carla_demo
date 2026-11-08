"""Cooperative same-user VM isolation for wall-clock pinned Phase 17 batches."""
from contextlib import contextmanager
from datetime import datetime,timezone
import json
import os
from pathlib import Path
import tempfile


@contextmanager
def batch_isolation(profile,stage,allow_concurrent=False,lock_path=None):
    info=dict(mode='not_required',override=bool(allow_concurrent))
    if profile!='pinned' or stage=='smoke':
        yield info
        return
    if allow_concurrent:
        info.update(mode='concurrent_override',limitation='Resource contention can change wall-clock outcomes')
        yield info
        return
    import fcntl
    path=Path(lock_path) if lock_path is not None else Path(tempfile.gettempdir())/f'carla_demo_phase17_pinned_{os.getuid()}.lock'
    with path.open('a+') as stream:
        try:fcntl.flock(stream,fcntl.LOCK_EX|fcntl.LOCK_NB)
        except BlockingIOError as error:
            raise RuntimeError('Another Phase 17 pinned batch is active on this VM for this user. '
                'Wait for it to finish; --allow-concurrent is an explicit, recorded development override.') from error
        try:
            info.update(mode='exclusive_same_user_vm',lock_path=str(path),pid=os.getpid(),
                acquired_at_utc=datetime.now(timezone.utc).isoformat(),
                limitation='Only cooperating Phase 17 runners are isolated; external VM/model workloads remain possible')
            stream.seek(0);stream.truncate();json.dump(info,stream);stream.flush()
            yield info
        finally:fcntl.flock(stream,fcntl.LOCK_UN)
