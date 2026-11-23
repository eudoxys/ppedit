"""@private Run a cvxopf solve in a child process that can be stopped (issue #130)

`SolveJob` is the handle the server shares between the request that
solves and the requests that read progress or stop the solve. `run` solves
with `ppedit._cvxopf.runopf` in a child process (a new Python interpreter running `_main`, so
it works the same on Linux, macOS and Windows, does not inherit the
server's threads and does not import the server's main script), passing
the inputs and messages as pickles over its stdin and stdout, relays the child's progress
reports to the job, and returns the child's result. `SolveJob.stop()`
kills the child: IPOPT, CLARABEL and CVXPY's model building run in C code,
which a Python thread cannot interrupt, so a process is the only way to
stop a solve at any point. The child runs in its own session (process
group) and ignores SIGINT from its first statement, so Ctrl-C in the
terminal running the server (or a SIGINT sent to the server's process
group) does not interrupt a solve; children still running when the
server exits are killed (`_kill_running`, `atexit`). Running in a child also keeps the server alive
when a solve runs out of memory (the operating system kills the child) and
returns the solver's memory to the system when the solve ends.

Progress reports are dicts (see `ppedit._cvxopf.runopf`, `progress`):
`phase` (`start`, `build`, `derivatives`, `iterate`, `solve`, `results`),
`text` (a short description) and, while IPOPT iterates, `iteration`,
`max_iter`, `objective` (IPOPT's internal objective value),
`inf_pr` (primal infeasibility) and `inf_du` (dual infeasibility).
`SolveJob.status()` adds `running`, `elapsed` (s) and `stopping`.

Caveats
-------

  - The child starts a new Python interpreter and imports cvxopf, which
    adds one to a few seconds to every CVXOPF solve run through `run`.

  - Python warnings raised in the child outside `runopf` are not relayed;
    `runopf` returns its own warnings in its result.

  - The solver's own output (`verbose`) reaches the log only when the solve
    ends: a stopped solve has the progress reports in its log instead.
"""

import atexit
import io
import os
import pickle
import queue
import signal
import subprocess
import sys
import threading
import time

_CHILD = ("import signal; signal.signal(signal.SIGINT,signal.SIG_IGN); "  # first: see _detached
    "from ppedit._solveproc import _main; _main()")

_RUNNING = set()
"""Child processes now solving, killed when the server process exits"""
_RUNNING_LOCK = threading.Lock()

@atexit.register
def _kill_running():
    """Kill the solver processes still running (the server is stopping, e.g.
    Ctrl-C), so none is left behind"""
    with _RUNNING_LOCK:
        procs = list(_RUNNING)
    for proc in procs:
        if proc.poll() is None:
            proc.kill()

def _detached() -> dict:
    """`subprocess.Popen` arguments that keep the child out of the
    terminal's process group, so Ctrl-C (SIGINT) in the terminal running
    the server does not interrupt the solver: only `SolveJob.stop()` ends it"""
    if os.name == "nt":
        return {"creationflags":subprocess.CREATE_NEW_PROCESS_GROUP}
    return {"start_new_session":True}
"""Python code the child process runs"""

POLL = 0.25
"""Seconds between checks of the child process and the stop request"""

class SolveStopped(Exception):
    """The solve was stopped by `SolveJob.stop()`"""

class SolverProcessError(Exception):
    """The solver process failed or ended without a result"""

class SolveJob:
    """Shared state of one solve: progress reports and the stop request

    All methods may be called from any thread."""

    def __init__(self):
        self.started = time.time()
        """When the job was created (`time.time()`)"""
        self.stoppable = False
        """Whether the solve runs in a child process that `stop()` can end"""
        self.done = False
        """Whether the solve has ended"""
        self._stop = threading.Event()
        self._progress = {}
        self._lock = threading.Lock()

    def report(self,progress:dict):
        """Record the latest progress report `progress`"""
        with self._lock:
            self._progress = dict(progress)

    def stop(self) -> bool:
        """Ask for the solve to stop; return whether it can be stopped"""
        self._stop.set()
        return self.stoppable and not self.done

    @property
    def stopping(self) -> bool:
        """Whether `stop()` was called"""
        return self._stop.is_set()

    def status(self) -> dict:
        """Return the latest progress report with `running`, `elapsed` (s),
        `stoppable` and `stopping`"""
        with self._lock:
            out = dict(self._progress)
        out.update(running=not self.done,elapsed=time.time()-self.started,
            stoppable=self.stoppable,stopping=self.stopping)
        return out

def describe(progress:dict) -> str:
    """Return a one-line description of the progress report `progress`"""
    if progress.get("phase") == "iterate" and progress.get("iteration") is not None:
        text = f"IPOPT iteration {progress['iteration']}"
        if progress.get("max_iter"):
            text += f" of at most {progress['max_iter']}"
        if progress.get("inf_pr") is not None:
            text += f", primal infeasibility {progress['inf_pr']:.2e}"
        return text
    return progress.get("text") or ""

def _main():
    """Child process: read the pickled
    `(ppc, formulation, options, series)` from stdin, solve, and write
    pickled `("progress", dict)` messages, then `("result", res, log)` or
    `("error", message, log)`, to the original stdout. File descriptor 1
    is pointed at stderr first, so what the solver prints cannot corrupt
    the messages."""
    signal.signal(signal.SIGINT,signal.SIG_IGN)  # stopped only by SolveJob.stop() (SIGKILL)
    out = os.fdopen(os.dup(1),"wb")
    os.dup2(2,1)
    sys.stdout = sys.stderr
    def send(msg):
        pickle.dump(msg,out)
        out.flush()
    log = io.StringIO()
    try:
        ppc,formulation,options,series = pickle.load(sys.stdin.buffer)
        from ppedit._cvxopf import runopf # pylint: disable=import-outside-toplevel
        res = runopf(ppc,formulation,log,options,series,progress=lambda p: send(("progress",p)))
        send(("result",res,log.getvalue()))
    except Exception as err: # pylint: disable=broad-exception-caught
        send(("error",str(err) or type(err).__name__,log.getvalue()))
    out.close()

def _reader(stream,messages):
    """Thread: put each message from the child's `stream` into `messages`,
    then `None` at the end of the stream"""
    try:
        while True:
            messages.put(pickle.load(stream))
    except Exception: # pylint: disable=broad-exception-caught
        pass  # EOFError at the end; anything else means the child died mid-message
    messages.put(None)

def run(job:SolveJob,ppc:dict,formulation:str,log,options:dict|None=None,
        series:dict|None=None) -> dict:
    """Solve like `ppedit._cvxopf.runopf(ppc,formulation,log,options,series)`
    in a child process, reporting progress to `job`

    Exceptions
    ----------

      - `SolveStopped`: `job.stop()` was called; the child was killed

      - `SolverProcessError`: the solve raised an error (its message) or
        the child ended without a result (e.g. killed for lack of memory)
    """
    env = dict(os.environ)  # find this ppedit even when it is not installed
    root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    env["PYTHONPATH"] = root + (os.pathsep + env["PYTHONPATH"] if env.get("PYTHONPATH") else "")
    job.report({"phase":"start","text":"starting the solver process"})
    proc = subprocess.Popen([sys.executable,"-c",_CHILD],env=env, # pylint: disable=consider-using-with
        stdin=subprocess.PIPE,stdout=subprocess.PIPE,**_detached())
    with _RUNNING_LOCK:
        _RUNNING.add(proc)
    job.stoppable = True
    messages = queue.Queue()
    threading.Thread(target=_reader,args=(proc.stdout,messages),daemon=True).start()
    last = {}
    def where():
        text = describe(last)
        return f"after {time.time()-job.started:.0f} s" + (f" ({text})" if text else "")
    try:
        try:
            pickle.dump((ppc,formulation,options,series),proc.stdin)
            proc.stdin.close()
        except OSError:
            pass  # the child already ended: reported below
        while True:
            if job.stopping:
                proc.kill()
                proc.wait()
                log.write(f"\nSolve stopped by the user {where()}\n")
                raise SolveStopped(f"stopped by the user {where()}")
            try:
                msg = messages.get(timeout=POLL)
            except queue.Empty:
                continue
            if msg is None:
                code = proc.wait()
                log.write(f"\nSolver process ended with exit code {code} {where()}\n")
                raise SolverProcessError("the solver process ended without a result "
                    f"(exit code {code}" + ("; killed by the operating system, possibly for "
                    "lack of memory" if code < 0 or code == 137 else "") + ")")
            if msg[0] == "progress":
                last = msg[1]
                job.report(last)
            elif msg[0] == "result":
                log.write(msg[2])
                return msg[1]
            else:
                log.write(msg[2])
                raise SolverProcessError(msg[1])
    finally:
        job.stoppable = False
        if proc.poll() is None:
            proc.kill()
        proc.wait()
        proc.stdout.close()
        with _RUNNING_LOCK:
            _RUNNING.discard(proc)

