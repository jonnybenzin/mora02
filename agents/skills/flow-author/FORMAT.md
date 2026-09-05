# The shape of a flow

A flow is a JSON object with a `name`, an optional `description`, and a list
of `steps`. Every step is an object with exactly ONE key: the op's name, or
`gate`, or `review`.

```json
{
  "name": "lighthouse-clip",
  "description": "A picture from a subject, checked by a human, then a short clip.",
  "steps": [
    {"llm.image_prompt": {"id": "prompt", "subject": {"arg": "subject", "default": "a lighthouse in fog"}}},
    {"image.generate": {"id": "picture", "flow": "photo"}},
    {"review": "Does this picture work? The clip is made only after your yes."},
    {"clip.generate": {"id": "clip", "resolution": "1080p"}},
    {"notify": {"id": "send", "channel": "signal"}}
  ]
}
```

What the keys mean:

- **`id`** — the step's own name. Optional; give one when two steps use the
  same op, and whenever another step refers to this one.
- **`in`** — where the step's input comes from. Left out, it is the previous
  step's output. `"in": "picture"` takes the output of the step with that id.
  `"in": "none"` means the step reads nothing (a producer that happens not to
  be first). A list, `"in": ["a", "b", "c"]`, collects several earlier outputs
  into one step that takes several.
- **`{"from": "<id>"}`** as a parameter value — that parameter takes an
  earlier step's output instead of a fixed value (a music step taking its
  lyrics from one text step and its style from another).
- **`{"arg": "<name>", "default": "..."}`** as a parameter value — the person
  gives this value when they run the flow; `default` is used when they give
  none. This is how what VARIES per run is written.
- **`{"gate": "<question>"}`** — the run stops and asks the person; it goes on
  only after they decide.
- **`{"review": "<question>"}`** — the previous step's output is sent to the
  person first (a picture to their phone), then the run stops and asks.

Parameter names and their allowed values come from `flow_ops`. A value that
is not in a parameter's `choices` is refused by `flow_check`; so is a
parameter the op does not have.
