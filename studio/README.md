# Autology Studio (interim shell)

A separate application for workspace administrators and members: it lists the use cases of the signed-in
person's workspace with their lifecycle stage, creates use cases from the operator's approved templates, shows
the readiness checks of the next stage and records stage moves (Draft → Simulation → Pilot; Production is not
authorised).

```bash
python -m autology platform examples/platform/platform.json --port 8700   # the platform (engine)
python -m studio --platform http://127.0.0.1:8700 --port 8950             # Studio, its own process
```

* It talks to the platform over HTTP only and never imports the `autology` package; it is not shipped in the
  engine's wheel.
* It forwards only `GET`/`POST` under `/platform/` and `/w/`, with `Authorization` and `Content-Type` only; the
  person's token stays in their browser tab. Every permission, check and stage rule is the platform's.
* The technology of the final Studio is an open owner decision (**D9**). This shell is deliberately small
  (standard library and plain JavaScript) so it can be replaced without touching the engine.

Not in this shell yet: the AI Solution Architect, the visual model editor, member and grant administration,
Excel templates. See `planning/AUTOLOGY_R2_SLICE_REPORT.md`.
