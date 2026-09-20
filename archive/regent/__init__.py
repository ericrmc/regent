"""A harness that stands in for a human product owner.

The harness is the one long-lived process. Every model call, the
super-orchestrator included, is a child process the harness starts and waits on.
The super-orchestrator has no tools. It receives an assembled context and returns
a JSON decision, and the harness applies it.
"""

__version__ = "0.1.0"
