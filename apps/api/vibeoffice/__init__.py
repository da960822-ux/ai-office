"""VibeOffice product layer (docs/VIBEOFFICE_IMPLEMENTATION_GUIDE.md).

This package sits on top of the existing execution runtime in ``apps.api.main``
(jobs, isolation, evidence, review, recovery) and never replaces it.  Slice S1
covers Intake -> Blueprint -> planning approval only:

* ``schema``    - additive SQLite tables + the project state machine
* ``intake``    - deterministic estimation of the 8 planning inputs, <=3 questions
* ``models``    - blueprint pydantic models + a minimal JSON Schema validator
* ``blueprint`` - blueprint build/persist/approve/handoff gate
* ``routes``    - ``/api/vibe/*`` router (included into the app by a human later)

Nothing in this package imports ``apps.api.main`` at module import time.  Every
DB helper does a lazy, function-body import so that ``main`` can keep importing
freely and so that tests which repoint ``main.DB_PATH`` at a temp file still get
the patched value.
"""
